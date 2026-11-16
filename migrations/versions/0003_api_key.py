"""密钥生命周期：api_key 表只存哈希，支持过期/吊销/轮换

Revision ID: 0003_api_key
Revises: 0002_audit_log
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_api_key"
down_revision: str | None = "0002_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("label", sa.String(80), nullable=False, server_default=""),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(80), nullable=False, server_default=""),
    )
    op.create_index("ix_api_key_key_id", "api_key", ["key_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_key_key_id", table_name="api_key")
    op.drop_table("api_key")
