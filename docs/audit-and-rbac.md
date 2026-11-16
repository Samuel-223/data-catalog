# 权限与审计（纵深防御第三层）

接口能挡住的攻击在请求层解决；挡不住的部分要靠「谁能做什么」和「做过什么留痕」。
这一层做三件事：认证、授权、审计，配套四份 Linux 运维件。

## 一、角色矩阵

密钥只从环境变量来，不进代码、不进镜像、不进 compose。

```bash
export AUTH_ENABLED=1
export API_KEYS='admin:sk_admin_xxx,editor:sk_editor_yyy,viewer:sk_viewer_zzz'
python -m app.core.security admin      # 生成一个随机 admin 密钥
```

| 角色 | 可读 | 可写 | 可删 | 可查审计 |
|---|---|---|---|---|
| viewer | ✅ | ❌ | ❌ | ❌ |
| editor | ✅ | ✅ | ❌ | ❌ |
| admin | ✅ | ✅ | ✅ | ✅ |

授权规则按 HTTP 方法推导，不按接口一个个写死：

```text
GET / HEAD / OPTIONS → viewer
POST / PUT / PATCH   → editor
DELETE               → admin
GET /audit           → admin（单独收紧）
```

失败响应：

```json
{"error": {"code": "forbidden", "message": "当前角色 viewer 无权执行 POST，需要 editor", "request_id": "…"}}
```

`AUTH_ENABLED=0` 时全部放行，`actor=anonymous`、`role=admin`，仅限本地开发；
生产必须为 1，否则 `/audit` 也会被匿名读。

## 二、审计落盘：一份数据，两个出口

| 出口 | 路径 | 用途 |
|---|---|---|
| SQLite / PostgreSQL 表 `audit_log` | 数据库 | 结构化查询，`GET /audit` 按人/路径/状态码过滤 |
| JSONL 文件 | `AUDIT_LOG_PATH`（默认 `/var/log/data-catalog/audit.jsonl`） | `grep`/`awk`/`jq`/`logrotate` 直接处理，不依赖服务存活 |

记录字段：`ts`、`request_id`、`actor`、`role`、`method`、`path`、`status`、`duration_ms`、`client_ip`。

两条设计取舍：

1. **写操作全记，读操作只记鉴权失败**。全量记 GET 只会把日志刷成噪音，真正的信号（越权尝试）会被淹没。
2. **审计失败不影响主流程**。DB 或文件写失败只打 `ERROR` 日志，请求照常返回——审计不能变成可用性单点。

密钥只落指纹，不落明文：

```json
{"actor": "editor:sk_edi…21", "role": "editor", "method": "POST", ...}
```

## 三、实测链路

```text
无密钥 GET      → 401  unauthorized，actor=unknown
viewer POST     → 403  forbidden，说明需要 editor
editor POST     → 201
editor DELETE   → 403  说明需要 admin
admin DELETE    → 204
admin GET /audit→ 200，返回含 401/403/201/204 全链路
```

报表（`scripts/audit_report.sh`，纯 shell）：

```bash
$ ./scripts/audit_report.sh -f audit.jsonl -n 6
==================== 审计概览 ====================
文件：audit.jsonl   大小：48K   行数：242
----------- 按操作人统计 -----------
  anonymous        222 次
  editor:sk_edi…21   6 次
  viewer:sk_vie…22   4 次
  unknown            4 次
----------- 按状态码统计 -----------
  HTTP 201   186 次 / 200 21 次 / 403 6 次 / 401 6 次
----------- 可疑信号 -----------
  · 403 共 6 次：存在越权尝试，核对 actor 是否为内部账号
  · 未认证调用 4 次（actor=unknown），核对来源 IP 与密钥下发
```

样例见 [`docs/demo/audit_report.txt`](demo/audit_report.txt) 与 [`docs/demo/audit_sample.jsonl`](demo/audit_sample.jsonl)。

## 四、Linux 侧四份运维件

### 1. 日志轮转 `deploy/logrotate-data-catalog`

```bash
sudo cp deploy/logrotate-data-catalog /etc/logrotate.d/data-catalog
sudo logrotate -d /etc/logrotate.d/data-catalog    # 演练，不落盘
sudo logrotate -f /etc/logrotate.d/data-catalog    # 强制切一次
ls -l /var/log/data-catalog/                        # 核对 640 appuser:adm
```

按天切、压缩、留 30 份、切完复核权限。审计文件不能对 other 可读。

### 2. 内核审计 `deploy/auditd.rules`

```bash
sudo cp deploy/auditd.rules /etc/audit/rules.d/data-catalog.rules
sudo augenrules --load
sudo auditctl -l | grep data-catalog                # 确认规则已加载
sudo ausearch -k data-catalog-write | tail -20      # 查应用代码/配置被改
sudo aureport -f -i | head -20                      # 文件访问总览
```

监控四类事件：应用代码写入、配置与密钥文件读写、审计目录与审计文件被动、root 提权执行。

### 3. 服务单元 `deploy/data-catalog.service`

```bash
sudo cp deploy/data-catalog.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now data-catalog
systemctl status data-catalog --no-pager
journalctl -u data-catalog --since today | grep -c '"level": "ERROR"'
```

单里用到的加固项：`NoNewPrivileges`、`ProtectSystem=strict`、`ProtectHome`、
`PrivateTmp`、`MemoryDenyWriteExecute`、`ReadWritePaths=/var/log/data-catalog`、
`UMask=0027`、`LimitNOFILE=4096`。只有审计目录可写，其余全只读。

### 4. 报表 `scripts/audit_report.sh`

```bash
python -m app.core.security admin                    # 生成密钥
AUDIT_LOG_PATH=/var/log/data-catalog/audit.jsonl ./scripts/audit_report.sh
./scripts/audit_report.sh --since 2026-11-16 -n 20   # 只看某天
```

只用 `grep` / `awk` / `sort` / `tail`，在被入侵、服务挂掉、数据库连不上时依然能出结论——
这是把审计写进文件而不是只写进数据库的原因。

## 五、结合查询的手工排查套路

```bash
# 1) 有人在扫接口？看 401/403 的时间分布
grep -E '"status": (401|403)' /var/log/data-catalog/audit.jsonl | cut -c1-20 | uniq -c

# 2) 谁删过东西
grep '"method": "DELETE"' /var/log/data-catalog/audit.jsonl | grep '"status": 204'

# 3) 某个 request_id 的全链路（结合应用日志）
grep '<request_id>' /var/log/data-catalog/audit.jsonl
journalctl -u data-catalog | grep '<request_id>'

# 4) 审计文件本身有没有被人动过
sudo ausearch -k data-catalog-audit -ts today
stat -c '%U %G %a %n' /var/log/data-catalog/audit.jsonl
```

## 六、仍缺的部分

1. 密钥无生命周期管理：没有过期、吊销、轮换流程，只靠改环境变量重启（下一步可做密钥表 + 有效期）
2. 无单点登录：与央企常见的企业身份源（LDAP/OIDC）未对接
3. 审计只覆盖写操作：读操作的完整访问日志需要开全量审计，代价是磁盘与性能
4. 未做审计完整性保护：没有哈希链或 WORM 存储，能防误删，防不住有 root 的篡改（靠 auditd 兜底）
