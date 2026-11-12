def test_create_not_null_rule(client, make_data):
    _, table_id, col_id = make_data()

    r = client.post(
        "/rules",
        json={"table_id": table_id, "column_id": col_id, "rule_type": "not_null"},
    )
    assert r.status_code in (200, 201)
    assert r.json()["rule_type"] == "not_null"

def test_run_not_null_rule_not_passed(client, make_data):
    _, table_id, col_id = make_data()
    r = client.post(
        "/rules",
        json={"table_id": table_id, "column_id": col_id, "rule_type": "not_null"},
    )
    rule_id = r.json()["id"]

    r = client.post(
        f"/rules/{rule_id}/run",
        json={"values": ["13800138000", "13900139000", None, "", "13700137000", "13600136000"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is False
    assert body["abnormal_count"] == 2

def test_run_not_null_rule_passed(client, make_data):
    _, table_id, col_id = make_data()
    r = client.post("/rules", json={"table_id": table_id, "rule_type": "not_null"})
    rule_id = r.json()["id"]

    r = client.post(f"/rules/{rule_id}/run", json={"values": ["a", "b", "c"]})
    body = r.json()
    assert body["passed"] is True
    assert body["abnormal_count"] == 0

def test_run_unique_rule(client, make_data):
    _, table_id, _ = make_data()
    r = client.post("/rules", json={"table_id": table_id, "rule_type": "unique"})
    rule_id = r.json()["id"]

    r = client.post(f"/rules/{rule_id}/run", json={"values": ["a", "b", "a", "c", "b"]})
    body = r.json()
    assert body["passed"] is False
    assert body["abnormal_count"] == 2

def test_run_range_rule(client, make_data):
    _, table_id, _ = make_data()
    r = client.post(
        "/rules",
        json={"table_id": table_id, "rule_type": "range", "threshold": 100},
    )
    rule_id = r.json()["id"]

    r = client.post(f"/rules/{rule_id}/run", json={"values": ["10", "20", "200", "50", "300"]})
    body = r.json()
    assert body["passed"] is False
    assert body["abnormal_count"] == 2

def test_invalid_rule_type(client, make_data):
    _, table_id, _ = make_data()
    r = client.post("/rules", json={"table_id": table_id, "rule_type": "unknown"})
    assert r.status_code == 400

def test_rule_results_history(client, make_data):
    _, table_id, _ = make_data()
    r = client.post("/rules", json={"table_id": table_id, "rule_type": "not_null"})
    rule_id = r.json()["id"]

    client.post(f"/rules/{rule_id}/run", json={"values": ["a", None]})
    client.post(f"/rules/{rule_id}/run", json={"values": ["a", "b"]})

    r = client.get(f"/rules/{rule_id}/results")
    assert r.status_code == 200
    assert len(r.json()) == 2

def test_delete_rule(client, make_data):
    _, table_id, _ = make_data()
    r = client.post("/rules", json={"table_id": table_id, "rule_type": "not_null"})
    rule_id = r.json()["id"]

    r = client.delete(f"/rules/{rule_id}")
    assert r.status_code in (200, 204)

def test_run_missing_rule(client):
    r = client.post("/rules/9999/run", json={"values": ["a"]})
    assert r.status_code == 404
