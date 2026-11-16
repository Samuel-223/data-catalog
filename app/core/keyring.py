"""密钥生命周期：签发 / 校验 / 轮换 / 吊销。

格式：`dc_{role}_{key_id}_{secret}`
    dc_admin_7f3a91c2_9b1c...（role 明文可见、key_id 8 位十六进制、secret 48 位十六进制）

三条不可让步的规则：
1. 明文只在签发响应里出现一次，入库的是 HMAC-SHA256(secret, API_KEY_PEPPER)；
2. 校验用 hmac.compare_digest 恒时比较，避免计时攻击逐字节试探；
3. 审计与日志只写 key_id 与前 6 位指纹，永不写明文。

为什么用 HMAC 而不是 bcrypt/argon2：密钥本身有 192 bit 熵，不存在弱口令爆破问题，
而 argon2 单次 50ms 会成为高频接口的瓶颈。pepper 与数据库分开存放（环境变量），
拖库者拿不到 pepper 就无法还原哈希。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

PREFIX = "dc"
KEY_ID_LEN = 8
SECRET_LEN = 48
LAST_USED_THROTTLE_SECONDS = 60


def pepper() -> str:
    return os.getenv("API_KEY_PEPPER", "")


def keyring_enabled() -> bool:
    """没配 pepper 就不启用数据库密钥，只有环境变量里的 legacy key 可用。"""
    return bool(pepper())


def hash_secret(secret: str) -> str:
    return hmac.new(pepper().encode(), secret.encode(), hashlib.sha256).hexdigest()


def parse_key(key: str) -> tuple[str, str, str] | None:
    """拆出 (role, key_id, secret)；格式不对返回 None。"""
    parts = key.split("_", 3)
    if len(parts) != 4 or parts[0] != PREFIX:
        return None
    _, role, key_id, secret = parts
    if role not in {"viewer", "editor", "admin"}:
        return None
    if len(key_id) != KEY_ID_LEN or len(secret) != SECRET_LEN:
        return None
    return role, key_id, secret


def fingerprint(key: str) -> str:
    """日志/审计用的短指纹：dc_admin_7f3a…共 63 位。"""
    if not key:
        return "-"
    return f"{key[:12]}…{len(key)}"


def new_key(role: str) -> tuple[str, str]:
    """返回 (明文, key_id)。明文只在此刻存在内存里，之后必须靠调用方交付。"""
    key_id = secrets.token_hex(KEY_ID_LEN // 2)
    secret = secrets.token_hex(SECRET_LEN // 2)
    return f"{PREFIX}_{role}_{key_id}_{secret}", key_id


def create_key(
    db: Session,
    *,
    role: str,
    label: str = "",
    days: int = 90,
    created_by: str = "",
) -> tuple[str, object]:
    from ..models import ApiKey

    plaintext, key_id = new_key(role)
    row = ApiKey(
        key_id=key_id,
        role=role,
        label=label[:80],
        key_hash=hash_secret(plaintext.split("_", 3)[3]),
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(days=days) if days > 0 else None,
        created_by=created_by[:80],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return plaintext, row


def status_of(row, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= now:
        return "expired"
    return "active"


def revoke_key(db: Session, key_id: str) -> bool:
    from ..models import ApiKey

    row = db.query(ApiKey).filter(ApiKey.key_id == key_id).first()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now()
    db.commit()
    return True


def rotate_key(
    db: Session,
    key_id: str,
    *,
    grace_hours: int = 24,
    days: int = 90,
    created_by: str = "",
) -> tuple[str, object | None, object | None]:
    """签发新密钥，旧密钥在宽限期后失效（宽限期是轮换不断服的关键）。"""
    from ..models import ApiKey

    old = db.query(ApiKey).filter(ApiKey.key_id == key_id).first()
    if old is None or old.revoked_at is not None:
        return "", None, old

    grace_end = datetime.now() + timedelta(hours=grace_hours)
    if old.expires_at is None or old.expires_at > grace_end:
        old.expires_at = grace_end

    plaintext, new_row = create_key(
        db, role=old.role, label=old.label, days=days, created_by=created_by
    )
    return plaintext, new_row, old


def touch_last_used(db: Session, row) -> None:
    """每 60 秒最多写一次，避免高频请求把数据库写成瓶颈。"""
    now = datetime.now()
    if row.last_used_at is not None and (now - row.last_used_at).total_seconds() < (
        LAST_USED_THROTTLE_SECONDS
    ):
        return
    try:
        row.last_used_at = now
        db.commit()
    except Exception:  # noqa: BLE001 — 记录使用时间失败不该阻断请求
        db.rollback()


def authenticate(key: str, db: Session) -> tuple[str, str]:
    """校验数据库密钥，返回 (role, key_id)；失败抛 ValueError 带原因。"""
    parsed = parse_key(key)
    if parsed is None:
        raise ValueError("invalid")
    _, key_id, secret = parsed

    from ..models import ApiKey

    row = db.query(ApiKey).filter(ApiKey.key_id == key_id).first()
    if row is None:
        raise ValueError("invalid")

    state = status_of(row)
    if state == "revoked":
        raise ValueError("revoked")
    if state == "expired":
        raise ValueError("expired")

    if not hmac.compare_digest(row.key_hash, hash_secret(secret)):
        raise ValueError("invalid")

    touch_last_used(db, row)
    return row.role, row.key_id


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — CLI 入口
    """python -m app.core.keyring create --role editor --label ci --days 90"""
    import argparse
    import sys

    from ..db import Base, SessionLocal, engine
    from ..models import ApiKey

    parser = argparse.ArgumentParser(description="data-catalog 密钥管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("--role", required=True, choices=["viewer", "editor", "admin"])
    p_create.add_argument("--label", default="")
    p_create.add_argument("--days", type=int, default=90)

    sub.add_parser("list")

    p_revoke = sub.add_parser("revoke")
    p_revoke.add_argument("key_id")

    p_rotate = sub.add_parser("rotate")
    p_rotate.add_argument("key_id")
    p_rotate.add_argument("--grace-hours", type=int, default=24)
    p_rotate.add_argument("--days", type=int, default=90)

    args = parser.parse_args(argv)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if not keyring_enabled():
        print("未设置 API_KEY_PEPPER，数据库密钥不可用", file=sys.stderr)
        return 2

    if args.cmd == "create":
        plaintext, row = create_key(
            db, role=args.role, label=args.label, days=args.days, created_by="cli"
        )
        print(plaintext)
        print(f"# key_id={row.key_id} expires_at={row.expires_at}", file=sys.stderr)
        return 0

    if args.cmd == "list":
        for row in db.query(ApiKey).order_by(ApiKey.id.desc()).all():
            print(
                f"{row.key_id}\t{row.role}\t{status_of(row)}\t"
                f"label={row.label}\texpires={row.expires_at}\tlast_used={row.last_used_at}"
            )
        return 0

    if args.cmd == "revoke":
        ok = revoke_key(db, args.key_id)
        print("已吊销" if ok else "未找到或已吊销")
        return 0 if ok else 1

    if args.cmd == "rotate":
        plaintext, new_row, old = rotate_key(
            db, args.key_id, grace_hours=args.grace_hours, days=args.days, created_by="cli"
        )
        if not plaintext:
            print("未找到或已吊销")
            return 1
        print(plaintext)
        print(
            f"# 新 key_id={new_row.key_id}；旧 key {old.key_id} 于 {old.expires_at} 失效",
            file=sys.stderr,
        )
        return 0

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
