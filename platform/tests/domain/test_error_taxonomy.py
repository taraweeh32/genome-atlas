"""The error taxonomy and its HTTP mapping must stay stable and framework-free."""

from __future__ import annotations

import pytest

from app.api.errors import status_for
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


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_status"),
    [
        (ValidationError("bad"), "validation_error", 422),
        (AuthenticationError("who"), "authentication_error", 401),
        (AuthorizationError("no"), "authorization_error", 403),
        (NotFoundError("gone"), "not_found", 404),
        (ConflictError("dup"), "conflict", 409),
        (
            InvalidStateTransitionError("analysis", "draft", "reported"),
            "invalid_state_transition",
            409,
        ),
        (DependencyFailureError("upstream"), "dependency_failure", 502),
        (InfrastructureError("db"), "infrastructure_failure", 503),
        (ScientificIntegrationError("engine"), "scientific_integration_failure", 502),
    ],
)
def test_taxonomy_codes_and_status_mapping(
    error: DomainError, expected_code: str, expected_status: int
) -> None:
    assert error.code == expected_code
    assert status_for(error) == expected_status


def test_unknown_domain_error_maps_to_internal_error() -> None:
    class SurpriseError(DomainError):
        pass

    assert status_for(SurpriseError("x")) == 500


def test_invalid_state_transition_records_both_states() -> None:
    error = InvalidStateTransitionError("job", "queued", "reported")
    assert error.details == {
        "entity": "job",
        "current_state": "queued",
        "requested_state": "reported",
    }


def test_every_taxonomy_member_has_a_distinct_code() -> None:
    errors = [
        ValidationError,
        AuthenticationError,
        AuthorizationError,
        NotFoundError,
        ConflictError,
        InvalidStateTransitionError,
        DependencyFailureError,
        InfrastructureError,
        ScientificIntegrationError,
    ]
    codes = [error.code for error in errors]
    assert len(codes) == len(set(codes))
