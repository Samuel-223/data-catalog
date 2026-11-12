from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class DataSource(Base):
    __tablename__ = "datasource"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(50))
    host: Mapped[str | None] = mapped_column(String(200))
    owner: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    tables: Mapped[list["TableMeta"]] = relationship(
        back_populates="datasource", cascade="all, delete-orphan"
    )


class TableMeta(Base):
    __tablename__ = "table_meta"

    id: Mapped[int] = mapped_column(primary_key=True)
    datasource_id: Mapped[int] = mapped_column(
        ForeignKey("datasource.id", ondelete="CASCADE"), index=True
    )
    table_name: Mapped[str] = mapped_column(String(200), index=True)
    layer: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    datasource: Mapped["DataSource"] = relationship(back_populates="tables")
    columns: Mapped[list["ColumnMeta"]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )


class ColumnMeta(Base):
    __tablename__ = "column_meta"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(
        ForeignKey("table_meta.id", ondelete="CASCADE"), index=True
    )
    column_name: Mapped[str] = mapped_column(String(200))
    data_type: Mapped[str | None] = mapped_column(String(50))
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    # 血缘：本字段来源于哪个上游字段（指向同一张表的另一条记录）
    upstream_column_id: Mapped[int | None] = mapped_column(
        ForeignKey("column_meta.id"), nullable=True
    )

    table: Mapped["TableMeta"] = relationship(back_populates="columns")


class QualityRule(Base):
    __tablename__ = "quality_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(
        ForeignKey("table_meta.id", ondelete="CASCADE"), index=True
    )
    column_id: Mapped[int | None] = mapped_column(
        ForeignKey("column_meta.id", ondelete="CASCADE"), nullable=True
    )
    rule_type: Mapped[str] = mapped_column(String(50))   # not_null / unique / range
    threshold: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class QualityResult(Base):
    __tablename__ = "quality_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("quality_rule.id", ondelete="CASCADE"), index=True
    )
    run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    passed: Mapped[bool] = mapped_column(Boolean)
    abnormal_count: Mapped[int] = mapped_column(default=0)
    detail: Mapped[str | None] = mapped_column(Text)
