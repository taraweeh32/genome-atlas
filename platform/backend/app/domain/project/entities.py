"""Project and project-membership domain entities.

``created_by`` and ``owner_user_id`` are distinct on purpose: the creator is a
historical fact that never changes, the owner is an accountable party that may be
transferred. Later resource types (datasets, analyses, reports) reuse this same
distinction rather than inventing their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import (
    DeletionState,
    MembershipState,
    ProjectRole,
    ProjectState,
)

MAX_PROJECT_NAME_LENGTH = 255


def clean_project_name(raw: str) -> str:
    candidate = (raw or "").strip()
    if not candidate:
        raise ValidationError("a project name is required", details={"field": "name"})
    if len(candidate) > MAX_PROJECT_NAME_LENGTH:
        raise ValidationError(
            "project name is too long",
            details={"field": "name", "max_length": MAX_PROJECT_NAME_LENGTH},
        )
    return candidate


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    workspace_id: str
    name: str
    state: ProjectState
    created_by: str
    owner_user_id: str | None = None
    description: str | None = None
    deletion_state: DeletionState = DeletionState.ACTIVE
    archived_at: datetime | None = None
    archived_by: str | None = None
    reopened_at: datetime | None = None
    closed_at: datetime | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return (
            self.state in (ProjectState.DRAFT, ProjectState.ACTIVE)
            and self.deletion_state is DeletionState.ACTIVE
        )


@dataclass(frozen=True, slots=True)
class ProjectMembership:
    id: str
    project_id: str
    user_id: str
    role: ProjectRole
    state: MembershipState
    granted_by: str | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None
    version: int = 1

    @property
    def is_active(self) -> bool:
        return self.state is MembershipState.ACTIVE


__all__ = [
    "MAX_PROJECT_NAME_LENGTH",
    "Project",
    "ProjectMembership",
    "clean_project_name",
]
