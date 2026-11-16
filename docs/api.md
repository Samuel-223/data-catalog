# 接口说明

Base URL：`http://127.0.0.1:8000`
所有响应头含 `X-Request-ID`、`X-Process-Time-ms`。
失败统一返回：

```json
{"error": {"code": "not_found", "message": "…", "request_id": "…"}, "detail": "…"}
```

| code | HTTP | 触发条件 |
|---|---|---|
| `bad_request` | 400 | 业务校验失败（如规则类型非法、规则已禁用） |
| `not_found` | 404 | 资源不存在 |
| `conflict` | 400 | 数据库约束冲突（重名、外键缺失） |
| `validation_error` | 422 | 入参形状不合法，`error.details` 给出字段级原因 |
| `internal_error` | 500 | 未捕获异常（不回显堆栈） |
| `service_unavailable` | 503 | 就绪探针查库失败 |

## 运维

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 存活探针，永远 200 |
| GET | `/ready` | 就绪探针，数据库不可达时 503 |
| GET | `/` | 服务名、版本、文档入口 |
| GET | `/docs` | 本地 Swagger UI（静态资源不依赖 CDN） |

## 数据源

**POST /datasources** → 201

```json
{"name": "核心业务库", "type": "mysql", "host": "10.0.0.12:3306", "owner": "交易团队"}
```

| 字段 | 必填 | 约束 |
|---|---|---|
| name | 是 | ≤100 字符，全局唯一 |
| type | 是 | ≤50 字符（mysql/postgresql/hive/…） |
| host / owner / description | 否 | — |

**GET /datasources** — 查询参数 `skip`（默认 0）、`limit`（默认 20，上限 100）

**GET /datasources/{id}** → 200；不存在 → 404
**PUT /datasources/{id}** → 200，字段均可选
**DELETE /datasources/{id}** → 204，级联删除其下表与字段

## 数据表与字段

**POST /tables**

```json
{"datasource_id": 1, "table_name": "ods_order", "layer": "ODS", "owner": "数据平台"}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| datasource_id | 是 | 必须已存在，否则 404 |
| table_name | 是 | ≤200 字符 |
| layer | 否 | ODS / DWD / DIM / ADS |
| description / owner | 否 | — |

**GET /tables** — 参数 `datasource_id`、`skip`、`limit`
**GET/PUT/DELETE /tables/{id}** — 查 / 改 / 删（删除级联字段与规则）

**POST /tables/{id}/columns**

```json
{"column_name": "id_card_no", "data_type": "varchar(32)", "is_sensitive": true,
 "upstream_column_id": 7}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| column_name | 是 | ≤200 字符 |
| data_type | 否 | — |
| is_sensitive | 否 | 默认 false，供脱敏策略取用 |
| upstream_column_id | 否 | 登记时可选，也可后续用 `/lineage` 改 |

**GET /tables/{id}/columns** — 字段列表

## 质量规则

**POST /rules**

```json
{"table_id": 1, "column_id": 3, "rule_type": "range", "threshold": 10000}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| table_id | 是 | 表必须存在，否则 404 |
| column_id | 否 | 字段必须存在，否则 404 |
| rule_type | 是 | `not_null` / `unique` / `range`，其他值 → 400 |
| threshold | 否 | `range` 规则的上界 |
| enabled | 否 | 默认 true |

**GET /rules** — 参数 `table_id`、`enabled`、`skip`、`limit`
**DELETE /rules/{id}** → 204
**POST /rules/{id}/run**

```json
{"values": ["120", "9800", "15000"]}
```

返回 `QualityResultOut`：

| 字段 | 含义 |
|---|---|
| passed | 是否全部合规 |
| abnormal_count | 异常条数 |
| detail | 如「总数 3，超出上界 10000.0 的有 1」 |

规则已禁用 → 400；规则不存在 → 404。
**GET /rules/{id}/results** — 校验历史，按时间倒序

## 血缘

**POST /lineage**

```json
{"column_id": 12, "upstream_column_id": 5}
```

**GET /lineage/{column_id}/upstream** — BFS 向上溯源，返回链路节点列表
**GET /lineage/{column_id}/downstream** — 向下推导影响范围

查询参数 `max_depth` 控制遍历深度，默认 10，用于截断环形血缘。
