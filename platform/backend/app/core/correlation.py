"""Correlation ID propagation.

One correlation ID travels request -> API operation -> job -> worker ->
scientific execution -> artifact. It is operational metadata only; it is not an
audit record and not scientific provenance.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

CORRELATION_ID_HEADER = "X-Correlation-ID"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(value: str) -> object:
    return _correlation_id.set(value)


def reset_correlation_id(token: object) -> None:
    _correlation_id.reset(token)  # type: ignore[arg-type]


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def require_correlation_id() -> str:
    """Return the active correlation ID, minting one outside a request context."""
    return _correlation_id.get() or new_correlation_id()
