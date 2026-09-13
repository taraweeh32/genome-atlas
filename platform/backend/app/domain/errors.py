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
    """The addressed resource does not exist or is not visible to the caller."""

    code = "not_found"


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
