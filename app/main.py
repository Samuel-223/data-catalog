from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .db import Base, engine
from .routers import datasources, lineage, rules, tables

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="数据资产目录服务",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(datasources.router)
app.include_router(tables.router)
app.include_router(rules.router)
app.include_router(lineage.router)


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - API 文档",
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
        swagger_favicon_url="/static/swagger/favicon-32x32.png",
    )


@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=400,
        content={"detail": "数据约束冲突，请检查字段是否为空或重复"},
    )


@app.get("/")
def root():
    return {"status": "ok", "service": "data-catalog", "version": "0.2.0"}
