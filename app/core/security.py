"""API Key 认证与角色授权。

角色矩阵（按 HTTP 方法推导，规则简单到不会被误用）：

| 方法 | 最低角色 | 覆盖的接口 |
|---|---|---|
| GET / HEAD / OPTIONS | viewer | 所有查询 |
| POST / PUT / PATCH | editor | 建数据源、建表字段、建规则、跑校验、登记血缘 |
| DELETE | admin | 删数据源、删表、删规则 |
| GET /audit | admin | 审计查询单独收紧 |

配置：
    AUTH_MODE=apikey                   # off | apikey | oidc | both（未设时按 AUTH_ENABLED 推导）
    API_KEYS=admin:sk_admin_xxx,editor:sk_editor_xxx,viewer:sk_viewer_xxx
    OIDC_ISSUER / OIDC_AUDIENCE        # AUTH_MODE 含 oidc 时必填，详见 core/oidc.py

密钥只从环境变量来，不进代码、不进镜像、不进 compose 文件。
"""

import os
import secrets

from fastapi import HTTPException, Request, status

ROLE_ORDER = {"viewer": 1, "editor": 2, "admin": 3}

# 免鉴权路径：探针与文档之外一律校验
PUBLIC_PATHS = {"/", "/health", "/ready", "/openapi.json"}


def auth_mode() -> str:
    """每请求读取，便于测试与线上快速降级（重启即生效）。

    AUTH_MODE 未显式设置时沿用旧的 AUTH_ENABLED 开关，避免升级时行为突变。
    """
    mode = os.getenv("AUTH_MODE", "").strip().lower()
    if mode in {"off", "apikey", "oidc", "both"}:
        return mode
    return "apikey" if os.getenv("AUTH_ENABLED", "0").strip() == "1" else "off"


def auth_enabled() -> bool:
    return auth_mode() != "off"


def parse_keys(raw: str | None = None) -> dict[str, str]:
    """把 `role:key,role:key` 解析成 {key: role}；格式不对的条目直接丢弃。"""
    raw = os.getenv("API_KEYS", "") if raw is None else raw
    mapping: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        role, key = item.split(":", 1)
        role, key = role.strip().lower(), key.strip()
        if role in ROLE_ORDER and len(key) >= 8:
            mapping[key] = role
    return mapping


def _required_role(method: str) -> str:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "viewer"
    if method == "DELETE":
        return "admin"
    return "editor"


def _digest(key: str) -> str:
    """日志里只落密钥前 6 位指纹，避免把凭据写进审计。"""
    if not key:
        return "-"
    return f"{key[:6]}…{len(key)}"


async def authorize(request: Request) -> str:
    """认证 + 授权，返回角色。挂在路由依赖上，未通过直接 401/403。

    支持两种身份：OIDC Bearer token 与 API Key。`AUTH_MODE=both` 时二者皆可。
    """
    if request.url.path in PUBLIC_PATHS:
        request.state.actor, request.state.role = "anonymous", "admin"
        return "admin"

    mode = auth_mode()
    if mode == "off":
        request.state.actor, request.state.role = "anonymous", "admin"
        return "admin"

    role: str | None = None
    auth_header = request.headers.get("Authorization", "")
    bearer = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""

    if bearer and mode in {"oidc", "both"}:
        from .oidc import local_role, principal_name, verify_token

        payload = verify_token(bearer)
        role, raw_roles = local_role(payload)
        request.state.actor = principal_name(payload)
        request.state.key_fp = "oidc"
        request.state.role = role or "none"
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"token 未包含本服务角色，原角色：{raw_roles or '空'}",
            )
    elif mode in {"apikey", "both"}:
        key = request.headers.get("X-API-Key", "").strip()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 X-API-Key（或改用 Bearer token）",
                headers={"WWW-Authenticate": "Bearer" if mode == "both" else "ApiKey"},
            )
        keys = parse_keys()
        role = keys.get(key)
        request.state.key_fp = _digest(key)
        if role is None:
            request.state.actor = f"key:{_digest(key)}"
            request.state.role = "none"
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 无效或已停用",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        request.state.actor = f"{role}:{_digest(key)}"
    else:
        scheme = "Bearer" if mode == "oidc" else "ApiKey"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"缺少 Bearer token（当前模式 {mode}）" if mode == "oidc" else "缺少 X-API-Key",
            headers={"WWW-Authenticate": scheme},
        )

    needed = _required_role(request.method)
    request.state.role = role
    if ROLE_ORDER[role] < ROLE_ORDER[needed]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前角色 {role} 无权执行 {request.method}，需要 {needed}",
        )
    return role


async def require_admin(request: Request) -> str:
    role = await authorize(request)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该接口仅管理员可访问")
    return role


def generate_key(prefix: str = "sk") -> str:
    """运维生成密钥用：python -m app.core.security admin"""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


if __name__ == "__main__":  # pragma: no cover
    import sys

    role = sys.argv[1] if len(sys.argv) > 1 else "editor"
    print(f"{role}:{generate_key()}")
    print("把这一行加进 API_KEYS，用逗号与其他条目分隔", file=sys.stderr)
