# 变更记录

## 0.5.0 — 2026-11-16

### 加固：探针与 JWT 验签

**探针**

- `/health` 仍只回 `{"status":"ok"}`，不带版本号与服务名（存活探针不该被当探测入口用）
- `/ready` 从“只查数据库”扩为“数据库 + 审计目录可写”：审计写不进去等于静默丢证据，
  此时返回 503 与 `{"audit":"readonly"}`，让编排层能识别这类机器
- 新增 `GET /health/detail`（**仅 admin**）：版本、认证模式、审计路径与可写性、
  JWKS 可达性，用于排障时一次问清，而不是逐条试接口
- `/` 不再列接口清单与版本，只留 `service/docs/health/ready`
- 新增 `DOCS_ENABLED`（默认 1，生产建议 0）：关闭后 `/docs`、`/openapi.json` 一律 404，
  不再把完整接口结构白送扫描器

**JWT**

- 验签结果按 `sha256(token | 配置指纹)` 缓存，默认 60 秒且不超过 token 自身 `exp`，
  同一 token 的并发请求不再重复做 RSA 验签（验签是主要 CPU 热点）
- 配置指纹覆盖 `OIDC_DEV_HS256_SECRET` / `OIDC_ISSUER` / `OIDC_AUDIENCE`：
  改配置即失效缓存，避免“换了密钥旧 token 还能过”
- JWKS 的 `kid` 未命中时**强制刷新一次公钥再判定**，支持身份源轮换密钥而不必重启服务
- 新增 `token_cache_stats()` / `clear_caches()`，便于运维观测与测试隔离

**测试**：46 → 54，新增 `/ready` 审计只读降级、`/health/detail` 三级权限、
文档开关 404、根接口字段集合、缓存命中、过期不入缓存、`_jwks(force=True)` 绕缓存 7 项

## 0.4.2 — 2026-11-16

### 修复：Python 3.13/3.14 无法安装依赖

- `pydantic` 由 `==2.11.7` 放宽为 `>=2.12,<3`：2.11.x 没有 cp313/cp314 的 wheel，
  在 3.13/3.14 上会退回源码编译 `pydantic-core`，需要 Rust，导致 `metadata-generation-failed`
- CI `test` job 改为 3.12 / 3.13 / 3.14 矩阵
- `docs/development.md` 补版本支持表与该报错的定位方法
- 其余依赖版本不变，3.12 上仍为原锁定组合

## 0.4.1 — 2026-11-16

### 新增：OIDC 单点登录

- `AUTH_MODE=off|apikey|oidc|both`，未显式设置时沿用 `AUTH_ENABLED`，升级不改变既有行为
- JWT 验签：RS256/RS384/RS512 走 JWKS（5 分钟缓存，支持 `.well-known` 自动发现），HS256 仅在配置 `OIDC_DEV_HS256_SECRET` 时可用
- 校验 iss / aud / exp / iat，错误分别给出可定位的 401 文案
- 角色映射：`OIDC_ROLES_CLAIM`（支持 `realm_access.roles` 这类路径）+ `OIDC_ROLE_MAP`，多角色取最高权限
- 新增 `GET /auth/whoami`：当前身份、角色、认证方式
- 新增 `scripts/dev_token.py` 与 `make token ROLE=admin`，不连身份源也能本地自测
- 文档 `docs/oidc.md`：Keycloak 的 kcadm 建 realm/client/角色/授权命令、Azure AD `roles` 映射、401/403 排障表

### 测试

- 新增 `tests/test_oidc.py` 9 项，全量 46 项通过

## 0.4.0 — 2026-11-16

### 新增：权限与审计

- API Key 认证 + viewer/editor/admin 三级角色，授权规则按 HTTP 方法推导（GET→viewer、写→editor、删→admin）
- `GET /audit`：审计查询，仅 admin，支持按 actor / method / path 前缀 / 状态码过滤
- 审计双落盘：`audit_log` 表（结构化查询）+ JSONL 文件（Linux 工具链处理），密钥只记 6 位指纹
- 写操作全记，读操作只记 401/403；审计写失败不影响主流程
- `python -m app.core.security <role>` 生成随机密钥；`make keygen ROLE=admin`
- 迁移 `0002_audit_log`

### 新增：Linux 运维件

- `deploy/logrotate-data-catalog`：按天轮转、压缩、留 30 份、切后复核 640 appuser:adm
- `deploy/auditd.rules`：监控代码、配置、审计目录与文件、root 提权执行
- `deploy/data-catalog.service`：systemd 单元，含 NoNewPrivileges / ProtectSystem=strict / ReadWritePaths
- `scripts/audit_report.sh`：纯 grep/awk 报表，服务挂掉或被入侵时仍可用

### 测试

- 新增 `tests/test_authz.py` 8 项：401 缺密钥、401 非法密钥、viewer/editor/admin 权限边界、审计落库、审计查询权限、失败鉴权留痕
- 全量 37 项通过，覆盖率 88%

## 0.3.1 — 2026-11-16

### 新增

- `security/linux_security_check.py`：20 项 Linux / 容器安全基线，仅标准库，支持 `--base-url` 附加 HTTP 侧检查与 `--json` 留证，有 FAIL 时退出码 1
- `docs/linux-security.md`：检查项、实测结论、加固清单、与接口安全测试的分工
- `make sec` 与 CI `linux-security` job：本地与流水线同一套基线

### 加固

- 应用统一注入 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`CSP`，L11 由 FAIL 转 PASS
- compose 增加 `user: 10001:10001`、`read_only`、`tmpfs /tmp`、`cap_drop: ALL`、`no-new-privileges`
- 数据库口令改为 `${POSTGRES_PASSWORD}` 注入，compose 不再含字面弱口令

### 测试

- 新增 1 项安全响应头断言，全量 29 项通过

## 0.3.0 — 2026-11-16

### 新增

- 工程基座：`pyproject.toml`（ruff / coverage）、`Makefile`（install/run/test/cov/lint/fmt/seed/migrate/up/down/logs）、依赖全部锁定版本、`.env.example`
- 可观测性：`RequestContextMiddleware`（`X-Request-ID` 透传与生成、`X-Process-Time-ms`）、JSON 结构化日志（`app/core/logging.py`）、`/health` 与 `/ready` 两类探针
- 统一错误模型（`app/core/errors.py`）：`HTTPException` / 校验错误 / 约束冲突 / 未捕获异常收敛为同一形状，字段级错误放进 `error.details`
- 数据库迁移：Alembic + `0001_init` 初始迁移，容器启动默认先迁移再起服务
- 演示数据脚本 `scripts/seed_demo.py`：2 数据源 / 5 表 / 21 字段 / 3 规则 / 6 条血缘，支持直连库或走 HTTP
- 文档体系：`docs/architecture.md`、`docs/api.md`、`docs/development.md`、`docs/testing.md`，README 重写
- CI：`.github/workflows/ci.yml`，lint + test（含覆盖率）+ docker 构建与冒烟

### 变更

- 配置集中到 `app/core/config.py`，`db.py` 从 settings 读取连接串；连接池显式配置
- `create_all` 改为 lifespan 内执行，可用 `AUTO_CREATE_SCHEMA=0` 关闭
- Dockerfile 改为非 root 用户运行、内置 HEALTHCHECK、入口脚本负责迁移
- 版本号 0.2.0 → 0.3.0，`/` 返回服务信息与文档入口

### 测试

- 新增 `tests/test_observability.py` 7 项：健康/就绪、请求 ID 生成与透传、错误体形状、422 字段级定位
- 全量 28 项通过，覆盖率 87%（原 21 项）

## 0.2.0

- 元数据三级模型、三类质量规则、字段级血缘 BFS 溯源
- Swagger UI 本地静态化，摆脱 CDN 依赖
- 21 项单元测试、34 项接口自动化、16 项安全检查、压测与时序证据

## 0.1.0

- 首个可用版本：数据源、表、字段、规则、血缘五组接口
