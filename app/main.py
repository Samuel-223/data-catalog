from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.errors import register_error_handlers
from .core.logging import setup_logging
from .core.middleware import RequestContextMiddleware
from .core.security import authorize
from .db import Base, engine
from .routers import audit, authinfo, datasources, health, keys, lineage, rules, tables

setup_logging(settings.log_level, settings.log_json)

DESCRIPTION = """
数据治理场景的后端服务，三块能力：
- **元数据登记**：数据源 → 表 → 字段三级模型，字段可标注敏感级别；
- **质量校验**：非空 / 唯一 / 值域三类规则，执行结果留存可查；
- **字段级血缘**：BFS 向上溯源、向下推导影响范围，设深度上限规避环依赖。

错误响应统一为 `{"error": {"code", "message", "request_id"}}`，
每次响应头都带 `X-Request-ID`，便于按请求排查日志。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=DESCRIPTION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,  # 关闭默认 /openapi.json，改为下面自己挂、受 DOCS_ENABLED 控制
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

app.add_middleware(RequestContextMiddleware)
register_error_handlers(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router)
# 业务路由统一挂鉴权依赖：GET→viewer，写→editor，删→admin
app.include_router(datasources.router, dependencies=[Depends(authorize)])
app.include_router(tables.router, dependencies=[Depends(authorize)])
app.include_router(rules.router, dependencies=[Depends(authorize)])
app.include_router(lineage.router, dependencies=[Depends(authorize)])
# 审计查询只给管理员，鉴权在路由内部完成
app.include_router(audit.router)
app.include_router(keys.router)
app.include_router(authinfo.router)


@app.get("/openapi.json", include_in_schema=False)
def openapi_spec():
    if not health.docs_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接口文档已关闭")
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    if not health.docs_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接口文档已关闭")
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - API 文档",
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
        swagger_favicon_url="/static/swagger/favicon-32x32.png",
    )


@app.get("/", tags=["运维"], summary="服务信息")
def root():
    """只暴露“我是谁、怎么探活”，不列接口清单、不报版本号。"""
    return {
        "status": "ok",
        "service": "data-catalog",
        "docs": "/docs" if health.docs_enabled() else None,
        "health": "/health",
        "ready": "/ready",
    }
