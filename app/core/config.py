"""集中配置：全部通过环境变量注入，代码里不硬编码连接串。"""

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "数据资产目录与质量校验服务"
    version: str = "0.6.7"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_json: bool = _flag("LOG_JSON", True)
    # 开发/测试环境自动建表；生产用 Alembic 迁移时置 0
    auto_create_schema: bool = _flag("AUTO_CREATE_SCHEMA", True)
    cors_origins: tuple[str, ...] = tuple(
        origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()
    )


settings = Settings()
