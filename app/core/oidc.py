"""OIDC：校验 Bearer token，并把企业角色映射成本服务的 viewer/editor/admin。

分工上有一条界线很重要：**本服务不做登录**。
登录、单点、MFA 由企业身份源（Keycloak / Azure AD / 统一认证）承担，
本服务只做「验 token + 认角色」，这样 API 不碰用户口令，也不承担会话管理。

配置：
    AUTH_MODE=oidc                       # off | apikey | oidc | both
    OIDC_ISSUER=https://sso.corp.com/realms/data-catalog
    OIDC_AUDIENCE=data-catalog-api
    OIDC_JWKS_URI=                       # 留空则走 .well-known 自动发现
    OIDC_ROLES_CLAIM=realm_access.roles  # 角色所在字段，支持 a.b.c 路径
    OIDC_ROLE_MAP=data-catalog-admin:admin,data-catalog-editor:editor,data-catalog-viewer:viewer
    OIDC_DEV_HS256_SECRET=               # 仅本地/CI 用对称密钥，生产禁止
"""

import hashlib
import os
import time
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, status

from .security import ROLE_ORDER

_jwks_cache: dict[str, Any] = {"uri": None, "keys": None, "fetched_at": 0.0}
JWKS_TTL = 300  # 秒；token 验签用的公钥轮换不会太频繁

# token 级缓存：同一 token 在有效期内不重复验签（RSA 验签是 CPU 热点）
_token_cache: dict[str, tuple[float, dict]] = {}
_token_stats = {"hits": 0, "misses": 0, "evictions": 0}


def token_cache_seconds() -> float:
    try:
        return float(os.getenv("OIDC_TOKEN_CACHE_SECONDS", "60"))
    except ValueError:
        return 60.0


def _config_fingerprint() -> str:
    """配置指纹：密钥/issuer/aud 变了就不该复用旧验签结果。"""
    raw = "|".join(
        [
            os.getenv("OIDC_DEV_HS256_SECRET", ""),
            os.getenv("OIDC_ISSUER", ""),
            os.getenv("OIDC_AUDIENCE", ""),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _cache_key(token: str) -> str:
    return hashlib.sha256(f"{token}|{_config_fingerprint()}".encode()).hexdigest()[:32]


def token_cache_stats() -> dict[str, int]:
    return {**_token_stats, "size": len(_token_cache)}


def clear_caches() -> None:
    """测试与运维用：清空 JWKS 与 token 缓存。"""
    _jwks_cache.update({"uri": None, "keys": None, "fetched_at": 0.0})
    _token_cache.clear()
    _token_stats.update({"hits": 0, "misses": 0, "evictions": 0})


def oidc_enabled() -> bool:
    return os.getenv("AUTH_MODE", "").strip().lower() in {"oidc", "both"}


def roles_claim_path() -> str:
    return os.getenv("OIDC_ROLES_CLAIM", "realm_access.roles")


def role_map() -> dict[str, str]:
    raw = os.getenv(
        "OIDC_ROLE_MAP",
        "data-catalog-admin:admin,data-catalog-editor:editor,data-catalog-viewer:viewer",
    )
    mapping: dict[str, str] = {}
    for item in raw.split(","):
        if ":" not in item:
            continue
        claim_role, local_role = (x.strip() for x in item.split(":", 1))
        if local_role in ROLE_ORDER and claim_role:
            mapping[claim_role] = local_role
    return mapping


def _jwks_uri() -> str:
    explicit = os.getenv("OIDC_JWKS_URI", "").strip()
    if explicit:
        return explicit
    issuer = os.getenv("OIDC_ISSUER", "").rstrip("/")
    if not issuer:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC 未配置 OIDC_ISSUER / OIDC_JWKS_URI",
        )
    discovery = f"{issuer}/.well-known/openid-configuration"
    try:
        resp = httpx.get(discovery, timeout=3.0)
        resp.raise_for_status()
        return resp.json()["jwks_uri"]
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"身份源发现失败：{exc.__class__.__name__}",
        ) from exc


def _jwks(force: bool = False) -> list[dict]:
    uri = _jwks_uri()
    now = time.time()
    if (
        not force
        and _jwks_cache["uri"] == uri
        and _jwks_cache["keys"]
        and now - _jwks_cache["fetched_at"] < JWKS_TTL
    ):
        return _jwks_cache["keys"]
    try:
        resp = httpx.get(uri, timeout=3.0)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"公钥获取失败：{exc.__class__.__name__}",
        ) from exc
    _jwks_cache.update({"uri": uri, "keys": keys, "fetched_at": now})
    return keys


def _public_key(token: str, alg: str, kid: str | None):
    if alg == "HS256":
        secret = os.getenv("OIDC_DEV_HS256_SECRET", "")
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="收到 HS256 token，但未配置 OIDC_DEV_HS256_SECRET（生产应为 RS256）",
            )
        return secret
    keys = _jwks()
    candidates = [k for k in keys if k.get("kid") == kid]
    if not candidates and kid:
        # kid 未命中通常是身份源轮换了密钥：强制刷新一次再匹配，不直接拒绝
        keys = _jwks(force=True)
        candidates = [k for k in keys if k.get("kid") == kid]
    if not candidates:
        candidates = keys
    if not candidates:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="身份源未返回可用公钥")
    try:
        return jwt.algorithms.RSAAlgorithm.from_jwk(candidates[0])
    except (jwt.PyJWKError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="公钥解析失败"
        ) from exc


def verify_token(token: str) -> dict:
    """验签 + 校验 iss/aud/exp，失败一律 401 并说明原因。

    命中缓存时跳过验签（同一 token 默认 60 秒内不重复算），
    缓存上界取 token 自己的 exp，避免缓存比 token 活得久。
    """
    key = _cache_key(token)
    now = time.time()
    hit = _token_cache.get(key)
    if hit and hit[0] > now:
        _token_stats["hits"] += 1
        return hit[1]

    payload = _verify_uncached(token)
    exp = payload.get("exp")
    ttl_end = now + token_cache_seconds()
    if isinstance(exp, (int, float)):
        ttl_end = min(ttl_end, float(exp))
    if ttl_end > now:
        _token_cache[key] = (ttl_end, payload)
    _token_stats["misses"] += 1
    return payload


def _verify_uncached(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 格式错误"
        ) from exc
    alg = header.get("alg", "")
    if alg not in {"RS256", "RS384", "RS512", "HS256"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"不支持的签名算法 {alg}"
        )

    issuer = os.getenv("OIDC_ISSUER", "").strip()
    audience = os.getenv("OIDC_AUDIENCE", "").strip()
    try:
        return jwt.decode(
            token,
            _public_key(token, alg, header.get("kid")),
            algorithms=[alg],
            audience=audience or None,
            issuer=issuer or None,
            options={"require": ["exp", "iat"], "verify_aud": bool(audience)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 已过期"
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 不属于本服务"
        ) from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 签发方不匹配"
        ) from exc
    except jwt.InvalidSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="签名校验失败"
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"token 校验失败：{exc.__class__.__name__}",
        ) from exc


def claimed_roles(payload: dict) -> list[str]:
    node: Any = payload
    for part in roles_claim_path().split("."):
        if not isinstance(node, dict) or part not in node:
            return []
        node = node[part]
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [str(x) for x in node]
    return []


def local_role(payload: dict) -> tuple[str | None, list[str]]:
    """返回 (本服务角色, 原始角色列表)。没有任何匹配角色时角色为 None。"""
    raw = claimed_roles(payload)
    mapping = role_map()
    matched = [mapping[r] for r in raw if r in mapping]
    if not matched:
        return None, raw
    best = max(matched, key=lambda r: ROLE_ORDER[r])
    return best, raw


def principal_name(payload: dict) -> str:
    for field in ("email", "preferred_username", "sub"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return "oidc:unknown"
