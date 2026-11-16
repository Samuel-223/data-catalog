"""可观测性：健康检查、请求 ID、统一错误结构。"""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["db"] == "ok"
    assert body["audit"] == "ok"  # 审计目录必须可写，否则视为不就绪


def test_root_service_info(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "data-catalog"
    assert body["docs"] == "/docs"


def test_request_id_is_returned(client):
    r = client.get("/health", headers={"X-Request-ID": "trace-abc"})
    assert r.headers["X-Request-ID"] == "trace-abc"
    assert float(r.headers["X-Process-Time-ms"]) >= 0


def test_request_id_generated_when_absent(client):
    r = client.get("/")
    assert len(r.headers["X-Request-ID"]) == 12


def test_not_found_envelope(client):
    r = client.get("/datasources/999999")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"]
    assert body["detail"] == body["error"]["message"]


def test_validation_envelope(client):
    r = client.post("/datasources", json={"type": "mysql"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    fields = {d["field"] for d in body["error"]["details"]}
    assert "name" in fields


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
