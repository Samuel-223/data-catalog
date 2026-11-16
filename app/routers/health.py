"""健康检查：/health 只看进程，/ready 才看依赖，便于容器编排区分两类故障。

- `/health`：存活，只回 {"status":"ok"}，不带版本号与服务名，少给扫描器信息
- `/ready`：就绪，检查数据库连通 + 审计目录可写（审计写不进去等于丢证据）
- `/health/detail`：admin 专用，查版本、认证模式、审计路径、JWKS 可达性
"""

import logging
import os

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from ..core.audit import audit_path
from ..core.security import auth_mode, require_admin
from ..db import engine

logger = logging.getLogger("app.health")

router = APIRouter(tags=["运维"])


def docs_enabled() -> bool:
    """文档开关：生产建议 DOCS_ENABLED=0，接口结构不对外暴露。"""
    return os.getenv("DOCS_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}


def _db_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("ready_db_check_failed", extra={"extra_fields": {"err": str(exc)[:80]}})
        return False


def _audit_writable() -> bool:
    """审计目录必须可写：写不进去说明这台机器会静默丢审计。"""
    try:
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".audit_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@router.get("/health", summary="存活探针")
def health():
    return {"status": "ok"}


@router.get("/ready", summary="就绪探针（数据库 + 审计目录）")
def ready(response: Response):
    db_ok = _db_ok()
    audit_ok = _audit_writable()
    if db_ok and audit_ok:
        return {"status": "ready", "db": "ok", "audit": "ok"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "unavailable",
        "db": "ok" if db_ok else "error",
        "audit": "ok" if audit_ok else "readonly",
    }


@router.get(
    "/health/detail",
    summary="详细健康信息（仅 admin）",
    dependencies=[Depends(require_admin)],
)
def health_detail():
    from ..core.config import settings
    from ..core.oidc import _jwks, oidc_enabled

    detail = {
        "version": settings.version,
        "auth_mode": auth_mode(),
        "oidc_enabled": oidc_enabled(),
        "db": "ok" if _db_ok() else "error",
        "audit_path": str(audit_path()),
        "audit_writable": _audit_writable(),
        "docs_enabled": docs_enabled(),
    }
    if oidc_enabled():
        try:
            detail["jwks_keys"] = len(_jwks())
        except Exception:  # noqa: BLE001 — 身份源不可达不影响详情接口本身
            detail["jwks_keys"] = "unreachable"
    return detail
