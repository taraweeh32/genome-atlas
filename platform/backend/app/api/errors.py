"""Maps domain/transport errors onto the stable API error envelope.

Outside development the response body never contains stack traces, SQL text,
credentials, infrastructure addresses or genomic content.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import get_correlation_id
from app.core.environment import Environment
from app.core.logging import get_logger
from app.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DependencyFailureError,
    DomainError,
    InfrastructureError,
    InvalidStateTransitionError,
    NotFoundError,
    ScientificIntegrationError,
    ValidationError,
)

logger = get_logger(__name__)

_STATUS_BY_ERROR: tuple[tuple[type[DomainError], int], ...] = (
    (ValidationError, 422),
    (AuthenticationError, 401),
    (AuthorizationError, 403),
    (NotFoundError, 404),
    (InvalidStateTransitionError, 409),
    (ConflictError, 409),
    (ScientificIntegrationError, 502),
    (DependencyFailureError, 502),
    (InfrastructureError, 503),
)


def status_for(error: DomainError) -> int:
    for error_type, status in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return status
    return 500


def error_response(
    *, status: int, code: str, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message}
    if details:
        body["details"] = details
    correlation_id = get_correlation_id()
    if correlation_id:
        body["correlation_id"] = correlation_id
    return JSONResponse(status_code=status, content={"error": body})


def register_exception_handlers(app: FastAPI, environment: Environment) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = status_for(exc)
        if status >= 500:
            logger.error("domain error", extra={"error_code": exc.code}, exc_info=exc)
        return error_response(
            status=status, code=exc.code, message=exc.message, details=exc.details
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            status=422,
            code="validation_error",
            message="request validation failed",
            details={
                "fields": [
                    {
                        "location": ".".join(str(part) for part in error["loc"]),
                        "message": error["msg"],
                    }
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "authentication_error", 403: "authorization_error", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        return error_response(status=exc.status_code, code=code, message=str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Full traceback goes to the log only; the response body stays opaque.
        logger.error("unhandled internal error", exc_info=exc)
        details = (
            {"exception": type(exc).__name__, "diagnostic": str(exc)}
            if environment.exposes_diagnostics
            else None
        )
        return error_response(
            status=500,
            code="internal_error",
            message="an internal error occurred",
            details=details,
        )
