"""健康检查：/health 只看进程，/ready 才看依赖，便于容器编排区分两类故障。"""

from fastapi import APIRouter, Response
from sqlalchemy import text

from ..db import engine

router = APIRouter(tags=["运维"])


@router.get("/health", summary="存活探针")
def health():
    return {"status": "ok"}


@router.get("/ready", summary="就绪探针（含数据库连通性）")
def ready(response: Response):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        response.status_code = 503
        return {"status": "unavailable", "db": "error", "reason": str(exc)[:120]}
    return {"status": "ready", "db": "ok"}
