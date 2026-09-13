"""Domain invariants: identifiers and workspace/tenancy context."""

from __future__ import annotations

import pytest

from app.domain.entities.base import Entity, utc_now
from app.domain.errors import ValidationError
from app.domain.value_objects.identifiers import (
    OrganizationId,
    ProjectId,
    UserId,
    WorkspaceId,
)
from app.domain.workspace.context import AuthorizationContext, WorkspaceKind, WorkspaceRef


class TestIdentifiers:
    def test_generated_identifier_uses_its_prefix(self) -> None:
        assert WorkspaceId.generate().value.startswith("wsp_")
        assert OrganizationId.generate().value.startswith("org_")
        assert ProjectId.generate().value.startswith("prj_")

    def test_generated_identifiers_are_unique(self) -> None:
        assert len({WorkspaceId.generate().value for _ in range(100)}) == 100

    def test_prefix_of_another_entity_is_rejected(self) -> None:
        organization = OrganizationId.generate().value
        with pytest.raises(ValidationError):
            WorkspaceId.parse(organization)

    def test_malformed_suffix_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserId.parse("usr_not-a-hex-suffix")

    def test_error_details_do_not_leak_the_raw_value(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            UserId.parse("usr_secret")
        assert "secret" not in str(excinfo.value.details)


class TestWorkspaceRef:
    def test_organization_workspace_requires_an_organization(self) -> None:
        with pytest.raises(ValidationError):
            WorkspaceRef(id=WorkspaceId.generate(), kind=WorkspaceKind.ORGANIZATION)

    def test_personal_workspace_rejects_an_organization(self) -> None:
        with pytest.raises(ValidationError):
            WorkspaceRef(
                id=WorkspaceId.generate(),
                kind=WorkspaceKind.PERSONAL,
                organization_id=OrganizationId.generate(),
            )

    def test_personal_workspace_needs_no_organization(self) -> None:
        workspace = WorkspaceRef(id=WorkspaceId.generate(), kind=WorkspaceKind.PERSONAL)
        assert workspace.organization_id is None


class TestAuthorizationContext:
    def test_anonymous_context_is_not_authenticated(self) -> None:
        context = AuthorizationContext.anonymous()
        assert context.is_authenticated is False
        assert context.permissions == frozenset()

    def test_context_carries_actor_and_workspace(self) -> None:
        workspace = WorkspaceRef(id=WorkspaceId.generate(), kind=WorkspaceKind.PERSONAL)
        context = AuthorizationContext(actor_id=UserId.generate(), workspace=workspace)
        assert context.is_authenticated is True
        assert context.workspace is workspace


class TestEntityConventions:
    def test_timestamps_are_timezone_aware_utc(self) -> None:
        now = utc_now()
        assert now.tzinfo is not None
        assert now.utcoffset() is not None and now.utcoffset().total_seconds() == 0

    def test_identity_equality_ignores_timestamps(self) -> None:
        identifier = WorkspaceId.generate()
        first = Entity(id=identifier)
        second = Entity(id=identifier)
        assert first == second
        assert hash(first) == hash(second)

    def test_touch_advances_updated_at(self) -> None:
        entity = Entity(id=WorkspaceId.generate())
        before = entity.updated_at
        entity.touch()
        assert entity.updated_at >= before
