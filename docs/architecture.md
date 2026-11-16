# 架构与设计取舍

## 分层

```
客户端 / Swagger UI
        │ HTTP
        ▼
┌───────────────────────────────────────────────┐
│ FastAPI 应用                                   │
│  middleware  RequestContextMiddleware（请求 ID）│
│  errors      HTTPException / 校验 / 约束 / 500  │
│  routers     datasources · tables · rules       │
│              lineage · health                   │
│  schemas     Pydantic v2 入出参                 │
│  models      SQLAlchemy 2.x 声明式模型          │
│  db          引擎、连接池、会话                  │
└───────────────────────────────────────────────┘
        │ psycopg / sqlite3
        ▼
   PostgreSQL 16 / SQLite
```

依赖方向单向：`routers → schemas/models → db`，`core` 只被依赖、不反向依赖任何业务模块，
因此换数据库、加鉴权、加限流都不需要改动业务代码。

## 数据模型

```
datasource ──< table_meta ──< column_meta
                   │              │
                   └──< quality_rule ──< quality_result
                                  │
column_meta.upstream_column_id ──┘（自引用，指向同表另一条字段记录）
```

| 表 | 作用 | 关键约束 |
|---|---|---|
| `datasource` | 数据源登记 | `name` 唯一索引 |
| `table_meta` | 表级元数据（含分层 layer） | `datasource_id` 外键 + 级联删除 |
| `column_meta` | 字段级元数据（类型、敏感级别） | `upstream_column_id` 自引用 |
| `quality_rule` | 规则定义（not_null/unique/range） | `rule_type` + 可选阈值 |
| `quality_result` | 每次执行的结论 | 保留 `passed` / `abnormal_count` / `detail` |

## 四个设计取舍

### 1. 规则与数据解耦

校验接口的输入是「值集 + 规则」，不是「数据库连接 + SQL」。
好处是规则逻辑可以被单元测试直接覆盖，接入真实数据库时只需换掉取数层；
代价是当前不具备主动扫描能力，需要调用方把数据传进来。

### 2. 血缘单向存储

只保存 `upstream_column_id`，下游通过反查推导。
双向存储看起来查询更快，但两条边必须同时更新，一旦漏写就出现「A 说 B 是下游、B 不认」，
排查成本远高于一次反查。

### 3. BFS + 深度上限

向上溯源和向下推影响都用广度优先，并设 `max_depth`。
血缘图在真实系统里经常出现环（人工录入错误、跨系统回环），
不设上限会直接把服务拖死；设了上限，遇到环只是截断，不会崩。

### 4. 双层校验，错误出口唯一

Pydantic 负责入参形状（必填、类型、长度），数据库负责约束（唯一、外键）。
两层都可能失败，但出口只有一个：`app/core/errors.py` 把
`HTTPException`、`RequestValidationError`、`IntegrityError`、未捕获异常
统一成同一形状的响应体，调用方不需要按异常类型分别处理。

## 可观测性

| 关注点 | 做法 |
|---|---|
| 单请求定位 | `X-Request-ID` 响应头 + 日志字段 `request_id`（contextvar 传递） |
| 耗时 | `X-Process-Time-ms`，日志 `duration_ms` |
| 存活 vs 就绪 | `/health` 只返回进程状态；`/ready` 执行 `SELECT 1`，失败返回 503 |
| 日志格式 | 一行一个 JSON（`LOG_JSON=1`），便于日志平台解析 |
| 500 处理 | 统一兜底，响应不含堆栈，堆栈只进日志 |

## 容量

连接池 `pool_size=10`、`max_overflow=20`，理论并发上限 30；
压测数据（50 并发 TPS 1194）是在早期 `pool_size=20 / max_overflow=40` 配置下取得，
调整连接池后需重跑压测复核。瓶颈始终在连接数而非 CPU——每个请求占一条连接，
超出部分排队，排队超过 `pool_timeout` 即超时。
