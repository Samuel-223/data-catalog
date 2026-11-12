# 数据资产目录与质量校验服务
一个面向数据治理场景的后端服务：登记数据资产元数据、配置质量规则、执行校验、追溯字段级血缘。
## 功能
| 模块 | 能力 |
|---|---|
| 数据源管理 | 数据源增删改查，支持 MySQL / PostgreSQL / Hive 等类型标识 |
| 元数据管理 | 数据表 → 字段两级登记，字段标记敏感级别 |
| 数据质量 | 规则配置（非空 / 唯一 / 值域），规则执行与历史结果留存 |
| 数据血缘 | 字段级上下游关系登记，支持向上追溯与向下影响范围查询 |
## 技术栈
- Python 3.14 / FastAPI
- SQLAlchemy 2.x（DeclarativeBase + Mapped 类型注解）
- SQLite（开发）/ 可切换 PostgreSQL
- Pydantic v2 校验
- Uvicorn
## 快速开始
```bash
python3 -m venv apienv
source apienv/bin/activate
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic

uvicorn app.main:app --host 0.0.0.0 --port 8000
打开 http://127.0.0.1:8000/docs 查看交互文档。
接口一览
POST   /datasources                    创建数据源
GET    /datasources                    分页查询数据源
GET    /datasources/{id}               查询单个数据源
PUT    /datasources/{id}               更新数据源
DELETE /datasources/{id}               删除数据源

POST   /tables                         创建数据表
GET    /tables?datasource_id=          按数据源查表
POST   /tables/{id}/columns            创建字段
GET    /tables/{id}/columns            查询字段列表

POST   /rules                          配置质量规则
GET    /rules?table_id=                查询规则
POST   /rules/{id}/run                 执行校验
GET    /rules/{id}/results             校验历史

POST   /lineage                        登记血缘关系
GET    /lineage/{id}/upstream          向上追溯
GET    /lineage/{id}/downstream        向下查影响范围

## 设计说明

- **数据模型**：数据源 → 数据表 → 字段 三级结构，字段级 `is_sensitive` 支撑脱敏策略，`upstream_column_id` 实现自引用外键形成血缘链
- **校验引擎**：规则与数据解耦，校验以「值集 + 规则」为输入，便于替换数据获取层，无需改动规则逻辑
- **血缘查询**：仅存上游引用，下游用反查推导，避免双向存储不一致；用 BFS + 深度上限规避环形血缘
- **级联删除**：`cascade="all, delete-orphan"` 保证删除数据源时元数据不残留
目录结构
app/
├── db.py          引擎与会话
├── models.py      ORM 模型
├── schemas.py     Pydantic 模型
├── main.py        应用入口
└── routers/
    ├── datasources.py
    ├── tables.py
    ├── rules.py
    └── lineage.py

## 容器化部署

```bash
docker compose up --build
服务	说明
api	FastAPI 应用，映射宿主 8000 端口
db	PostgreSQL 16，数据持久化在 pgdata 数据卷
启动顺序由 `depends_on` + `pg_isready` 健康检查保证，API 在数据库就绪后才启动。
数据库地址通过 `DATABASE_URL` 注入，本地开发默认 SQLite，容器内切换为 PostgreSQL，代码无需修改。
docker compose ps                    # 状态
docker compose logs -f api           # 日志
docker compose exec db psql -U catalog -d catalog -c "\dt"   # 看表
docker compose down                  # 停止
docker compose down -v               # 停止并清除数据

