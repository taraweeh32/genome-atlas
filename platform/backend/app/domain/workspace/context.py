"""Workspace context - the domain-side tenancy concept.

A workspace is either a user's *personal* workspace or an *organization*
workspace. A user need not belong to any organization. A project always belongs
to exactly one workspace. Membership and authorization rules are implemented in
a later package; Package 1 fixes the shape so later modules do not reinvent it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.domain.errors import ValidationError
from app.domain.value_objects.identifiers import OrganizationId, ProjectId, UserId, WorkspaceId


class WorkspaceKind(str, enum.Enum):
    PERSONAL = "personal"
    ORGANIZATION = "organization"


@dataclass(frozen=True, slots=True)
class WorkspaceRef:
    """Identifies the tenancy scope an operation executes in."""

    id: WorkspaceId
    kind: WorkspaceKind
    organization_id: OrganizationId | None = None

    def __post_init__(self) -> None:
        if self.kind is WorkspaceKind.ORGANIZATION and self.organization_id is None:
            raise ValidationError("an organization workspace requires an organization id")
        if self.kind is WorkspaceKind.PERSONAL and self.organization_id is not None:
            raise ValidationError("a personal workspace must not carry an organization id")


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Propagated from transport through the application layer into use cases.

    Package 1 only defines and propagates it. The authenticated identity and the
    permission set are populated once authentication/RBAC land.
    """

    actor_id: UserId | None = None
    workspace: WorkspaceRef | None = None
    project_id: ProjectId | None = None
    permissions: frozenset[str] = frozenset()

    @property
    def is_authenticated(self) -> bool:
        return self.actor_id is not None

    @classmethod
    def anonymous(cls) -> AuthorizationContext:
        return cls()
