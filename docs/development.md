# 开发与调试

## 环境准备

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # 测试必须装这份：TestClient 依赖其中的 httpx
make run          # SQLite，热重载，默认 8000 端口
```

需要 PostgreSQL 时：

```bash
export DATABASE_URL='postgresql+psycopg://catalog:catalog123@localhost:5432/catalog'
make run
```

## 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | 支持 sqlite / postgresql+psycopg |
| `AUTO_CREATE_SCHEMA` | `1` | 启动自动建表；生产用迁移时置 0 |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING |
| `LOG_JSON` | `1` | 1 = 一行一个 JSON，0 = 文本日志 |
| `CORS_ORIGINS` | 空 | 逗号分隔，留空则不启用 CORS |

## 目录约定

- 新增一个业务域：在 `app/routers/` 加文件 → `schemas.py` 加模型 → `models.py` 加表 → `main.py` 注册 router
- 新增配置项：只加到 `app/core/config.py` 的 `Settings`，业务代码通过 `settings.xxx` 读取，不直接 `os.getenv`
- 日志：`logger.info("event_name", extra={"extra_fields": {...}})`，字段会自动并入 JSON

## 迁移

```bash
alembic revision --autogenerate -m "描述"   # 先改模型再生成
alembic upgrade head                        # 应用
alembic downgrade -1                        # 回退一步
alembic current                             # 当前版本
```

`migrations/env.py` 从 `settings.database_url` 读取连接串，不需要改 `alembic.ini`。
SQLite 下启用 `render_as_batch=True`，否则删列改列会失败。

## 调试常用手法

```bash
# 看某个请求的全链路日志（先拿到 X-Request-ID）
LOG_JSON=0 LOG_LEVEL=DEBUG uvicorn app.main:app --reload 2>&1 | grep <request_id>

# 只看就绪状态
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/ready

# 打开交互文档
open http://127.0.0.1:8000/docs
```

## 提交前自检

```bash
make lint      # ruff check + format --check
make test      # 28 项，覆盖率门槛人工看
```

CI 会跑同样的命令，本地绿了再推，能省一轮往返。

## Python 版本支持范围

| 版本 | 状态 | 说明 |
|---|---|---|
| 3.12 | ✅ 主力版本 | 依赖锁定基线，CI 与本地验证均在此版本 |
| 3.13 | ✅ CI 验证 | pydantic ≥2.12 提供 cp313 wheel |
| 3.14 | ✅ CI 验证 | 需 pydantic ≥2.12；2.11.x 无 cp314 wheel，会退回源码编译并失败 |

安装依赖失败的典型症状：

```text
error: metadata-generation-failed
╰─> pydantic-core
```

原因不是网络，是 pydantic-core 没有对应 Python 版本的预编译包，pip 退回源码编译、需要 Rust 工具链。
处理方式：`pip install "pydantic>=2.12,<3"`，或把解释器降到 3.12。
