"""Request lifecycle middleware: correlation, access logs, size limits, headers."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.correlation import (
    CORRELATION_ID_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.core.logging import get_logger

logger = get_logger("app.access")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Accepts an inbound correlation ID or mints one, and echoes it back."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(CORRELATION_ID_HEADER, "").strip()
        correlation_id = incoming if 8 <= len(incoming) <= 128 else new_correlation_id()
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "http request",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized declared bodies before they are read into memory.

    Genomic file uploads never traverse the API: they are presigned directly to
    object storage, so a small API body limit is correct.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "validation_error",
                        "message": "request body too large",
                        "details": {"max_bytes": self._max_bytes},
                    }
                },
            )
        return await call_next(request)
