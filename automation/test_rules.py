import httpx
import os


def test_create_rule(table, rule_factory):
    rule = rule_factory(table["id"], "not_null")
    assert rule["table_id"] == table["id"]
    assert rule["rule_type"] == "not_null"
    assert isinstance(rule["id"], int)


def test_create_rule_missing_table():
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    r = httpx.post(f"{base}/rules", json={"rule_type": "not_null"}, timeout=10)
    assert r.status_code == 422


def test_run_not_null_rule(api, table, make_column, rule_factory):
    col = make_column()
    rule = rule_factory(table["id"], "not_null", column_id=col["id"])

    r = api.post(f"/rules/{rule['id']}/run", {"values": ["a", "b", "c"]})
    assert r.status_code == 200, r.text

    body = r.json()
    if isinstance(body, list):
        body = body[0]
    assert "passed" in body
    assert isinstance(body["passed"], bool)
    assert isinstance(body.get("abnormal_count", 0), int)


def test_unique_rule_detects_duplicate(api, table, make_column, rule_factory):
    """唯一性规则：传入重复值应判定不通过，且异常计数大于 0。"""
    col = make_column()
    rule = rule_factory(table["id"], "unique", column_id=col["id"])

    r = api.post(f"/rules/{rule['id']}/run", {"values": ["dup", "dup", "other"]})
    assert r.status_code == 200, r.text

    body = r.json()
    if isinstance(body, list):
        body = body[0]
    assert body["passed"] is False, f"重复值应判定不通过，实际 {body}"
    assert body["abnormal_count"] >= 1


def test_rule_results_persisted(api, table, make_column, rule_factory):
    col = make_column()
    rule = rule_factory(table["id"], "not_null", column_id=col["id"])
    api.post(f"/rules/{rule['id']}/run", {"values": ["x", "y"]})

    r = api.get(f"/rules/{rule['id']}/results")
    assert r.status_code == 200
    results = r.json()
    assert len(results) >= 1, "执行后应至少留存一条结果"
    assert results[0]["rule_id"] == rule["id"]
    assert results[0]["run_at"], "结果应记录执行时间"


def test_list_rules_contains_new(api, table, rule_factory):
    rule = rule_factory(table["id"], "not_null")
    r = api.get("/rules")
    assert r.status_code == 200
    assert rule["id"] in [x["id"] for x in r.json()]


def test_delete_rule(api, table, rule_factory):
    rule = rule_factory(table["id"], "not_null")
    r = api.delete(f"/rules/{rule['id']}")
    assert r.status_code in (200, 204), f"删除规则应返回 200/204，实际 {r.status_code}"

    again = api.get("/rules")
    assert rule["id"] not in [x["id"] for x in again.json()]
