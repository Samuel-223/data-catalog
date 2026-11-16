"""权限矩阵与审计链路。"""

import pytest

KEYS = "admin:sk_admin_000000000000,editor:sk_editor_11111111111,viewer:sk_viewer_222222222222"


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("API_KEYS", KEYS)
    return {
        "admin": {"X-API-Key": "sk_admin_000000000000"},
        "editor": {"X-API-Key": "sk_editor_11111111111"},
        "viewer": {"X-API-Key": "sk_viewer_222222222222"},
    }


def _ds(name="ds_auth"):
    return {"name": name, "type": "mysql"}


def test_missing_key_401(client, auth_on):
    r = client.get("/datasources")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert r.headers.get("WWW-Authenticate") == "ApiKey"


def test_invalid_key_401(client, auth_on):
    r = client.get("/datasources", headers={"X-API-Key": "sk_not_exist_999999"})
    assert r.status_code == 401


def test_viewer_reads_but_cannot_write(client, auth_on):
    assert client.get("/datasources", headers=auth_on["viewer"]).status_code == 200
    r = client.post("/datasources", json=_ds(), headers=auth_on["viewer"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_editor_writes_but_cannot_delete(client, auth_on):
    created = client.post("/datasources", json=_ds("ds_editor"), headers=auth_on["editor"])
    assert created.status_code == 201
    ds_id = created.json()["id"]
    r = client.delete(f"/datasources/{ds_id}", headers=auth_on["editor"])
    assert r.status_code == 403


def test_admin_can_delete(client, auth_on):
    created = client.post("/datasources", json=_ds("ds_admin"), headers=auth_on["admin"])
    ds_id = created.json()["id"]
    assert client.delete(f"/datasources/{ds_id}", headers=auth_on["admin"]).status_code == 204


def test_audit_records_write_operation(client, auth_on):
    client.post("/datasources", json=_ds("ds_audit"), headers=auth_on["editor"])
    rows = client.get(
        "/audit", params={"path_prefix": "/datasources"}, headers=auth_on["admin"]
    ).json()
    assert rows, "写操作应留审计记录"
    row = rows[0]
    assert row["method"] == "POST"
    assert row["status_code"] == 201
    assert row["actor"].startswith("editor:")
    # 审计里不能出现完整密钥
    assert "sk_editor" not in str(row)


def test_audit_query_requires_admin(client, auth_on):
    assert client.get("/audit", headers=auth_on["viewer"]).status_code == 403
    assert client.get("/audit", headers=auth_on["admin"]).status_code == 200


def test_failed_auth_is_recorded(client, auth_on):
    client.get("/datasources")  # 无密钥
    rows = client.get("/audit", params={"status_code": 401}, headers=auth_on["admin"]).json()
    assert any(r["status_code"] == 401 for r in rows)
