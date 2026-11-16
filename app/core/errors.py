"""统一错误响应：所有失败都返回同一形状，调用方只需解析一个结构。

{
  "error": {"code": "not_found", "message": "…", "request_id": "…", "details": [...]},
  "detail": "…"      # 兼容 FastAPI 默认字段，老调用方不受影响
}
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from .logging import request_id_ctx

logger = logging.getLogger("app.error")

STATUS_CODE_MAP = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}


def _envelope(code: str, message: str, details=None) -> dict:
    body = {"code": code, "message": message, "request_id": request_id_ctx.get()}
    if details:
        body["details"] = details
    return {"error": body, "detail": message}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = STATUS_CODE_MAP.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in err.get("loc", [])[1:]),
                "problem": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "请求参数校验失败", details),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError):
        logger.warning("integrity_conflict", extra={"extra_fields": {"path": request.url.path}})
        return JSONResponse(
            status_code=400,
            content=_envelope("conflict", "数据约束冲突，请检查字段是否为空或重复"),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled_error", extra={"extra_fields": {"path": request.url.path}})
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "服务内部错误，请稍后重试或联系管理员"),
        )
