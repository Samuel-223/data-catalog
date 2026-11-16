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
    # 值集允许字符串与数值混用，执行侧统一按字符串/浮点处理
    values: list[str | int | float | None] | None = None


class LineageCreate(BaseModel):
    column_id: int
    upstream_column_id: int


class AuditLogOut(BaseModel):
    id: int
    ts: datetime
    request_id: str
    actor: str
    role: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    client_ip: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreate(BaseModel):
    role: str = Field(..., pattern="^(viewer|editor|admin)$")
    label: str = Field("", max_length=80)
    days: int = Field(90, ge=1, le=3650)


class ApiKeyCreated(BaseModel):
    key: str
    key_id: str
    role: str
    label: str
    expires_at: datetime | None


class ApiKeyOut(BaseModel):
    key_id: str
    role: str
    label: str
    status: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_by: str

    model_config = ConfigDict(from_attributes=True)


class ApiKeyRotate(BaseModel):
    grace_hours: int = Field(24, ge=1, le=720)
    days: int = Field(90, ge=1, le=3650)
