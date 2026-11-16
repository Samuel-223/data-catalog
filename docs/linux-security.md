# Linux / 容器侧安全测试

接口层的安全检查（注入、畸形输入、越权）只看请求；Linux 侧看的是「服务跑在什么环境里」。
两者互补：接口能挡住的，运行环境未必稳；运行环境收紧的，接口逻辑未必对。

## 怎么跑

```bash
# 只做本地基线（不需要服务在跑）
python3 security/linux_security_check.py

# 服务已启动时，附加 HTTP 面检查（安全头、点文件暴露）
python3 security/linux_security_check.py --base-url http://127.0.0.1:8000

# 结果落盘，供 CI 或复盘留证
python3 security/linux_security_check.py --json security/linux_result.json
```

```bash
# 容器内（验证的是实际运行的镜像，而不是宿主）
docker compose exec api python /app/security/linux_security_check.py
```

退出码：有任一 FAIL → 1，CI 里可直接当门禁。

## 20 项检查

| 编号 | 检查项 | 判定依据 |
|---|---|---|
| L01 | 运行身份非 root | `euid != 0` |
| L02 | 镜像声明非 root | Dockerfile `USER` 非 root |
| L03 | 基础镜像版本固定 | `FROM` 非 `:latest` |
| L04 | 密钥与数据文件权限 | `.env` / `app.db` 不含 group/other 位 |
| L05 | 项目内无全局可写文件 | 递归 `perm & o+w` |
| L06 | 项目内无 SUID 文件 | `find -perm -4000` |
| L07 | compose 运行时加固 | `cap_drop` / `no-new-privileges` / `read_only` / `user` |
| L08b | 容器根文件系统只读 | 容器内写 `/usr/local/lib` 失败 |
| L09 | 有效能力集最小化 | `CapEff` 不含 SYS_ADMIN / NET_ADMIN / SYS_PTRACE / DAC_OVERRIDE |
| L10 | 本项目暴露端口 | compose 只映射 8000，且不映射 <1024 端口 |
| L11 | HTTP 安全响应头 | `X-Content-Type-Options` / `X-Frame-Options` / `CSP` |
| L12 | 点文件与源码不可下载 | `/.git/config`、`/.env`、`/app/main.py` 均 404 |
| L13 | 依赖版本锁定 | 每行 `==` 或带上下界 |
| L14 | 密钥与数据未入库 | `git ls-files` 无 `.env` / 私钥 / `*.sqlite3` |
| L15 | 口令不硬编码 | compose 中口令由环境变量注入且足够长 |
| L16 | 日志不落明文口令 | 扫日志中 `password=…` / `token=…` |
| L17 | 文件描述符上限 | `RLIMIT_NOFILE >= 1024` |
| L18 | 内核网络参数 | `tcp_syncookies=1`，`ip_forward=0` |
| L19 | SSH 基线 | 配置权限、禁 root 登录、禁密码登录 |
| L20 | 时间同步 | `timedatectl` 显示已同步（容器内降级为 INFO） |

## 本轮实测

```text
合计 20 项：PASS 17 / FAIL 0 / INFO 1 / SKIP 2
INFO：时间同步（运行环境无 systemd / 容器继承宿主时间）
SKIP：根文件系统只读（非容器环境）、SSH 基线（未安装 sshd）
```

结果文件：`security/linux_result.json`（本次带 `--base-url` 运行，故 L11/L12 计入 PASS；
不带服务地址时这两项降级为 SKIP，结论为 15 PASS / 4 SKIP）。

## 已落地的加固

| 位置 | 改动 |
|---|---|
| Dockerfile | 非 root 用户 `appuser`、`HEALTHCHECK` 打 `/ready`、入口脚本负责迁移 |
| docker-compose | `user: 10001:10001`、`read_only: true`、`tmpfs: /tmp`、`cap_drop: ALL`、`no-new-privileges` |
| 口令 | compose 不含字面口令，改由 `${POSTGRES_PASSWORD}` 注入，`.env` 不入库 |
| 应用层 | 统一注入 `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` / `CSP` |
| 暴露面 | 静态目录只挂 `app/static`，未整体挂载源码目录 |

## 与接口安全测试的分工

| 层面 | 脚本 | 回答的问题 |
|---|---|---|
| 请求/接口 | `security/security_check.py` | 注入、畸形输入、信息泄露、鉴权缺口 |
| 主机/容器 | `security/linux_security_check.py` | 身份、权限、能力、暴露面、日志与配置基线 |

## 未覆盖（诚实清单）

1. 依赖漏洞扫描（CVE）：需要 `pip-audit` 与漏洞库联网，未纳入本地脚本
2. 容器镜像层扫描（Trivy / Grype）：需在 CI 引入扫描器
3. 主机层面：auditd 规则、SELinux/AppArmor profile、磁盘加密，这些属于运维基线，本脚本只覆盖与服务直接相关的部分
