"""OIDC token 校验与角色映射。"""

import time

import jwt
import pytest

ISSUER = "https://sso.test/realms/data-catalog"
AUDIENCE = "data-catalog-api"


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("OIDC_DEV_HS256_SECRET", "dev-secret-for-tests-0123456789abcdef0123")


def make_token(
    roles=("data-catalog-editor",),
    *,
    audience=AUDIENCE,
    issuer=ISSUER,
    ttl=300,
    email="zhang@corp.com",
):
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": "u-1001",
        "email": email,
        "preferred_username": "zhang",
        "iat": now,
        "exp": now + ttl,
        "realm_access": {"roles": list(roles)},
    }
    return jwt.encode(payload, "dev-secret-for-tests-0123456789abcdef0123", algorithm="HS256")


def test_admin_token_can_write_and_delete(client, oidc_on):
    token = make_token(["data-catalog-admin"])
    created = client.post(
        "/datasources",
        json={"name": "ds_oidc", "type": "mysql"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201
    r = client.delete(
        f"/datasources/{created.json()['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 204


def test_viewer_token_cannot_write(client, oidc_on):
    token = make_token(["data-catalog-viewer"])
    assert (
        client.get("/datasources", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    )
    r = client.post(
        "/datasources",
        json={"name": "ds_viewer", "type": "mysql"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_expired_token_rejected(client, oidc_on):
    token = make_token(ttl=-60)
    r = client.get("/datasources", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "过期" in r.json()["error"]["message"]


def test_wrong_audience_rejected(client, oidc_on):
    token = make_token(audience="other-api")
    r = client.get("/datasources", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "不属于本服务" in r.json()["error"]["message"]


def test_wrong_issuer_rejected(client, oidc_on):
    token = make_token(issuer="https://evil.example/realms/x")
    r = client.get("/datasources", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_without_mapped_role_forbidden(client, oidc_on):
    token = make_token(["some-other-app-role"])
    r = client.get("/datasources", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert "未包含本服务角色" in r.json()["error"]["message"]


def test_whoami_returns_identity(client, oidc_on):
    token = make_token(["data-catalog-admin"], email="li@corp.com")
    r = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["actor"] == "li@corp.com"
    assert body["role"] == "admin"
    assert body["mode"] == "oidc"
    assert body["scheme"] == "bearer"


def test_both_mode_accepts_api_key_and_bearer(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "both")
    monkeypatch.setenv("API_KEYS", "admin:sk_admin_000000000000")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("OIDC_DEV_HS256_SECRET", "dev-secret-for-tests-0123456789abcdef0123")
    assert (
        client.get("/datasources", headers={"X-API-Key": "sk_admin_000000000000"}).status_code
        == 200
    )
    token = make_token(["data-catalog-admin"])
    assert (
        client.get("/datasources", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    )


def test_hs256_without_secret_rejected(client, oidc_on, monkeypatch):
    monkeypatch.delenv("OIDC_DEV_HS256_SECRET")
    token = make_token(["data-catalog-admin"])
    r = client.get("/datasources", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "HS256" in r.json()["error"]["message"]
