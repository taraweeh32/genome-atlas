"""Domain error taxonomy.

Framework-free. The API layer maps these to HTTP status codes and to the stable
error envelope; no HTTP concept appears here.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for every expected, non-bug failure in the platform."""

    code = "domain_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ValidationError(DomainError):
    """Input violates a domain rule or invariant."""

    code = "validation_error"


class AuthenticationError(DomainError):
    """The caller could not be identified."""

    code = "authentication_error"


class AuthorizationError(DomainError):
    """The caller is known but not permitted to perform the operation."""

    code = "authorization_error"


class NotFoundError(DomainError):
    """The addressed resource does not exist or is not visible to the caller.

    Two call shapes are supported deliberately. ``NotFoundError("no such page")``
    carries a message directly; ``NotFoundError("dataset", dataset_id)`` names a
    resource type and the identifier the caller supplied. The second form is what
    use cases raise, so "does not exist" and "not yours" are answered
    identically — the response never confirms that an id exists.
    """

    code = "not_found"

    def __init__(
        self,
        message: str,
        resource_id: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if resource_id is None:
            super().__init__(message, details=details)
            return
        merged = {"resource_type": message, "resource_id": resource_id}
        merged.update(details or {})
        super().__init__(f"{message} was not found", details=merged)




class ConflictError(DomainError):
    """The operation conflicts with the current state (e.g. uniqueness)."""

    code = "conflict"


class InvalidStateTransitionError(DomainError):
    """A lifecycle transition is not permitted from the current state."""

    code = "invalid_state_transition"

    def __init__(self, entity: str, current: str, requested: str) -> None:
        super().__init__(
            f"{entity} cannot transition from {current} to {requested}",
            details={"entity": entity, "current_state": current, "requested_state": requested},
        )


class DependencyFailureError(DomainError):
    """A required external dependency responded with a failure."""

    code = "dependency_failure"


class InfrastructureError(DomainError):
    """A technical component (database, cache, storage) is unavailable."""

    code = "infrastructure_failure"


class ScientificIntegrationError(DomainError):
    """The scientific subsystem could not be reached or reported a failure.

    This never represents a scientific result; it represents an integration
    outcome.
    """

    code = "scientific_integration_failure"


class ConcurrencyConflictError(ConflictError):
    """A concurrent modification was detected via the optimistic version column.

    Raised instead of silently overwriting another actor's change; the caller is
    expected to re-read and retry rather than to force the write.
    """

    code = "concurrency_conflict"


class RateLimitedError(DomainError):
    """Too many attempts for this identity/address within the policy window."""

    code = "rate_limited"

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        super().__init__(
            "too many attempts; please retry later",
            details={"retry_after_seconds": retry_after_seconds}
            if retry_after_seconds is not None
            else None,
        )
        self.retry_after_seconds = retry_after_seconds
