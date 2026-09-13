"""Backend-owned lifecycle state machines.

A lifecycle transition is a *named domain operation*, never an arbitrary status
assignment. Every transition table lives here so no route, controller or
repository can invent a transition of its own, and so the legal graph is
reviewable in one place.

The tables are expressed over the Package 2 state vocabularies
(``app.domain.value_objects.enums``); Package 2 constrains which *values* may be
persisted, this module constrains which *moves* are legal.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.errors import InvalidStateTransitionError
from app.domain.value_objects.enums import (
    AccountState,
    DeletionState,
    EmailVerificationState,
    InvitationState,
    MembershipState,
    OrganizationState,
    ProjectState,
    StrEnum,
)

#: Account lifecycle. Suspension and deactivation are reversible and never
#: destroy account-owned resources; deletion is a separate retention concern
#: (``DeletionState``), deliberately not folded into the account state.
ACCOUNT_TRANSITIONS: Mapping[AccountState, frozenset[AccountState]] = {
    AccountState.PENDING_VERIFICATION: frozenset(
        {AccountState.ACTIVE, AccountState.SUSPENDED, AccountState.DEACTIVATED}
    ),
    AccountState.ACTIVE: frozenset(
        {AccountState.SUSPENDED, AccountState.DEACTIVATED, AccountState.LOCKED}
    ),
    AccountState.LOCKED: frozenset(
        {AccountState.ACTIVE, AccountState.SUSPENDED, AccountState.DEACTIVATED}
    ),
    AccountState.SUSPENDED: frozenset({AccountState.ACTIVE, AccountState.DEACTIVATED}),
    AccountState.DEACTIVATED: frozenset({AccountState.ACTIVE}),
}

EMAIL_VERIFICATION_TRANSITIONS: Mapping[
    EmailVerificationState, frozenset[EmailVerificationState]
] = {
    EmailVerificationState.UNVERIFIED: frozenset(
        {EmailVerificationState.PENDING, EmailVerificationState.VERIFIED}
    ),
    EmailVerificationState.PENDING: frozenset(
        {
            EmailVerificationState.VERIFIED,
            EmailVerificationState.FAILED,
            EmailVerificationState.PENDING,
        }
    ),
    EmailVerificationState.FAILED: frozenset({EmailVerificationState.PENDING}),
    EmailVerificationState.VERIFIED: frozenset(),
}

#: Organization lifecycle. ``requested``/``pending`` are the review states;
#: only an approval decision may leave them, and a rejected request is retained
#: forever (there is no transition out of ``rejected``).
ORGANIZATION_TRANSITIONS: Mapping[OrganizationState, frozenset[OrganizationState]] = {
    OrganizationState.REQUESTED: frozenset(
        {OrganizationState.PENDING, OrganizationState.APPROVED, OrganizationState.REJECTED}
    ),
    OrganizationState.PENDING: frozenset(
        {OrganizationState.APPROVED, OrganizationState.REJECTED}
    ),
    OrganizationState.APPROVED: frozenset({OrganizationState.ACTIVE, OrganizationState.SUSPENDED}),
    OrganizationState.ACTIVE: frozenset(
        {OrganizationState.SUSPENDED, OrganizationState.DEACTIVATED}
    ),
    OrganizationState.SUSPENDED: frozenset(
        {OrganizationState.ACTIVE, OrganizationState.DEACTIVATED}
    ),
    OrganizationState.DEACTIVATED: frozenset({OrganizationState.ACTIVE}),
    OrganizationState.REJECTED: frozenset(),
}

PROJECT_TRANSITIONS: Mapping[ProjectState, frozenset[ProjectState]] = {
    ProjectState.DRAFT: frozenset({ProjectState.ACTIVE, ProjectState.ARCHIVED}),
    ProjectState.ACTIVE: frozenset(
        {ProjectState.ARCHIVED, ProjectState.SUSPENDED, ProjectState.CLOSED}
    ),
    ProjectState.ARCHIVED: frozenset({ProjectState.ACTIVE, ProjectState.CLOSED}),
    ProjectState.SUSPENDED: frozenset({ProjectState.ACTIVE, ProjectState.CLOSED}),
    ProjectState.CLOSED: frozenset({ProjectState.ACTIVE}),
}

MEMBERSHIP_TRANSITIONS: Mapping[MembershipState, frozenset[MembershipState]] = {
    MembershipState.INVITED: frozenset(
        {MembershipState.ACTIVE, MembershipState.REMOVED, MembershipState.LEFT}
    ),
    MembershipState.ACTIVE: frozenset(
        {MembershipState.SUSPENDED, MembershipState.LEFT, MembershipState.REMOVED}
    ),
    MembershipState.SUSPENDED: frozenset({MembershipState.ACTIVE, MembershipState.REMOVED}),
    MembershipState.LEFT: frozenset({MembershipState.ACTIVE}),
    MembershipState.REMOVED: frozenset({MembershipState.ACTIVE}),
}

INVITATION_TRANSITIONS: Mapping[InvitationState, frozenset[InvitationState]] = {
    InvitationState.PENDING: frozenset(
        {
            InvitationState.ACCEPTED,
            InvitationState.DECLINED,
            InvitationState.REVOKED,
            InvitationState.EXPIRED,
        }
    ),
    InvitationState.ACCEPTED: frozenset(),
    InvitationState.DECLINED: frozenset(),
    InvitationState.REVOKED: frozenset(),
    InvitationState.EXPIRED: frozenset(),
}

#: Retention lifecycle, kept strictly separate from operational state.
DELETION_TRANSITIONS: Mapping[DeletionState, frozenset[DeletionState]] = {
    DeletionState.ACTIVE: frozenset({DeletionState.SOFT_DELETED}),
    DeletionState.SOFT_DELETED: frozenset({DeletionState.ACTIVE, DeletionState.RETENTION}),
    DeletionState.RETENTION: frozenset({DeletionState.ACTIVE, DeletionState.PURGE_PENDING}),
    DeletionState.PURGE_PENDING: frozenset({DeletionState.PERMANENTLY_DELETED}),
    DeletionState.PERMANENTLY_DELETED: frozenset(),
}


_TABLES: dict[str, Mapping[StrEnum, frozenset[StrEnum]]] = {
    "account": ACCOUNT_TRANSITIONS,  # type: ignore[dict-item]
    "email_verification": EMAIL_VERIFICATION_TRANSITIONS,  # type: ignore[dict-item]
    "organization": ORGANIZATION_TRANSITIONS,  # type: ignore[dict-item]
    "project": PROJECT_TRANSITIONS,  # type: ignore[dict-item]
    "membership": MEMBERSHIP_TRANSITIONS,  # type: ignore[dict-item]
    "invitation": INVITATION_TRANSITIONS,  # type: ignore[dict-item]
    "deletion": DELETION_TRANSITIONS,  # type: ignore[dict-item]
}


def can_transition(entity: str, current: StrEnum, requested: StrEnum) -> bool:
    table = _TABLES[entity]
    return requested in table.get(current, frozenset())


def require_transition(entity: str, current: StrEnum, requested: StrEnum) -> StrEnum:
    """Return ``requested`` when the move is legal, else raise.

    Raising ``InvalidStateTransitionError`` maps to HTTP 409 at the transport
    boundary without any route knowing the rule.
    """
    if not can_transition(entity, current, requested):
        raise InvalidStateTransitionError(entity, str(current), str(requested))
    return requested


def transition_targets(entity: str, current: StrEnum) -> frozenset[StrEnum]:
    return _TABLES[entity].get(current, frozenset())


__all__ = [
    "ACCOUNT_TRANSITIONS",
    "DELETION_TRANSITIONS",
    "EMAIL_VERIFICATION_TRANSITIONS",
    "INVITATION_TRANSITIONS",
    "MEMBERSHIP_TRANSITIONS",
    "ORGANIZATION_TRANSITIONS",
    "PROJECT_TRANSITIONS",
    "can_transition",
    "require_transition",
    "transition_targets",
]
