from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class DataSourceBase(BaseModel):
    name: str = Field(..., max_length=100)
    type: str = Field(..., max_length=50)
    host: str | None = None
    owner: str | None = None
    description: str | None = None


class DataSourceCreate(DataSourceBase):
    pass


class DataSourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    host: str | None = None
    owner: str | None = None
    description: str | None = None


class DataSourceOut(DataSourceBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TableMetaBase(BaseModel):
    table_name: str = Field(..., max_length=200)
    layer: str | None = None
    description: str | None = None
    owner: str | None = None


class TableMetaCreate(TableMetaBase):
    datasource_id: int


class TableMetaUpdate(BaseModel):
    table_name: str | None = None
    layer: str | None = None
    description: str | None = None
    owner: str | None = None


class TableMetaOut(TableMetaBase):
    id: int
    datasource_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ColumnMetaBase(BaseModel):
    column_name: str = Field(..., max_length=200)
    data_type: str | None = None
    is_sensitive: bool = False
    description: str | None = None
    upstream_column_id: int | None = None


class ColumnMetaCreate(ColumnMetaBase):
    pass


class ColumnMetaOut(ColumnMetaBase):
    id: int
    table_id: int
    model_config = ConfigDict(from_attributes=True)

class QualityRuleBase(BaseModel):
    table_id: int
    column_id: int | None = None
    rule_type: str
    threshold: float | None = None
    enabled: bool = True

class QualityRuleCreate(QualityRuleBase):
    pass

class QualityRuleOut(QualityRuleBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class QualityResultOut(BaseModel):
    id: int
    rule_id: int
    run_at: datetime
    passed: bool
    abnormal_count: int
    detail: str | None = None
    model_config = ConfigDict(from_attributes=True)

class RunPayload(BaseModel):
    values: list[str | None] | None = None

class LineageCreate(BaseModel):
    column_id: int
    upstream_column_id: int
