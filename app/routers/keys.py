"""密钥管理：签发 / 列表 / 轮换 / 吊销。全部仅 admin。

设计底线：
- 签发响应里明文只出现这一次，列表永远不回明文；
- 轮换是“新旧并存 + 宽限期”，避免替换瞬间全量 401；
- 吊销立即写入 revoked_at，配合 60 秒判定缓存，最坏 60 秒后彻底失效（文档已写明）。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core import keyring
from ..core.security import require_admin
from ..db import get_db
from ..models import ApiKey
from ..schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, ApiKeyRotate

router = APIRouter(prefix="/keys", tags=["密钥"], dependencies=[Depends(require_admin)])


def _to_out(row) -> ApiKeyOut:
    """status 是计算字段（未落库），所以手工组装而不是 model_validate。"""
    return ApiKeyOut(
        key_id=row.key_id,
        role=row.role,
        label=row.label,
        status=keyring.status_of(row),
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_by=row.created_by,
    )


def _created(plaintext: str, row) -> ApiKeyCreated:
    return ApiKeyCreated(
        key=plaintext,
        key_id=row.key_id,
        role=row.role,
        label=row.label,
        expires_at=row.expires_at,
    )


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED, summary="签发密钥")
def create(payload: ApiKeyCreate, request: Request, db: Session = Depends(get_db)):
    if not keyring.keyring_enabled():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="未配置 API_KEY_PEPPER，密钥托管未启用",
        )
    plaintext, row = keyring.create_key(
        db,
        role=payload.role,
        label=payload.label,
        days=payload.days,
        created_by=str(getattr(request.state, "actor", "admin")),
    )
    return _created(plaintext, row)


@router.get("", response_model=list[ApiKeyOut], summary="密钥列表（不含明文）")
def list_keys(
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    rows = db.query(ApiKey).order_by(ApiKey.id.desc()).offset(skip).limit(limit).all()
    out = []
    for row in rows:
        item = _to_out(row)
        if status_filter and item.status != status_filter:
            continue
        out.append(item)
    return out


@router.post("/{key_id}/rotate", response_model=ApiKeyCreated, summary="轮换密钥")
def rotate(
    key_id: str,
    payload: ApiKeyRotate,
    request: Request,
    db: Session = Depends(get_db),
):
    plaintext, new_row, old = keyring.rotate_key(
        db,
        key_id,
        grace_hours=payload.grace_hours,
        days=payload.days,
        created_by=str(getattr(request.state, "actor", "admin")),
    )
    if not plaintext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="密钥不存在或已吊销",
        )
    return _created(plaintext, new_row)


@router.post("/{key_id}/revoke", response_model=ApiKeyOut, summary="吊销密钥")
def revoke(key_id: str, db: Session = Depends(get_db)):
    ok = keyring.revoke_key(db, key_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="密钥不存在或已吊销")
    row = db.query(ApiKey).filter(ApiKey.key_id == key_id).first()
    return _to_out(row)
