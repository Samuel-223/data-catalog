"""请求上下文中间件：生成/透传 X-Request-ID，记录耗时与状态码。"""

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .logging import request_id_ctx

logger = logging.getLogger("app.access")

SKIP_PATHS = {"/health", "/ready", "/metrics"}

# 本地 Swagger UI 需要内联样式，故放开 style-src，脚本仍限制同源
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'"
    ),
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.exception(
                "request_failed",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": 500,
                        "duration_ms": duration_ms,
                    }
                },
            )
            raise
        finally:
            request_id_ctx.reset(token)

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = str(duration_ms)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)

        if request.url.path not in SKIP_PATHS:
            log = logger.info if response.status_code < 500 else logger.warning
            log(
                "request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": duration_ms,
                    }
                },
            )
        return response
