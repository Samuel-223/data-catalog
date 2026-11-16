# 变更记录

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
