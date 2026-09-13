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
    DatasetState,
    DatasetVersionState,
    DeletionState,
    EmailVerificationState,
    FileUploadState,
    FileValidationState,
    ImportSessionState,
    InvitationState,
    MalwareScanState,
    MembershipState,
    OrganizationState,
    ProjectState,
    StrEnum,
    UploadSessionState,
    ValidationRunState,
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


# --------------------------------------------------------------------------- #
# Datasets, uploads, import and validation (Package 4)                        #
# --------------------------------------------------------------------------- #

#: A dataset is the mutable, named resource. It becomes ``ready`` only when a
#: version has been accepted, and ``rejected`` is recoverable by submitting a
#: corrected version — the rejection itself is never erased.
DATASET_TRANSITIONS: Mapping[DatasetState, frozenset[DatasetState]] = {
    DatasetState.DRAFT: frozenset(
        {DatasetState.VALIDATING, DatasetState.READY, DatasetState.REJECTED,
         DatasetState.ARCHIVED}
    ),
    DatasetState.VALIDATING: frozenset(
        {DatasetState.READY, DatasetState.REJECTED, DatasetState.DRAFT}
    ),
    DatasetState.READY: frozenset(
        {DatasetState.VALIDATING, DatasetState.ARCHIVED, DatasetState.DRAFT}
    ),
    DatasetState.REJECTED: frozenset({DatasetState.DRAFT, DatasetState.ARCHIVED}),
    DatasetState.ARCHIVED: frozenset({DatasetState.READY, DatasetState.DRAFT}),
}

#: A dataset version is an immutable scientific input. The only mutation allowed
#: is its own acceptance bookkeeping, which happens once; a correction produces a
#: *new* version and marks this one ``superseded``. There is deliberately no way
#: back out of ``accepted``, ``rejected`` or ``superseded`` into a working state.
DATASET_VERSION_TRANSITIONS: Mapping[DatasetVersionState, frozenset[DatasetVersionState]] = {
    DatasetVersionState.CREATED: frozenset(
        {DatasetVersionState.UPLOADING, DatasetVersionState.REJECTED}
    ),
    DatasetVersionState.UPLOADING: frozenset(
        {DatasetVersionState.VALIDATING, DatasetVersionState.REJECTED}
    ),
    DatasetVersionState.VALIDATING: frozenset(
        {DatasetVersionState.VALIDATED, DatasetVersionState.REJECTED}
    ),
    DatasetVersionState.VALIDATED: frozenset(
        {DatasetVersionState.ACCEPTED, DatasetVersionState.REJECTED}
    ),
    DatasetVersionState.ACCEPTED: frozenset({DatasetVersionState.SUPERSEDED}),
    DatasetVersionState.REJECTED: frozenset(),
    DatasetVersionState.SUPERSEDED: frozenset(),
}

#: Byte transfer. ``uploaded`` means "bytes arrived", never "usable".
FILE_UPLOAD_TRANSITIONS: Mapping[FileUploadState, frozenset[FileUploadState]] = {
    FileUploadState.PENDING: frozenset(
        {FileUploadState.IN_PROGRESS, FileUploadState.ABORTED, FileUploadState.FAILED}
    ),
    FileUploadState.IN_PROGRESS: frozenset(
        {FileUploadState.UPLOADED, FileUploadState.FAILED, FileUploadState.ABORTED}
    ),
    FileUploadState.UPLOADED: frozenset(),
    FileUploadState.FAILED: frozenset({FileUploadState.PENDING}),
    FileUploadState.ABORTED: frozenset(),
}

#: Usability of an artifact. Quarantine is terminal for that artifact: a
#: quarantined object is never promoted, only replaced by a fresh upload.
FILE_VALIDATION_TRANSITIONS: Mapping[FileValidationState, frozenset[FileValidationState]] = {
    FileValidationState.NOT_VALIDATED: frozenset(
        {FileValidationState.VALIDATING, FileValidationState.QUARANTINED}
    ),
    FileValidationState.VALIDATING: frozenset(
        {
            FileValidationState.VALID,
            FileValidationState.INVALID,
            FileValidationState.QUARANTINED,
        }
    ),
    FileValidationState.VALID: frozenset(
        {FileValidationState.VALIDATING, FileValidationState.QUARANTINED}
    ),
    FileValidationState.INVALID: frozenset(
        {FileValidationState.VALIDATING, FileValidationState.QUARANTINED}
    ),
    FileValidationState.QUARANTINED: frozenset(),
}

#: The upload session: permission to transfer, then the gate that decides whether
#: the transferred bytes may become a scientific input at all.
UPLOAD_SESSION_TRANSITIONS: Mapping[UploadSessionState, frozenset[UploadSessionState]] = {
    UploadSessionState.CREATED: frozenset(
        {
            UploadSessionState.UPLOADING,
            UploadSessionState.CANCELLED,
            UploadSessionState.EXPIRED,
        }
    ),
    UploadSessionState.UPLOADING: frozenset(
        {
            UploadSessionState.UPLOADED,
            UploadSessionState.FAILED,
            UploadSessionState.CANCELLED,
            UploadSessionState.EXPIRED,
        }
    ),
    UploadSessionState.UPLOADED: frozenset(
        {
            UploadSessionState.SCANNING,
            UploadSessionState.QUARANTINED,
            UploadSessionState.REJECTED,
            UploadSessionState.FAILED,
        }
    ),
    UploadSessionState.SCANNING: frozenset(
        {
            UploadSessionState.VALIDATING,
            UploadSessionState.QUARANTINED,
            UploadSessionState.REJECTED,
            UploadSessionState.FAILED,
        }
    ),
    UploadSessionState.VALIDATING: frozenset(
        {
            UploadSessionState.ACCEPTED,
            UploadSessionState.REJECTED,
            UploadSessionState.QUARANTINED,
            UploadSessionState.FAILED,
        }
    ),
    UploadSessionState.ACCEPTED: frozenset(),
    UploadSessionState.REJECTED: frozenset(),
    UploadSessionState.QUARANTINED: frozenset(),
    UploadSessionState.EXPIRED: frozenset(),
    UploadSessionState.CANCELLED: frozenset(),
    UploadSessionState.FAILED: frozenset({UploadSessionState.CANCELLED}),
}

#: Scanning outcomes are recorded, not re-decided: an ``unavailable`` scan may be
#: retried, but it never becomes ``clean`` without an actual clean result.
MALWARE_SCAN_TRANSITIONS: Mapping[MalwareScanState, frozenset[MalwareScanState]] = {
    MalwareScanState.NOT_SCANNED: frozenset({MalwareScanState.SCANNING}),
    MalwareScanState.SCANNING: frozenset(
        {
            MalwareScanState.CLEAN,
            MalwareScanState.INFECTED,
            MalwareScanState.UNAVAILABLE,
            MalwareScanState.FAILED,
        }
    ),
    MalwareScanState.CLEAN: frozenset(),
    MalwareScanState.INFECTED: frozenset(),
    MalwareScanState.UNAVAILABLE: frozenset({MalwareScanState.SCANNING}),
    MalwareScanState.FAILED: frozenset({MalwareScanState.SCANNING}),
}

#: Import history is preserved: a rejected import and its reason stay queryable,
#: and an abandoned session is never silently deleted.
IMPORT_SESSION_TRANSITIONS: Mapping[ImportSessionState, frozenset[ImportSessionState]] = {
    ImportSessionState.OPEN: frozenset(
        {ImportSessionState.SUBMITTED, ImportSessionState.ABANDONED}
    ),
    ImportSessionState.SUBMITTED: frozenset(
        {
            ImportSessionState.VALIDATING,
            ImportSessionState.REJECTED,
            ImportSessionState.ABANDONED,
        }
    ),
    ImportSessionState.VALIDATING: frozenset(
        {ImportSessionState.ACCEPTED, ImportSessionState.REJECTED}
    ),
    ImportSessionState.ACCEPTED: frozenset(),
    ImportSessionState.REJECTED: frozenset({ImportSessionState.OPEN}),
    ImportSessionState.ABANDONED: frozenset(),
}

#: A validation run is a recorded execution: its terminal outcome is a fact and
#: is never rewritten. Re-validation creates a new run.
VALIDATION_RUN_TRANSITIONS: Mapping[ValidationRunState, frozenset[ValidationRunState]] = {
    ValidationRunState.PENDING: frozenset(
        {ValidationRunState.RUNNING, ValidationRunState.ERRORED}
    ),
    ValidationRunState.RUNNING: frozenset(
        {
            ValidationRunState.PASSED,
            ValidationRunState.PASSED_WITH_WARNINGS,
            ValidationRunState.FAILED,
            ValidationRunState.ERRORED,
        }
    ),
    ValidationRunState.PASSED: frozenset(),
    ValidationRunState.PASSED_WITH_WARNINGS: frozenset(),
    ValidationRunState.FAILED: frozenset(),
    ValidationRunState.ERRORED: frozenset(),
}


_TABLES: dict[str, Mapping[StrEnum, frozenset[StrEnum]]] = {
    "account": ACCOUNT_TRANSITIONS,  # type: ignore[dict-item]
    "email_verification": EMAIL_VERIFICATION_TRANSITIONS,  # type: ignore[dict-item]
    "organization": ORGANIZATION_TRANSITIONS,  # type: ignore[dict-item]
    "project": PROJECT_TRANSITIONS,  # type: ignore[dict-item]
    "membership": MEMBERSHIP_TRANSITIONS,  # type: ignore[dict-item]
    "invitation": INVITATION_TRANSITIONS,  # type: ignore[dict-item]
    "deletion": DELETION_TRANSITIONS,  # type: ignore[dict-item]
    "dataset": DATASET_TRANSITIONS,  # type: ignore[dict-item]
    "dataset_version": DATASET_VERSION_TRANSITIONS,  # type: ignore[dict-item]
    "file_upload": FILE_UPLOAD_TRANSITIONS,  # type: ignore[dict-item]
    "file_validation": FILE_VALIDATION_TRANSITIONS,  # type: ignore[dict-item]
    "upload_session": UPLOAD_SESSION_TRANSITIONS,  # type: ignore[dict-item]
    "malware_scan": MALWARE_SCAN_TRANSITIONS,  # type: ignore[dict-item]
    "import_session": IMPORT_SESSION_TRANSITIONS,  # type: ignore[dict-item]
    "validation_run": VALIDATION_RUN_TRANSITIONS,  # type: ignore[dict-item]
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
    "DATASET_TRANSITIONS",
    "DATASET_VERSION_TRANSITIONS",
    "DELETION_TRANSITIONS",
    "EMAIL_VERIFICATION_TRANSITIONS",
    "FILE_UPLOAD_TRANSITIONS",
    "FILE_VALIDATION_TRANSITIONS",
    "IMPORT_SESSION_TRANSITIONS",
    "INVITATION_TRANSITIONS",
    "MALWARE_SCAN_TRANSITIONS",
    "MEMBERSHIP_TRANSITIONS",
    "ORGANIZATION_TRANSITIONS",
    "PROJECT_TRANSITIONS",
    "UPLOAD_SESSION_TRANSITIONS",
    "VALIDATION_RUN_TRANSITIONS",
    "can_transition",
    "require_transition",
    "transition_targets",
]
