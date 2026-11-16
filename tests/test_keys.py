"""密钥生命周期：签发、使用、轮换宽限、吊销、legacy 兼容。"""

import pytest

from app.core import keyring


@pytest.fixture
def pepper(monkeypatch):
    monkeypatch.setenv("API_KEY_PEPPER", "test-pepper-0123456789")
    monkeypatch.setenv("AUTH_MODE", "apikey")
    # 引导密钥：签发接口本身也要 admin 身份，legacy key 在这里充当引导者
    monkeypatch.setenv(
        "API_KEYS", "admin:sk_admin_000000000000,viewer:sk_viewer_222222222222"
    )
    keyring.pepper()
    yield "test-pepper-0123456789"


def _issue(client, admin_key, role="viewer", days=90, label="t"):
    r = client.post(
        "/keys",
        json={"role": role, "label": label, "days": days},
        headers={"X-API-Key": admin_key},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_issue_returns_plaintext_once_and_list_hides_it(client, pepper):
    admin = "sk_admin_000000000000"
    issued = _issue(client, admin, role="editor", label="CI Jenkins")
    assert issued["key"].startswith("dc_editor_")
    assert len(issued["key"].split("_", 3)[3]) == keyring.SECRET_LEN

    rows = client.get("/keys", headers={"X-API-Key": admin}).json()
    assert rows
    assert "key" not in rows[0]
    assert issued["key"] not in str(rows)


def test_issued_key_authenticates_with_its_role(client, pepper, make_data):
    admin = "sk_admin_000000000000"
    viewer_key = _issue(client, admin, role="viewer")["key"]
    editor_key = _issue(client, admin, role="editor")["key"]

    assert client.get("/datasources", headers={"X-API-Key": viewer_key}).status_code == 200

    r = client.post(
        "/datasources",
        json={"name": "t1", "type": "mysql"},
        headers={"X-API-Key": viewer_key},
    )
    assert r.status_code == 403  # viewer 不能写

    r = client.post(
        "/datasources",
        json={"name": "t2", "type": "mysql"},
        headers={"X-API-Key": editor_key},
    )
    assert r.status_code == 201


def test_expired_key_is_rejected(client, pepper, days=90):
    admin = "sk_admin_000000000000"
    key = _issue(client, admin, role="viewer", days=1)["key"]

    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import ApiKey

    db = SessionLocal()
    try:
        row = db.query(ApiKey).filter(ApiKey.key_id == keyring.parse_key(key)[1]).first()
        row.expires_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    r = client.get("/datasources", headers={"X-API-Key": key})
    assert r.status_code == 401
    assert "过期" in r.json()["error"]["message"]


def test_revoked_key_is_rejected(client, pepper):
    admin = "sk_admin_000000000000"
    issued = _issue(client, admin, role="viewer")
    key_id = issued["key_id"]

    r = client.post(f"/keys/{key_id}/revoke", headers={"X-API-Key": admin})
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"

    r = client.get("/datasources", headers={"X-API-Key": issued["key"]})
    assert r.status_code == 401
    assert "吊销" in r.json()["error"]["message"]


def test_rotate_keeps_old_key_working_during_grace(client, pepper):
    admin = "sk_admin_000000000000"
    issued = _issue(client, admin, role="editor")
    r = client.post(
        f"/keys/{issued['key_id']}/rotate",
        json={"grace_hours": 24, "days": 90},
        headers={"X-API-Key": admin},
    )
    assert r.status_code == 200
    new_key = r.json()["key"]
    assert new_key != issued["key"]

    # 宽限期内旧 key 仍可用（这是轮换不断服的前提）
    assert client.get("/datasources", headers={"X-API-Key": issued["key"]}).status_code == 200
    # 新 key 也已生效
    assert client.get("/datasources", headers={"X-API-Key": new_key}).status_code == 200

    rows = {row["key_id"]: row for row in client.get("/keys", headers={"X-API-Key": admin}).json()}
    assert rows[issued["key_id"]]["status"] == "active"


def test_keys_endpoints_require_admin(client, pepper):
    admin = "sk_admin_000000000000"
    viewer_key = _issue(client, admin, role="viewer")["key"]

    assert client.get("/keys").status_code == 401
    assert client.get("/keys", headers={"X-API-Key": viewer_key}).status_code == 403
    r = client.post(
        "/keys",
        json={"role": "admin", "label": "x", "days": 90},
        headers={"X-API-Key": viewer_key},
    )
    assert r.status_code == 403


def test_keyring_requires_pepper(client, monkeypatch):
    monkeypatch.delenv("API_KEY_PEPPER", raising=False)
    monkeypatch.setenv("AUTH_MODE", "apikey")
    monkeypatch.setenv("API_KEYS", "admin:sk_admin_000000000000")
    r = client.post(
        "/keys",
        json={"role": "viewer", "label": "x", "days": 90},
        headers={"X-API-Key": "sk_admin_000000000000"},
    )
    assert r.status_code == 500
    assert "API_KEY_PEPPER" in r.json()["error"]["message"]


def test_legacy_env_keys_still_work(client, pepper):
    """升级不破坏既有部署：dc_ 之外的密钥继续按环境变量校验。"""
    r = client.get("/datasources", headers={"X-API-Key": "sk_viewer_222222222222"})
    assert r.status_code == 200


def test_unknown_dc_key_rejected_without_leaking_reason(client, pepper):
    r = client.get("/datasources", headers={"X-API-Key": "dc_viewer_deadbeef_" + "0" * 48})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "API Key 无效"


def test_hash_is_not_plaintext_in_db(client, pepper):
    admin = "sk_admin_000000000000"
    issued = _issue(client, admin, role="viewer")
    secret = issued["key"].split("_", 3)[3]

    from app.db import SessionLocal
    from app.models import ApiKey

    db = SessionLocal()
    try:
        row = db.query(ApiKey).filter(ApiKey.key_id == issued["key_id"]).first()
        assert secret not in row.key_hash
        assert len(row.key_hash) == 64  # sha256 hex
    finally:
        db.close()


def test_last_used_is_recorded(client, pepper):
    admin = "sk_admin_000000000000"
    issued = _issue(client, admin, role="viewer")
    client.get("/datasources", headers={"X-API-Key": issued["key"]})

    from app.db import SessionLocal
    from app.models import ApiKey

    db = SessionLocal()
    try:
        row = db.query(ApiKey).filter(ApiKey.key_id == issued["key_id"]).first()
        assert row.last_used_at is not None
    finally:
        db.close()
