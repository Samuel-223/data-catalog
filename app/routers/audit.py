"""审计查询：只给管理员，按人、按方法、按路径前缀过滤。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.security import require_admin
from ..db import get_db
from ..models import AuditLog
from ..schemas import AuditLogOut

router = APIRouter(prefix="/audit", tags=["审计"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[AuditLogOut], summary="审计记录查询")
def list_audit(
    actor: str | None = None,
    method: str | None = None,
    path_prefix: str | None = None,
    status_code: int | None = None,
    skip: int = 0,
    limit: int = Query(20, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog).order_by(AuditLog.id.desc())
    if actor:
        q = q.filter(AuditLog.actor.like(f"%{actor}%"))
    if method:
        q = q.filter(AuditLog.method == method.upper())
    if path_prefix:
        q = q.filter(AuditLog.path.like(f"{path_prefix}%"))
    if status_code is not None:
        q = q.filter(AuditLog.status_code == status_code)
    return q.offset(skip).limit(limit).all()
