"""初始表结构：数据源 / 表 / 字段 / 质量规则 / 校验结果

Revision ID: 0001_init
Revises:
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasource",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("host", sa.String(200), nullable=True),
        sa.Column("owner", sa.String(50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_datasource_name", "datasource", ["name"], unique=True)

    op.create_table(
        "table_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "datasource_id",
            sa.Integer(),
            sa.ForeignKey("datasource.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_name", sa.String(200), nullable=False),
        sa.Column("layer", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_table_meta_datasource_id", "table_meta", ["datasource_id"])
    op.create_index("ix_table_meta_table_name", "table_meta", ["table_name"])

    op.create_table(
        "column_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "table_id",
            sa.Integer(),
            sa.ForeignKey("table_meta.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_name", sa.String(200), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=True),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "upstream_column_id",
            sa.Integer(),
            sa.ForeignKey("column_meta.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_column_meta_table_id", "column_meta", ["table_id"])

    op.create_table(
        "quality_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "table_id",
            sa.Integer(),
            sa.ForeignKey("table_meta.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "column_id",
            sa.Integer(),
            sa.ForeignKey("column_meta.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_quality_rule_table_id", "quality_rule", ["table_id"])
    op.create_index("ix_quality_rule_column_id", "quality_rule", ["column_id"])

    op.create_table(
        "quality_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("quality_rule.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("abnormal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_quality_result_rule_id", "quality_result", ["rule_id"])


def downgrade() -> None:
    op.drop_table("quality_result")
    op.drop_table("quality_rule")
    op.drop_table("column_meta")
    op.drop_table("table_meta")
    op.drop_table("datasource")
