"""灌入演示数据：2 个数据源 / 5 张表 / 21 个字段 / 3 条规则并执行校验。

用法：
    python scripts/seed_demo.py                 # 直接写库（SQLite 或 .env 中的 DATABASE_URL）
    BASE_URL=http://localhost:8000 python scripts/seed_demo.py   # 走 HTTP 接口（推荐用于演示）
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# (数据源, 表, 层级, 描述, [(字段, 类型, 是否敏感)])
PLAN = [
    (
        {"name": "核心业务库", "type": "mysql", "host": "10.0.0.12:3306", "owner": "交易团队"},
        {
            "table_name": "ods_order",
            "layer": "ODS",
            "description": "订单原始表，来自业务库每日增量",
            "owner": "数据平台",
        },
        [
            ("id", "bigint", False),
            ("order_no", "varchar(32)", False),
            ("customer_id", "bigint", True),
            ("amount", "decimal(18,2)", False),
            ("created_at", "datetime", False),
        ],
    ),
    (
        {"name": "核心业务库", "type": "mysql", "host": "10.0.0.12:3306", "owner": "交易团队"},
        {
            "table_name": "dwd_order_detail",
            "layer": "DWD",
            "description": "订单明细清洗层，按订单号聚合金额",
            "owner": "数据平台",
        },
        [
            ("order_id", "bigint", False),
            ("order_no", "varchar(32)", False),
            ("pay_amount", "decimal(18,2)", False),
            ("pay_status", "varchar(16)", False),
        ],
    ),
    (
        {"name": "核心业务库", "type": "mysql", "host": "10.0.0.12:3306", "owner": "交易团队"},
        {
            "table_name": "ads_order_summary",
            "layer": "ADS",
            "description": "订单汇总应用层，供经营看板使用",
            "owner": "经营分析",
        },
        [
            ("stat_date", "date", False),
            ("order_cnt", "bigint", False),
            ("gmv", "decimal(18,2)", False),
        ],
    ),
    (
        {
            "name": "客户主数据库",
            "type": "postgresql",
            "host": "10.0.0.21:5432",
            "owner": "客户团队",
        },
        {
            "table_name": "dim_customer",
            "layer": "DIM",
            "description": "客户维度表，含证件号等敏感字段",
            "owner": "客户团队",
        },
        [
            ("customer_id", "bigint", False),
            ("customer_name", "varchar(64)", True),
            ("id_card_no", "varchar(32)", True),
            ("mobile", "varchar(32)", True),
            ("city", "varchar(32)", False),
        ],
    ),
    (
        {
            "name": "客户主数据库",
            "type": "postgresql",
            "host": "10.0.0.21:5432",
            "owner": "客户团队",
        },
        {
            "table_name": "rpt_daily_metrics",
            "layer": "ADS",
            "description": "日报指标表，由汇总任务每日生成",
            "owner": "经营分析",
        },
        [
            ("stat_date", "date", False),
            ("active_user_cnt", "bigint", False),
            ("order_cnt", "bigint", False),
            ("refund_rate", "decimal(6,4)", False),
        ],
    ),
]

# 血缘：下游字段 -> 上游字段（表名, 字段名）
LINEAGE = [
    ("dwd_order_detail", "order_id", "ods_order", "id"),
    ("dwd_order_detail", "order_no", "ods_order", "order_no"),
    ("dwd_order_detail", "pay_amount", "ods_order", "amount"),
    ("ads_order_summary", "gmv", "dwd_order_detail", "pay_amount"),
    ("ads_order_summary", "order_cnt", "dwd_order_detail", "order_id"),
    ("rpt_daily_metrics", "order_cnt", "ads_order_summary", "order_cnt"),
]

RULES = [
    ("ods_order", "order_no", "not_null", None, [f"OD{1000 + i}" for i in range(20)]),
    ("ods_order", "id", "unique", None, [1, 2, 3, 3, 4, 5, 5, 6]),
    ("dwd_order_detail", "pay_amount", "range", 10000, ["120", "9800", "15000", "3200", "26000"]),
]


def _http():
    import httpx

    return httpx.Client(base_url=BASE_URL, timeout=10)


def _db():
    from app import models  # noqa: F401
    from app.db import Base, SessionLocal, engine

    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def main() -> None:
    if BASE_URL:
        seed_http()
    else:
        seed_db()
    print("演示数据写入完成")


def seed_http() -> None:
    c = _http()
    ds_ids, table_ids, col_ids = {}, {}, {}
    for ds, table, cols in PLAN:
        ds_id = next(
            (
                x["id"]
                for x in c.get("/datasources", params={"limit": 100}).json()
                if x["name"] == ds["name"]
            ),
            None,
        )
        if ds_id is None:
            ds_id = c.post("/datasources", json=ds).json()["id"]
        ds_ids[ds["name"]] = ds_id
        table_id = next(
            (
                x["id"]
                for x in c.get("/tables", params={"datasource_id": ds_id, "limit": 100}).json()
                if x["table_name"] == table["table_name"]
            ),
            None,
        )
        if table_id is None:
            table_id = c.post("/tables", json={**table, "datasource_id": ds_id}).json()["id"]
        table_ids[table["table_name"]] = table_id
        for name, dtype, sensitive in cols:
            r = c.post(
                f"/tables/{table_id}/columns",
                json={"column_name": name, "data_type": dtype, "is_sensitive": sensitive},
            )
            col_ids[(table["table_name"], name)] = r.json()["id"]
    for down_table, down_col, up_table, up_col in LINEAGE:
        c.post(
            "/lineage",
            json={
                "column_id": col_ids[(down_table, down_col)],
                "upstream_column_id": col_ids[(up_table, up_col)],
            },
        )
    for table_name, col_name, rule_type, threshold, values in RULES:
        r = c.post(
            "/rules",
            json={
                "table_id": table_ids[table_name],
                "column_id": col_ids[(table_name, col_name)],
                "rule_type": rule_type,
                "threshold": threshold,
            },
        )
        c.post(f"/rules/{r.json()['id']}/run", json={"values": values})


def seed_db() -> None:
    from app import models as m

    db = _db()
    try:
        ds_ids, table_ids, col_ids = {}, {}, {}
        for ds, table, cols in PLAN:
            existing = db.query(m.DataSource).filter_by(name=ds["name"]).first()
            if existing:
                ds_obj = existing
            else:
                ds_obj = m.DataSource(**ds)
                db.add(ds_obj)
                db.commit()
                db.refresh(ds_obj)
            ds_ids[ds["name"]] = ds_obj.id

            tm = (
                db.query(m.TableMeta)
                .filter_by(datasource_id=ds_obj.id, table_name=table["table_name"])
                .first()
            )
            if tm:
                table_obj = tm
            else:
                table_obj = m.TableMeta(datasource_id=ds_obj.id, **table)
                db.add(table_obj)
                db.commit()
                db.refresh(table_obj)
            table_ids[table["table_name"]] = table_obj.id

            for name, dtype, sensitive in cols:
                cm = (
                    db.query(m.ColumnMeta)
                    .filter_by(table_id=table_obj.id, column_name=name)
                    .first()
                )
                if not cm:
                    cm = m.ColumnMeta(
                        table_id=table_obj.id,
                        column_name=name,
                        data_type=dtype,
                        is_sensitive=sensitive,
                    )
                    db.add(cm)
                    db.commit()
                    db.refresh(cm)
                col_ids[(table["table_name"], name)] = cm.id

        for down_table, down_col, up_table, up_col in LINEAGE:
            down_id = col_ids[(down_table, down_col)]
            up_id = col_ids[(up_table, up_col)]
            cm = db.query(m.ColumnMeta).filter_by(id=down_id).first()
            cm.upstream_column_id = up_id
            db.commit()

        for table_name, col_name, rule_type, threshold, values in RULES:
            rule = m.QualityRule(
                table_id=table_ids[table_name],
                column_id=col_ids[(table_name, col_name)],
                rule_type=rule_type,
                threshold=threshold,
            )
            db.add(rule)
            db.commit()
            db.refresh(rule)
            result = _evaluate(rule_type, threshold, values)
            db.add(
                m.QualityResult(
                    rule_id=rule.id,
                    passed=result[0],
                    abnormal_count=result[1],
                    detail=result[2],
                )
            )
            db.commit()
    finally:
        db.close()
    time.sleep(0)


def _evaluate(rule_type, threshold, values):
    from app.routers.rules import _to_float

    if rule_type == "not_null":
        bad = sum(1 for v in values if v is None or str(v).strip() == "")
        return bad == 0, bad, f"总数 {len(values)}，空值 {bad}"
    if rule_type == "unique":
        bad = len(values) - len({str(v) for v in values})
        return bad == 0, bad, f"总数 {len(values)}，重复 {bad}"
    upper = threshold if threshold is not None else float("inf")
    bad = sum(1 for v in values if v is not None and (_to_float(v) is None or _to_float(v) > upper))
    return bad == 0, bad, f"总数 {len(values)}，超出上界 {upper} 的有 {bad}"


if __name__ == "__main__":
    main()
