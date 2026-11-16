"""/health/detail、/ready 的审计目录检查、文档开关、JWT 验签缓存。"""

import time


def test_ready_reports_audit_readonly(client, monkeypatch, tmp_path):
    """审计目录不可写时必须判不就绪——写不进去等于静默丢审计。"""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(blocker / "audit.jsonl"))
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["audit"] == "readonly"


def test_health_detail_requires_admin(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "apikey")
    monkeypatch.setenv("API_KEYS", "admin:sk_admin_000000000000,viewer:sk_viewer_222222222222")

    assert client.get("/health/detail").status_code == 401
    r = client.get("/health/detail", headers={"X-API-Key": "sk_viewer_222222222222"})
    assert r.status_code == 403

    r = client.get("/health/detail", headers={"X-API-Key": "sk_admin_000000000000"})
    assert r.status_code == 200
    body = r.json()
    assert body["version"]
    assert body["audit_writable"] is True
    assert body["db"] == "ok"


def test_docs_disabled_returns_404(client, monkeypatch):
    monkeypatch.setenv("DOCS_ENABLED", "0")
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_enabled_by_default(client, monkeypatch):
    monkeypatch.delenv("DOCS_ENABLED", raising=False)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_root_does_not_leak_endpoint_list(client):
    body = client.get("/").json()
    assert set(body) == {"status", "service", "docs", "health", "ready"}


def test_token_verification_is_cached(monkeypatch):
    import app.core.oidc as oidc

    oidc.clear_caches()
    calls = {"n": 0}

    def fake_verify(token):
        calls["n"] += 1
        return {"sub": "u1", "exp": time.time() + 300}

    monkeypatch.setenv("OIDC_DEV_HS256_SECRET", "dev")
    monkeypatch.setattr(oidc, "_verify_uncached", fake_verify)

    oidc.verify_token("token-abc")
    oidc.verify_token("token-abc")
    assert calls["n"] == 1, "同一 token 第二次应命中缓存"
    assert oidc.token_cache_stats()["hits"] == 1


def test_expired_token_not_cached(monkeypatch):
    import app.core.oidc as oidc

    oidc.clear_caches()
    calls = {"n": 0}

    def fake_verify(token):
        calls["n"] += 1
        return {"sub": "u1", "exp": time.time() - 1}

    monkeypatch.setenv("OIDC_DEV_HS256_SECRET", "dev")
    monkeypatch.setattr(oidc, "_verify_uncached", fake_verify)

    oidc.verify_token("expired")
    oidc.verify_token("expired")
    assert calls["n"] == 2, "过期 token 不应进入缓存"


def test_jwks_force_refresh_bypasses_cache(monkeypatch):
    import app.core.oidc as oidc

    oidc.clear_caches()
    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            calls["n"] += 1
            return {"keys": [{"kid": f"k{calls['n']}", "kty": "RSA", "n": "x", "e": "AQAB"}]}

    monkeypatch.setenv("OIDC_JWKS_URI", "https://sso.test/certs")
    monkeypatch.setattr(oidc.httpx, "get", lambda *a, **k: FakeResp())

    oidc._jwks()
    oidc._jwks()
    assert calls["n"] == 1, "TTL 内应复用缓存"

    oidc._jwks(force=True)
    assert calls["n"] == 2, "force=True 必须绕过缓存（密钥轮换用）"
