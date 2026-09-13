"""Organization, membership and invitation domain entities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import (
    DeletionState,
    InvitationState,
    MembershipState,
    OrganizationRole,
    OrganizationState,
)

_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{1,62}[a-z0-9])?$")


def normalize_slug(raw: str) -> str:
    """Organization slugs are lowercase, hyphenated and globally unique."""
    candidate = (raw or "").strip().casefold()
    candidate = re.sub(r"[\s_]+", "-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
    if not _SLUG_PATTERN.match(candidate):
        raise ValidationError(
            "organization slug must be lowercase letters, digits and hyphens",
            details={"field": "slug"},
        )
    return candidate


@dataclass(frozen=True, slots=True)
class Organization:
    id: str
    slug: str
    name: str
    state: OrganizationState
    deletion_state: DeletionState = DeletionState.ACTIVE
    description: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    approval_decided_by: str | None = None
    approval_decided_at: datetime | None = None
    approval_decision_reason: str | None = None
    suspended_at: datetime | None = None
    deactivated_at: datetime | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_usable(self) -> bool:
        return (
            self.state in (OrganizationState.ACTIVE, OrganizationState.APPROVED)
            and self.deletion_state is DeletionState.ACTIVE
        )

    @property
    def is_under_review(self) -> bool:
        return self.state in (OrganizationState.REQUESTED, OrganizationState.PENDING)


@dataclass(frozen=True, slots=True)
class OrganizationMembership:
    """Membership of one organization. Never implies project access."""

    id: str
    organization_id: str
    user_id: str
    role: OrganizationRole
    state: MembershipState
    invited_by: str | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None
    removed_by: str | None = None
    version: int = 1

    @property
    def is_active(self) -> bool:
        return self.state is MembershipState.ACTIVE


@dataclass(frozen=True, slots=True)
class OrganizationInvitation:
    """An invitation. The token itself is never stored or returned — only its hash."""

    id: str
    organization_id: str
    invited_email_normalized: str
    role: OrganizationRole
    state: InvitationState
    expires_at: datetime
    invited_by: str | None = None
    responded_at: datetime | None = None
    accepted_user_id: str | None = None
    version: int = 1
    created_at: datetime | None = None

    def is_open_at(self, moment: datetime) -> bool:
        return self.state is InvitationState.PENDING and self.expires_at > moment


__all__ = [
    "Organization",
    "OrganizationInvitation",
    "OrganizationMembership",
    "normalize_slug",
]
