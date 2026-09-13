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
    AnalysisState,
    DatasetState,
    DatasetVersionState,
    DeletionState,
    EmailVerificationState,
    ExecutionState,
    FileUploadState,
    FileValidationState,
    ImportSessionState,
    InvitationState,
    JobState,
    MalwareScanState,
    MembershipState,
    NodeLifecycleState,
    OrganizationState,
    ProjectState,
    ResultArtifactState,
    ResultIngestionState,
    ResultSetState,
    ScheduleState,
    ScientificExecutionState,
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
            # A grant can fail before a single byte arrives — no object was
            # stored, for instance. That is a recorded failure, not a silent
            # cancellation.
            UploadSessionState.FAILED,
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


# --------------------------------------------------------------------------- #
# Analyses, executions, jobs, schedules, compute nodes (Package 5)            #
# --------------------------------------------------------------------------- #

#: The analysis *definition*. It never carries run state: a running execution
#: does not move its definition, and archiving a definition never rewrites the
#: executions that already happened.
ANALYSIS_TRANSITIONS: Mapping[AnalysisState, frozenset[AnalysisState]] = {
    AnalysisState.DRAFT: frozenset({AnalysisState.READY, AnalysisState.ARCHIVED}),
    AnalysisState.READY: frozenset(
        {AnalysisState.ACTIVE, AnalysisState.DRAFT, AnalysisState.ARCHIVED}
    ),
    AnalysisState.ACTIVE: frozenset({AnalysisState.READY, AnalysisState.ARCHIVED}),
    AnalysisState.ARCHIVED: frozenset({AnalysisState.READY}),
}

#: One execution attempt. Append-only in spirit: every terminal state is final,
#: and a re-run is always a *new* execution row with a new attempt sequence.
#: ``cancel_requested`` exists because asking a running execution to stop is a
#: distinct fact from it having stopped.
ANALYSIS_EXECUTION_TRANSITIONS: Mapping[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.DRAFT: frozenset({ExecutionState.VALIDATING, ExecutionState.CANCELLED}),
    ExecutionState.VALIDATING: frozenset(
        {ExecutionState.VALIDATED, ExecutionState.FAILED, ExecutionState.CANCELLED}
    ),
    ExecutionState.VALIDATED: frozenset(
        {ExecutionState.REQUESTED, ExecutionState.FAILED, ExecutionState.CANCELLED}
    ),
    ExecutionState.REQUESTED: frozenset(
        {
            ExecutionState.QUEUED,
            ExecutionState.FAILED,
            ExecutionState.CANCEL_REQUESTED,
            ExecutionState.CANCELLED,
        }
    ),
    ExecutionState.QUEUED: frozenset(
        {
            ExecutionState.SUBMITTED,
            ExecutionState.RUNNING,
            ExecutionState.FAILED,
            ExecutionState.CANCEL_REQUESTED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    #: Handed to the scientific subsystem; the application is now an observer.
    ExecutionState.SUBMITTED: frozenset(
        {
            ExecutionState.RUNNING,
            ExecutionState.SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.CANCEL_REQUESTED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.RUNNING: frozenset(
        {
            ExecutionState.SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.CANCEL_REQUESTED,
            ExecutionState.TIMED_OUT,
            # A retryable failure re-queues the *same* execution; the attempt
            # itself is recorded on the job, never overwritten here.
            ExecutionState.QUEUED,
        }
    ),
    ExecutionState.CANCEL_REQUESTED: frozenset(
        {
            ExecutionState.CANCELLED,
            # A cancellation can lose the race against completion. The real
            # outcome wins; the request stays visible in the audit trail.
            ExecutionState.SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.SUCCEEDED: frozenset(),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.TIMED_OUT: frozenset(),
}

#: Durable job lifecycle. Claiming, leasing, retry backoff, stale recovery and
#: cancellation are all explicit states rather than implicit side effects.
JOB_TRANSITIONS: Mapping[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.QUEUED: frozenset(
        {JobState.CLAIMED, JobState.CANCEL_REQUESTED, JobState.CANCELLED, JobState.DEAD_LETTER}
    ),
    JobState.CLAIMED: frozenset(
        {
            JobState.RUNNING,
            JobState.FAILED,
            JobState.RETRY_WAITING,
            JobState.STALE,
            JobState.CANCEL_REQUESTED,
            JobState.CANCELLING,
        }
    ),
    JobState.RUNNING: frozenset(
        {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.RETRY_WAITING,
            JobState.STALE,
            JobState.CANCEL_REQUESTED,
            JobState.CANCELLING,
        }
    ),
    JobState.RETRY_WAITING: frozenset(
        {JobState.QUEUED, JobState.CANCEL_REQUESTED, JobState.CANCELLED, JobState.DEAD_LETTER}
    ),
    #: A stale job is recovered back into the queue, or dead-lettered when its
    #: attempt budget is spent. It is never silently resurrected as "running".
    JobState.STALE: frozenset({JobState.QUEUED, JobState.DEAD_LETTER, JobState.CANCELLED}),
    JobState.CANCEL_REQUESTED: frozenset(
        {
            JobState.CANCELLING,
            JobState.CANCELLED,
            # The worker may finish before it observes the request.
            JobState.SUCCEEDED,
            JobState.FAILED,
        }
    ),
    JobState.CANCELLING: frozenset({JobState.CANCELLED, JobState.SUCCEEDED, JobState.FAILED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.CANCELLED: frozenset(),
    JobState.DEAD_LETTER: frozenset({JobState.QUEUED}),
}

#: A schedule is administratively enabled or disabled; archiving is terminal for
#: scheduling, and it never deletes the executions the schedule already produced.
SCHEDULE_TRANSITIONS: Mapping[ScheduleState, frozenset[ScheduleState]] = {
    ScheduleState.ENABLED: frozenset({ScheduleState.DISABLED, ScheduleState.ARCHIVED}),
    ScheduleState.DISABLED: frozenset({ScheduleState.ENABLED, ScheduleState.ARCHIVED}),
    ScheduleState.ARCHIVED: frozenset(),
}

#: The scientific subsystem's own run, mirrored locally for provenance. The
#: application only *records* what the adapter reports; it never invents a
#: scientific outcome.
SCIENTIFIC_EXECUTION_TRANSITIONS: Mapping[
    ScientificExecutionState, frozenset[ScientificExecutionState]
] = {
    ScientificExecutionState.SUBMITTED: frozenset(
        {
            ScientificExecutionState.ACCEPTED,
            ScientificExecutionState.REJECTED,
            ScientificExecutionState.FAILED,
            ScientificExecutionState.CANCELLED,
        }
    ),
    ScientificExecutionState.ACCEPTED: frozenset(
        {
            ScientificExecutionState.RUNNING,
            ScientificExecutionState.SUCCEEDED,
            ScientificExecutionState.FAILED,
            ScientificExecutionState.CANCELLED,
        }
    ),
    ScientificExecutionState.RUNNING: frozenset(
        {
            ScientificExecutionState.SUCCEEDED,
            ScientificExecutionState.FAILED,
            ScientificExecutionState.CANCELLED,
        }
    ),
    ScientificExecutionState.SUCCEEDED: frozenset(),
    ScientificExecutionState.FAILED: frozenset(),
    ScientificExecutionState.REJECTED: frozenset(),
    ScientificExecutionState.CANCELLED: frozenset(),
}

#: Administrative intent for a compute/worker node, separate from its observed
#: health: draining a node must not be expressible as "it became unhealthy".
NODE_LIFECYCLE_TRANSITIONS: Mapping[NodeLifecycleState, frozenset[NodeLifecycleState]] = {
    NodeLifecycleState.ACTIVE: frozenset(
        {
            NodeLifecycleState.DRAINING,
            NodeLifecycleState.MAINTENANCE,
            NodeLifecycleState.UNAVAILABLE,
        }
    ),
    NodeLifecycleState.DRAINING: frozenset(
        {
            NodeLifecycleState.ACTIVE,
            NodeLifecycleState.MAINTENANCE,
            NodeLifecycleState.UNAVAILABLE,
        }
    ),
    NodeLifecycleState.MAINTENANCE: frozenset(
        {NodeLifecycleState.ACTIVE, NodeLifecycleState.UNAVAILABLE}
    ),
    NodeLifecycleState.UNAVAILABLE: frozenset(
        {NodeLifecycleState.ACTIVE, NodeLifecycleState.MAINTENANCE}
    ),
}


# --------------------------------------------------------------------------- #
# Scientific result data layer (Package 6)                                    #
# --------------------------------------------------------------------------- #

#: A result set is the durable surface of one scientific execution's output. Its
#: *content* is immutable: nothing here allows an available result set to go back
#: to ``generating`` and be rewritten. Correction means a new result set, and the
#: old one becomes ``superseded`` — it is never edited and never deleted as part
#: of that move.
RESULT_SET_TRANSITIONS: Mapping[ResultSetState, frozenset[ResultSetState]] = {
    ResultSetState.PENDING: frozenset(
        {ResultSetState.GENERATING, ResultSetState.FAILED, ResultSetState.INVALIDATED}
    ),
    ResultSetState.GENERATING: frozenset(
        {ResultSetState.VALIDATED, ResultSetState.FAILED, ResultSetState.INVALIDATED}
    ),
    #: Structurally validated payload; materialization has not completed yet.
    ResultSetState.VALIDATED: frozenset(
        {ResultSetState.AVAILABLE, ResultSetState.FAILED, ResultSetState.INVALIDATED}
    ),
    ResultSetState.AVAILABLE: frozenset(
        {ResultSetState.SUPERSEDED, ResultSetState.INVALIDATED, ResultSetState.EXPIRED}
    ),
    #: A failed ingestion is terminal for *this* result set. Re-ingestion creates
    #: a new one, so a failure never turns into a success after the fact.
    ResultSetState.FAILED: frozenset(),
    ResultSetState.SUPERSEDED: frozenset({ResultSetState.EXPIRED}),
    ResultSetState.INVALIDATED: frozenset({ResultSetState.EXPIRED}),
    ResultSetState.EXPIRED: frozenset(),
}

#: One stored artifact of a result set. ``missing`` is reachable from every
#: non-terminal state because storage reconciliation may discover that the object
#: is gone; that is recorded as a fact rather than hidden.
RESULT_ARTIFACT_TRANSITIONS: Mapping[ResultArtifactState, frozenset[ResultArtifactState]] = {
    ResultArtifactState.REGISTERED: frozenset(
        {
            ResultArtifactState.VERIFYING,
            ResultArtifactState.REJECTED,
            ResultArtifactState.MISSING,
        }
    ),
    ResultArtifactState.VERIFYING: frozenset(
        {
            ResultArtifactState.ACCEPTED,
            ResultArtifactState.REJECTED,
            ResultArtifactState.MISSING,
        }
    ),
    ResultArtifactState.ACCEPTED: frozenset(
        {ResultArtifactState.SUPERSEDED, ResultArtifactState.MISSING}
    ),
    ResultArtifactState.REJECTED: frozenset(),
    ResultArtifactState.SUPERSEDED: frozenset({ResultArtifactState.MISSING}),
    ResultArtifactState.MISSING: frozenset({ResultArtifactState.VERIFYING}),
}

#: The ingestion *request*, separate from the result surface it produces.
RESULT_INGESTION_TRANSITIONS: Mapping[ResultIngestionState, frozenset[ResultIngestionState]] = {
    ResultIngestionState.RECEIVED: frozenset(
        {
            ResultIngestionState.VALIDATING,
            ResultIngestionState.REJECTED,
            ResultIngestionState.FAILED,
        }
    ),
    ResultIngestionState.VALIDATING: frozenset(
        {
            ResultIngestionState.VALIDATED,
            ResultIngestionState.REJECTED,
            ResultIngestionState.FAILED,
        }
    ),
    ResultIngestionState.VALIDATED: frozenset(
        {ResultIngestionState.MATERIALIZING, ResultIngestionState.FAILED}
    ),
    ResultIngestionState.MATERIALIZING: frozenset(
        {ResultIngestionState.ACCEPTED, ResultIngestionState.FAILED}
    ),
    ResultIngestionState.ACCEPTED: frozenset(),
    #: Rejected means "the payload did not satisfy the contract"; failed means
    #: "the platform could not complete the work". Never collapsed.
    ResultIngestionState.REJECTED: frozenset(),
    ResultIngestionState.FAILED: frozenset(),
}

#: Result-set states whose scientific content may be read and filtered.
READABLE_RESULT_SET_STATES: frozenset[ResultSetState] = frozenset(
    {ResultSetState.AVAILABLE, ResultSetState.SUPERSEDED}
)



#: States in which an execution still occupies scheduling capacity. Used by the
#: schedule concurrency policy and by administrative monitoring.
ACTIVE_EXECUTION_STATES: frozenset[ExecutionState] = frozenset(
    {
        ExecutionState.DRAFT,
        ExecutionState.VALIDATING,
        ExecutionState.VALIDATED,
        ExecutionState.REQUESTED,
        ExecutionState.QUEUED,
        ExecutionState.SUBMITTED,
        ExecutionState.RUNNING,
        ExecutionState.CANCEL_REQUESTED,
    }
)

TERMINAL_EXECUTION_STATES: frozenset[ExecutionState] = frozenset(
    {
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT,
    }
)

#: States in which a job is held by a worker and therefore needs a live lease.
LEASED_JOB_STATES: frozenset[JobState] = frozenset(
    {JobState.CLAIMED, JobState.RUNNING, JobState.CANCELLING}
)

TERMINAL_JOB_STATES: frozenset[JobState] = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.DEAD_LETTER}
)


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
    "analysis": ANALYSIS_TRANSITIONS,  # type: ignore[dict-item]
    "analysis_execution": ANALYSIS_EXECUTION_TRANSITIONS,  # type: ignore[dict-item]
    "job": JOB_TRANSITIONS,  # type: ignore[dict-item]
    "schedule": SCHEDULE_TRANSITIONS,  # type: ignore[dict-item]
    "scientific_execution": SCIENTIFIC_EXECUTION_TRANSITIONS,  # type: ignore[dict-item]
    "compute_node": NODE_LIFECYCLE_TRANSITIONS,  # type: ignore[dict-item]
    "result_set": RESULT_SET_TRANSITIONS,  # type: ignore[dict-item]
    "result_artifact": RESULT_ARTIFACT_TRANSITIONS,  # type: ignore[dict-item]
    "result_ingestion": RESULT_INGESTION_TRANSITIONS,  # type: ignore[dict-item]
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
    "ACTIVE_EXECUTION_STATES",
    "ANALYSIS_EXECUTION_TRANSITIONS",
    "ANALYSIS_TRANSITIONS",
    "DATASET_TRANSITIONS",
    "DATASET_VERSION_TRANSITIONS",
    "DELETION_TRANSITIONS",
    "EMAIL_VERIFICATION_TRANSITIONS",
    "FILE_UPLOAD_TRANSITIONS",
    "FILE_VALIDATION_TRANSITIONS",
    "IMPORT_SESSION_TRANSITIONS",
    "INVITATION_TRANSITIONS",
    "JOB_TRANSITIONS",
    "LEASED_JOB_STATES",
    "MALWARE_SCAN_TRANSITIONS",
    "MEMBERSHIP_TRANSITIONS",
    "NODE_LIFECYCLE_TRANSITIONS",
    "ORGANIZATION_TRANSITIONS",
    "PROJECT_TRANSITIONS",
    "READABLE_RESULT_SET_STATES",
    "RESULT_ARTIFACT_TRANSITIONS",
    "RESULT_INGESTION_TRANSITIONS",
    "RESULT_SET_TRANSITIONS",
    "SCHEDULE_TRANSITIONS",
    "SCIENTIFIC_EXECUTION_TRANSITIONS",
    "TERMINAL_EXECUTION_STATES",
    "TERMINAL_JOB_STATES",
    "UPLOAD_SESSION_TRANSITIONS",
    "VALIDATION_RUN_TRANSITIONS",
    "can_transition",
    "require_transition",
    "transition_targets",
]
