"""Shared API schema conventions for /api/v1.

Conventions fixed here and reused by every later resource module:
- identifiers are opaque prefixed strings, never database primary keys;
- timestamps are ISO-8601 UTC;
- collections are returned as ``{ "items": [...], "page": {...} }``;
- errors are returned as ``{ "error": { code, message, details?, correlation_id } }``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorDetail(ApiModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable, non-sensitive summary.")
    details: dict[str, object] | None = Field(
        default=None, description="Structured, non-sensitive error context."
    )
    correlation_id: str | None = Field(
        default=None, description="Correlates this response with server logs."
    )


class ErrorResponse(ApiModel):
    error: ErrorDetail


class PageInfo(ApiModel):
    limit: int
    cursor: str | None = None
    next_cursor: str | None = None


class Collection[ItemT](ApiModel):
    items: list[ItemT]
    page: PageInfo


class Timestamped(ApiModel):
    created_at: datetime
    updated_at: datetime


# Reusable OpenAPI response declarations, so every route documents the same
# error contract without duplicating it.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Authentication error"},
    403: {"model": ErrorResponse, "description": "Authorization error"},
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Conflict or invalid state transition"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    500: {"model": ErrorResponse, "description": "Internal error"},
    502: {"model": ErrorResponse, "description": "Dependency or scientific integration failure"},
    503: {"model": ErrorResponse, "description": "Infrastructure unavailable"},
}
