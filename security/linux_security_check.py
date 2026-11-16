#!/usr/bin/env python3
"""Linux / 容器侧安全基线检查。

只依赖标准库，既能在容器内跑（docker exec），也能直接在宿主机跑。
结论三态：PASS / FAIL / INFO / SKIP，命中 FAIL 时进程退出码为 1。

用法：
    python3 security/linux_security_check.py
    python3 security/linux_security_check.py --base-url http://127.0.0.1:8000
    python3 security/linux_security_check.py --json security/linux_result.json

参数：
    --base-url  有服务在跑时，附加 HTTP 侧检查（目录穿越、点文件暴露、安全响应头）
    --json      结果落盘路径
    --root      项目根目录，默认本脚本上一级
"""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

RESULTS = []


def add(check_id, name, status, detail, hint=""):
    RESULTS.append(
        {
            "id": check_id,
            "name": name,
            "status": status,
            "detail": detail,
            "hint": hint,
        }
    )


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- 身份与权限


def check_runtime_user():
    uid = os.geteuid()
    if uid == 0:
        add(
            "L01",
            "运行身份非 root",
            "FAIL",
            "当前进程 euid=0（root）",
            "容器内加 USER 非 root；宿主上用专用账号启动服务",
        )
    else:
        add("L01", "运行身份非 root", "PASS", f"euid={uid}，非 root")


def check_dockerfile_user(root: Path):
    df = read(root / "Dockerfile")
    if not df:
        add("L02", "镜像声明非 root 用户", "SKIP", "未找到 Dockerfile")
        return
    users = [
        line.split(maxsplit=1)[1].strip()
        for line in df.splitlines()
        if line.strip().upper().startswith("USER ")
    ]
    if not users:
        add(
            "L02",
            "镜像声明非 root 用户",
            "FAIL",
            "Dockerfile 无 USER 指令，默认以 root 运行",
            "补 USER appuser",
        )
    elif users[-1].lower() in {"root", "0"}:
        add("L02", "镜像声明非 root 用户", "FAIL", f"USER {users[-1]} 仍为 root", "改为普通用户")
    else:
        add("L02", "镜像声明非 root 用户", "PASS", f"USER {users[-1]}")


def check_base_image_pinned(root: Path):
    df = read(root / "Dockerfile")
    if not df:
        add("L03", "基础镜像版本固定", "SKIP", "未找到 Dockerfile")
        return
    for line in df.splitlines():
        if line.strip().upper().startswith("FROM "):
            image = line.split()[1]
            if image.endswith(":latest") or ":" not in image:
                add(
                    "L03",
                    "基础镜像版本固定",
                    "FAIL",
                    f"{image} 未固定版本",
                    "固定到具体 tag 或 digest",
                )
                return
            add("L03", "基础镜像版本固定", "PASS", image)
            return
    add("L03", "基础镜像版本固定", "SKIP", "无可解析的 FROM 行")


def check_file_modes(root: Path):
    sensitive = [root / ".env", root / "app.db"]
    bad = []
    for path in sensitive:
        if not path.exists():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            bad.append(f"{path.name} 权限 {oct(mode)}（同组/其他用户可读写）")
    if bad:
        add("L04", "密钥与数据文件权限", "FAIL", "；".join(bad), "chmod 600 .env app.db")
    else:
        add("L04", "密钥与数据文件权限", "PASS", "敏感文件不存在或权限已收紧")


def check_world_writable(root: Path):
    hits = []
    for path in root.rglob("*"):
        if ".git/" in str(path) or not path.is_file():
            continue
        try:
            if path.stat().st_mode & stat.S_IWOTH:
                hits.append(str(path.relative_to(root)))
        except OSError:
            continue
        if len(hits) >= 5:
            break
    if hits:
        add(
            "L05",
            "项目内无全局可写文件",
            "FAIL",
            f"示例：{', '.join(hits[:5])}",
            "chmod o-w <file>",
        )
    else:
        add("L05", "项目内无全局可写文件", "PASS", "未发现 other 可写文件")


def check_suid(root: Path):
    out = sh(["find", str(root), "-xdev", "-perm", "-4000", "-type", "f"])
    files = [line for line in out.splitlines() if line.strip()]
    if files:
        add("L06", "项目内无 SUID 文件", "FAIL", f"{len(files)} 个：{files[:3]}", "移除 setuid 位")
    else:
        add("L06", "项目内无 SUID 文件", "PASS", "未发现 SUID 文件")


# ---------------------------------------------------------------- 容器加固


def check_compose_hardening(root: Path):
    compose = read(root / "docker-compose.yml")
    if not compose:
        add("L07", "compose 运行时加固", "SKIP", "未找到 docker-compose.yml")
        return
    missing = []
    if "cap_drop" not in compose:
        missing.append("cap_drop: ALL")
    if "no-new-privileges" not in compose:
        missing.append("no-new-privileges")
    if "read_only" not in compose:
        missing.append("read_only: true")
    if "user:" not in compose.lower():
        missing.append("user（显式指定非 root）")
    if missing:
        add(
            "L07",
            "compose 运行时加固",
            "FAIL",
            "缺少：" + "、".join(missing),
            "补齐见 docs/linux-security.md",
        )
    else:
        add(
            "L07",
            "compose 运行时加固",
            "PASS",
            "cap_drop / no-new-privileges / read_only / user 均已声明",
        )


def check_capabilities():
    status = read(Path("/proc/self/status"))
    line = [ln for ln in status.splitlines() if ln.startswith("CapEff:")]
    if not line:
        add("L08", "有效能力集最小化", "SKIP", "容器外或 /proc 不可读")
        return
    cap_hex = int(line[0].split()[1], 16)
    # CAP_SYS_ADMIN(21)、CAP_NET_ADMIN(12)、CAP_SYS_PTRACE(19)、CAP_DAC_OVERRIDE(1)
    dangerous = {
        21: "CAP_SYS_ADMIN",
        12: "CAP_NET_ADMIN",
        19: "CAP_SYS_PTRACE",
        1: "CAP_DAC_OVERRIDE",
    }
    held = [name for bit, name in dangerous.items() if cap_hex & (1 << bit)]
    if held:
        add(
            "L09",
            "有效能力集最小化",
            "FAIL",
            "持有：" + "、".join(held),
            "compose 加 cap_drop: [ALL]",
        )
    else:
        add("L09", "有效能力集最小化", "PASS", "未持有高风险能力")


def check_readonly_rootfs():
    if not Path("/.dockerenv").exists():
        add("L08b", "根文件系统只读", "SKIP", "非容器环境，跳过")
        return
    probe = Path("/usr/local/lib/__write_probe__")
    try:
        probe.write_text("x")
        probe.unlink()
        add("L08b", "根文件系统只读", "FAIL", "容器根文件系统可写", "compose 加 read_only: true")
    except OSError:
        add("L08b", "根文件系统只读", "PASS", "根文件系统只读")


# ---------------------------------------------------------------- 网络面


def check_listen_ports(root: Path):
    """只看本项目 compose 声明的暴露面，避免把宿主上别的服务算进来。"""
    compose = read(root / "docker-compose.yml")
    mapping = re.findall(r'-\s*"(\d+):(\d+)"', compose)
    if not mapping:
        add("L10", "本项目暴露端口", "INFO", "compose 未声明端口映射，无法判定")
        return
    issues = []
    for host_port, _container_port in mapping:
        if int(host_port) < 1024:
            issues.append(f"映射到特权端口 {host_port}")
        if int(host_port) != 8000:
            issues.append(f"额外暴露 {host_port}")
    listening = sorted({int(m) for m in re.findall(r'-\s*"(\d+):', compose)})
    if issues:
        add("L10", "本项目暴露端口", "FAIL", "；".join(issues), "只保留 8000，且不映射特权端口")
    else:
        add("L10", "本项目暴露端口", "PASS", f"仅映射 {listening}")


def check_security_headers(base_url: str):
    if not base_url:
        add("L11", "HTTP 安全响应头", "SKIP", "未提供服务地址，跳过")
        return
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except (urllib.error.URLError, OSError) as exc:
        add("L11", "HTTP 安全响应头", "SKIP", f"服务不可达：{exc}")
        return
    missing = [
        h
        for h in ("x-content-type-options", "x-frame-options", "content-security-policy")
        if h not in headers
    ]
    if missing:
        add("L11", "HTTP 安全响应头", "FAIL", "缺少：" + "、".join(missing), "中间件统一注入三个头")
    else:
        add("L11", "HTTP 安全响应头", "PASS", "三类头齐全")


def check_dotfile_exposure(base_url: str):
    if not base_url:
        add("L12", "点文件与源码不可下载", "SKIP", "未提供服务地址，跳过")
        return
    paths = ["/.git/config", "/.env", "/requirements.txt", "/app/main.py"]
    leaked = []
    for path in paths:
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=5) as resp:
                if resp.status == 200:
                    leaked.append(path)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            continue
    if leaked:
        add(
            "L12",
            "点文件与源码不可下载",
            "FAIL",
            "可下载：" + "、".join(leaked),
            "静态目录只挂 app/static，勿整包挂载",
        )
    else:
        add("L12", "点文件与源码不可下载", "PASS", "四类路径均 404")


# ---------------------------------------------------------------- 依赖与密钥


def check_locked_deps(root: Path):
    req = read(root / "requirements.txt")
    if not req:
        add("L13", "依赖版本锁定", "SKIP", "未找到 requirements.txt")
        return
    loose = []
    for line in req.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" not in line and "<" not in line:
            loose.append(line)
    if loose:
        add("L13", "依赖版本锁定", "FAIL", f"{len(loose)} 项未锁版本：{loose[:3]}", "改成 ==")
    else:
        add("L13", "依赖版本锁定", "PASS", "全部锁定或带上下界约束")


def check_secret_committed(root: Path):
    tracked = sh(["git", "-C", str(root), "ls-files"])
    risks = [
        f
        for f in tracked.splitlines()
        if re.search(r"(^|/)(\.env|.*\.pem|.*\.key|id_rsa)$", f)
        or f.endswith(".sqlite3")
        or f.endswith("app.db")
    ]
    if risks:
        add(
            "L14",
            "密钥与数据未入库",
            "FAIL",
            "被跟踪：" + "、".join(risks[:5]),
            "git rm --cached 并补 .gitignore",
        )
    else:
        add("L14", "密钥与数据未入库", "PASS", "未跟踪 .env / 私钥 / 数据库文件")


def check_hardcoded_password(root: Path):
    compose = read(root / "docker-compose.yml")
    if not compose:
        add("L15", "口令不硬编码", "SKIP", "未找到 compose")
        return
    m = re.search(r"POSTGRES_PASSWORD:\s*(\S+)", compose)
    if m and "$" in m.group(1):
        add("L15", "口令不硬编码", "PASS", f"从环境变量注入：{m.group(1)}")
        return
    if m and len(m.group(1)) < 16:
        add(
            "L15",
            "口令不硬编码",
            "FAIL",
            f"compose 内置弱口令（{len(m.group(1))} 位）",
            "改从 .env 注入随机口令",
        )
    else:
        add("L15", "口令不硬编码", "PASS", "未检出短口令")


def check_log_secret_leak(root: Path):
    candidates = [Path("/tmp/api.log"), Path("/tmp/api2.log"), root / "logs" / "app.log"]
    leaks = []
    pattern = re.compile(r"(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s\"']{6,}", re.I)
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in pattern.finditer(text):
            leaks.append(f"{path.name}: {m.group(0)[:40]}")
    if leaks:
        add("L16", "日志不落明文口令", "FAIL", "、".join(leaks[:3]), "日志脱敏或禁止打印请求体")
    else:
        add("L16", "日志不落明文口令", "PASS", "未在日志中发现明文凭据")


# ---------------------------------------------------------------- 宿主机基线


def check_ulimit():
    try:
        soft, _hard = __import__("resource").getrlimit(__import__("resource").RLIMIT_NOFILE)
    except (OSError, ValueError):
        add("L17", "文件描述符上限", "SKIP", "无法读取 RLIMIT_NOFILE")
        return
    if soft < 1024:
        add("L17", "文件描述符上限", "FAIL", f"soft limit {soft} < 1024", "ulimit -n 4096")
    else:
        add("L17", "文件描述符上限", "PASS", f"soft limit {soft}")


def check_kernel_net():
    props = {}
    for key in ("net.ipv4.tcp_syncookies", "net.ipv4.ip_forward"):
        path = Path("/proc/sys") / key.replace(".", "/")
        props[key] = read(path).strip()
    syncookies = props.get("net.ipv4.tcp_syncookies")
    ip_forward = props.get("net.ipv4.ip_forward")
    if not syncookies:
        add("L18", "内核网络参数", "SKIP", "容器内不可读 /proc/sys/net")
        return
    problems = []
    if syncookies != "1":
        problems.append("tcp_syncookies != 1（SYN Flood 防护关闭）")
    if ip_forward not in {"0", ""}:
        problems.append("ip_forward=1（若无需路由应关闭）")
    if problems:
        add("L18", "内核网络参数", "FAIL", "；".join(problems), "sysctl 调整并写入 /etc/sysctl.d")
    else:
        add("L18", "内核网络参数", "PASS", "syncookies 开启，未开启转发")


def check_ssh():
    cfg = Path("/etc/ssh/sshd_config")
    if not cfg.exists():
        add("L19", "SSH 基线", "SKIP", "未安装 sshd（容器常态）")
        return
    mode = stat.S_IMODE(cfg.stat().st_mode)
    text = read(cfg)
    problems = []
    if mode & 0o022:
        problems.append(f"sshd_config 权限 {oct(mode)} 过宽")
    if re.search(r"^\s*PermitRootLogin\s+yes", text, re.I | re.M):
        problems.append("允许 root 直接登录")
    if re.search(r"^\s*PasswordAuthentication\s+yes", text, re.I | re.M):
        problems.append("开启密码登录（建议密钥登录）")
    if problems:
        add("L19", "SSH 基线", "FAIL", "；".join(problems), "PermitRootLogin no + 密钥登录")
    else:
        add("L19", "SSH 基线", "PASS", "禁用 root 登录与密码登录")


def check_time_sync():
    out = sh(["timedatectl"])
    if out and "synchronized: yes" in out:
        add("L20", "时间同步", "PASS", "已与 NTP 同步")
    elif Path("/.dockerenv").exists():
        add("L20", "时间同步", "INFO", "容器继承宿主时间，需在宿主机校验")
    elif not out.strip():
        add("L20", "时间同步", "INFO", "无 timedatectl（非 systemd 环境），需在宿主机自行校验")
    else:
        add("L20", "时间同步", "FAIL", "未开启时间同步", "systemctl enable --now chronyd")


CHECKS_SUMMARY = """检查覆盖：运行身份、镜像与 compose 加固、能力集、根文件系统、
文件权限、SUID、监听端口、HTTP 安全头、点文件暴露、依赖锁定、
密钥入库、口令硬编码、日志泄漏、资源上限、内核网络、SSH、时间同步。"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Linux/容器安全基线检查")
    parser.add_argument("--base-url", default="", help="服务地址，提供后附加 HTTP 侧检查")
    parser.add_argument("--json", default="", help="结果落盘路径")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    root = Path(args.root).resolve()

    check_runtime_user()
    check_dockerfile_user(root)
    check_base_image_pinned(root)
    check_file_modes(root)
    check_world_writable(root)
    check_suid(root)
    check_compose_hardening(root)
    check_capabilities()
    check_readonly_rootfs()
    check_listen_ports(root)
    check_security_headers(args.base_url)
    check_dotfile_exposure(args.base_url)
    check_locked_deps(root)
    check_secret_committed(root)
    check_hardcoded_password(root)
    check_log_secret_leak(root)
    check_ulimit()
    check_kernel_net()
    check_ssh()
    check_time_sync()

    for r in RESULTS:
        print(f"[{r['status']:4}] {r['id']:5} {r['name']} — {r['detail']}")

    counts = {
        s: sum(1 for r in RESULTS if r["status"] == s) for s in ("PASS", "FAIL", "INFO", "SKIP")
    }
    print(
        f"\n合计 {len(RESULTS)} 项：PASS {counts['PASS']} / FAIL {counts['FAIL']} / INFO {counts['INFO']} / SKIP {counts['SKIP']}"
    )

    if args.json:
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "root": str(root),
            "base_url": args.base_url or None,
            "counts": counts,
            "results": RESULTS,
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"结果已写入 {args.json}")

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
