"""审计：写操作与鉴权失败落两处——数据库（可查）与 JSONL 文件（可被 Linux 工具处理）。

落盘设计是有意的：
- 数据库表适合按人、按路径做结构化查询（`GET /audit`）；
- JSONL 文件适合 `grep` / `awk` / `jq` / `logrotate` 直接处理，
  不依赖服务存活，也无权限穿越数据库的风险。

写失败不影响主流程（审计不能成为可用性单点），但会打一条 ERROR 日志。
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .logging import request_id_ctx

logger = logging.getLogger("app.audit")


def audit_path() -> Path:
    return Path(os.getenv("AUDIT_LOG_PATH", "audit.jsonl"))


def record(
    *,
    actor: str,
    role: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_ip: str,
    db_factory=None,
) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "request_id": request_id_ctx.get(),
        "actor": actor,
        "role": role,
        "method": method,
        "path": path,
        "status": status_code,
        "duration_ms": duration_ms,
        "client_ip": client_ip,
    }
    _append_jsonl(entry)
    if db_factory is not None:
        _insert_row(entry, db_factory)


def _append_jsonl(entry: dict) -> None:
    path = audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("audit_file_write_failed", extra={"extra_fields": {"err": str(exc)[:80]}})


def _insert_row(entry: dict, db_factory) -> None:
    from ..models import AuditLog

    session = db_factory()
    try:
        session.add(
            AuditLog(
                ts=datetime.fromisoformat(entry["ts"]),
                request_id=entry["request_id"],
                actor=entry["actor"],
                role=entry["role"],
                method=entry["method"],
                path=entry["path"],
                status_code=entry["status"],
                duration_ms=entry["duration_ms"],
                client_ip=entry["client_ip"],
            )
        )
        session.commit()
    except SQLAlchemyError as exc:
        logger.error("audit_db_write_failed", extra={"extra_fields": {"err": str(exc)[:80]}})
        session.rollback()
    finally:
        session.close()


def should_record(method: str, status_code: int) -> bool:
    """写操作全记；读操作只记鉴权失败，避免日志被查询刷满。"""
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    return status_code in {401, 403}
