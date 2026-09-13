"""Workspace domain entity.

A workspace is the tenancy boundary: personal (owned by exactly one user, no
organization) or organization (owned by exactly one organization). The XOR is
enforced in the database by Package 2 and re-asserted here so an invalid
workspace can never be constructed in memory either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import DeletionState, WorkspaceKind


@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    kind: WorkspaceKind
    name: str
    owner_user_id: str | None = None
    organization_id: str | None = None
    created_by: str | None = None
    deletion_state: DeletionState = DeletionState.ACTIVE
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.kind is WorkspaceKind.PERSONAL:
            if self.organization_id is not None:
                raise ValidationError("a personal workspace has no organization")
            if self.owner_user_id is None:
                raise ValidationError("a personal workspace requires an owner")
        elif self.organization_id is None:
            raise ValidationError("an organization workspace requires an organization")

    @property
    def is_personal(self) -> bool:
        return self.kind is WorkspaceKind.PERSONAL

    @property
    def is_usable(self) -> bool:
        return self.deletion_state is DeletionState.ACTIVE


__all__ = ["Workspace"]
