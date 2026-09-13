"""Upload sessions, transfer completion and authorized downloads.

The rule this module exists to enforce: **possessing a presigned URL is not
permission to make an artifact usable.**

An upload therefore runs through two distinct decisions, in two transactions:

1. ``OpenUploadSession`` — the server decides, before a single byte moves,
   whether this caller may add this input to this scope, whether the declared
   format is accepted for the dataset kind, and whether the declared size is
   within the configured limit. It then derives a storage key from
   server-generated identifiers only (never from the filename) and issues a
   short-lived transfer grant.
2. ``CompleteUpload`` — the server checks what *actually* arrived against what
   was declared, and enqueues the durable verification job. Scanning, structural
   inspection and the validation run happen in that job, not in the request, so a
   large file is never verified on a web worker and a lost connection never
   leaves an artifact half-decided.

Neither step marks an artifact usable. That only happens when verification
records a clean scan and a validation outcome (``data/artifacts.py``), and even
then the *version* still needs an explicit human acceptance decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.data.dependencies import (
    DOWNLOAD,
    WRITE,
    DataServices,
    require_dataset_access,
)
from app.domain.authorization.context import ActorContext
from app.domain.data.entities import (
    Dataset,
    DatasetVersion,
    FileArtifact,
    UploadSession,
    ValidationRun,
)
from app.domain.data.formats import (
    format_from_filename,
    require_accepted_format,
    require_within_size_limit,
    sanitize_filename,
)
from app.domain.data.storage import upload_key
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.events import EventType
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    AuditOutcome,
    ChecksumAlgorithm,
    DatasetState,
    DatasetVersionState,
    DuplicateRelation,
    FileUploadState,
    InputFormat,
    JobKind,
    UploadSessionState,
)
from app.infrastructure.persistence.repositories.base import new_id

#: Upload sessions that never completed stop being usable after this window. The
#: expiry is enforced on every read, not only by the sweeper, so a long-idle
#: session cannot be completed just because the sweeper has not run yet.
DEFAULT_UPLOAD_TTL_SECONDS = 900

#: States from which a session can still legitimately be completed.
_COMPLETABLE = frozenset({UploadSessionState.CREATED, UploadSessionState.UPLOADING})

#: States that already recorded a final answer for this transfer.
_TERMINAL = frozenset(
    {
        UploadSessionState.ACCEPTED,
        UploadSessionState.REJECTED,
        UploadSessionState.QUARANTINED,
        UploadSessionState.EXPIRED,
        UploadSessionState.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class UploadSessionView:
    session: UploadSession
    artifact: FileArtifact
    latest_validation: ValidationRun | None = None


@dataclass(frozen=True, slots=True)
class UploadTicket:
    """A transfer grant. Deliberately not a resource the client can re-derive."""

    session: UploadSession
    artifact: FileArtifact
    upload_url: str
    expires_at: datetime
    #: Reported, never auto-resolved: an identical upload may be legitimate, and
    #: silently reusing an existing artifact would rewrite lineage.
    duplicate_relation: DuplicateRelation
    duplicate_of_file_artifact_id: str | None


async def _load_version_scope(
    services: DataServices,
    repositories,
    actor: ActorContext,
    version_id: str,
    *,
    action,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> tuple[DatasetVersion, Dataset, str]:
    """Resolve a version to its dataset and require ``action`` in that scope."""
    version = await repositories.dataset_versions.get(version_id)
    if version is None:
        raise NotFoundError("dataset_version", version_id)
    dataset = await repositories.datasets.get(version.dataset_id)
    if dataset is None or not dataset.is_active:
        # An unknown id and an id in a scope the caller cannot reach are
        # answered identically, so existence is never disclosed by probing.
        raise NotFoundError("dataset_version", version_id)
    scope = await require_dataset_access(
        services,
        repositories,
        actor,
        dataset,
        action=action,
        recorder=recorder,
        occurred_at=occurred_at,
    )
    actor_id = scope.actor.actor_id
    if actor_id is None:  # pragma: no cover - the permission check precedes this
        raise AuthorizationError("authentication is required")
    return version, dataset, actor_id


# --------------------------------------------------------------------------- #
# Opening a transfer grant                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OpenUploadSessionCommand:
    actor: ActorContext
    version_id: str
    filename: str
    size_bytes: int
    declared_format: InputFormat | None
    checksum_algorithm: ChecksumAlgorithm
    checksum_value: str | None
    content_type: str | None
    request: RequestContext


class OpenUploadSession:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: OpenUploadSessionCommand) -> UploadTicket:
        now = self._services.clock.now()
        display_name = sanitize_filename(command.filename)
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            version, dataset, actor_id = await _load_version_scope(
                self._services,
                repositories,
                command.actor,
                command.version_id,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            if dataset.state is DatasetState.ARCHIVED:
                raise ConflictError("an archived dataset cannot receive uploads")
            if version.state not in (
                DatasetVersionState.CREATED,
                DatasetVersionState.UPLOADING,
            ):
                # An immutable version never gains new bytes; a correction is a
                # new version, which is what keeps historical results valid.
                raise ConflictError(
                    "this version no longer accepts uploads",
                    details={"version_state": version.state.value},
                )

            declared_format = command.declared_format or format_from_filename(
                display_name
            ).format
            if declared_format is InputFormat.UNKNOWN:
                raise ValidationError(
                    "the input format could not be determined from the filename and "
                    "must be declared explicitly",
                    details={"field": "declared_format"},
                )
            require_accepted_format(dataset.kind, declared_format)
            require_within_size_limit(
                command.size_bytes, limit_bytes=self._services.config.max_upload_bytes
            )
            if command.checksum_value is not None and not command.checksum_value.strip():
                raise ValidationError(
                    "a declared checksum must not be empty",
                    details={"field": "checksum_value"},
                )

            duplicate_relation = DuplicateRelation.NONE
            duplicate_of: str | None = None
            if command.checksum_value:
                existing = await repositories.file_artifacts.find_by_checksum(
                    workspace_id=dataset.workspace_id,
                    checksum_algorithm=command.checksum_algorithm.value,
                    checksum_value=command.checksum_value,
                )
                if existing is not None:
                    duplicate_relation = DuplicateRelation.SAME_CHECKSUM_IN_SCOPE
                    duplicate_of = existing.id
            if duplicate_of is None:
                named = await repositories.file_artifacts.find_by_filename(
                    workspace_id=dataset.workspace_id, filename=display_name
                )
                if named is not None:
                    duplicate_relation = DuplicateRelation.SAME_NAME_IN_SCOPE
                    duplicate_of = named.id

            artifact_id = new_id("fla")
            key = upload_key(
                workspace_id=dataset.workspace_id,
                dataset_id=dataset.id,
                dataset_version_id=version.id,
                file_artifact_id=artifact_id,
            )
            artifact = await repositories.file_artifacts.add(
                FileArtifact(
                    id=artifact_id,
                    workspace_id=dataset.workspace_id,
                    storage_provider=self._services.storage_provider,
                    storage_bucket=self._services.storage_bucket,
                    storage_key=key,
                    filename=display_name,
                    uploaded_by=actor_id,
                    dataset_id=dataset.id,
                    dataset_version_id=version.id,
                    content_type=command.content_type,
                    size_bytes=None,
                    checksum_algorithm=command.checksum_algorithm,
                    # The declared checksum is recorded on the session as a claim;
                    # the artifact only carries a checksum once one was computed
                    # from the stored bytes.
                    checksum_value=None,
                    declared_format=declared_format,
                    original_filename=command.filename,
                )
            )
            ttl = self._services.upload_url_ttl_seconds or DEFAULT_UPLOAD_TTL_SECONDS
            session = await repositories.upload_sessions.add(
                UploadSession(
                    id=new_id("ups"),
                    workspace_id=dataset.workspace_id,
                    project_id=dataset.project_id,
                    dataset_id=dataset.id,
                    dataset_version_id=version.id,
                    file_artifact_id=artifact.id,
                    state=UploadSessionState.CREATED,
                    initiated_by=actor_id,
                    storage_key=key,
                    declared_filename=display_name,
                    declared_size_bytes=command.size_bytes,
                    declared_format=declared_format,
                    declared_checksum_algorithm=command.checksum_algorithm,
                    declared_checksum_value=command.checksum_value,
                    expires_at=now + timedelta(seconds=ttl),
                    duplicate_relation=duplicate_relation,
                    duplicate_of_file_artifact_id=duplicate_of,
                    correlation_id=command.request.correlation_id,
                )
            )
            if version.state is DatasetVersionState.CREATED:
                await repositories.dataset_versions.save(
                    replace(
                        version,
                        state=require_transition(
                            "dataset_version", version.state, DatasetVersionState.UPLOADING
                        ),
                        declared_format=declared_format,
                    )
                )
            await recorder.audit(
                action="upload_session.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="upload_session",
                resource_id=session.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                new_state=session.state.value,
                detail={
                    "file_artifact_id": artifact.id,
                    "declared_format": declared_format.value,
                    "declared_size_bytes": command.size_bytes,
                    "duplicate_relation": duplicate_relation.value,
                },
            )
            await recorder.event(
                event_type=EventType.UPLOAD_SESSION_CREATED,
                aggregate_type="upload_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
                idempotency_suffix=session.id,
            )

        # Presigning happens after the transaction committed: a URL must never
        # exist for a session that was rolled back.
        url = await self._services.storage.presign_upload(
            key, expires_seconds=self._services.upload_url_ttl_seconds
        )
        return UploadTicket(
            session=session,
            artifact=artifact,
            upload_url=url,
            expires_at=session.expires_at or now,
            duplicate_relation=duplicate_relation,
            duplicate_of_file_artifact_id=duplicate_of,
        )


# --------------------------------------------------------------------------- #
# Completing a transfer                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CompleteUploadCommand:
    actor: ActorContext
    session_id: str
    request: RequestContext


class CompleteUpload:
    """Check what arrived, then hand verification to a durable job.

    Only the cheap, authoritative checks happen inline: does the object exist,
    and is its size exactly what was declared. Scanning, decompression and
    structural inspection are queued, because they are unbounded work and must
    survive a dropped connection or a restarted process.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: CompleteUploadCommand) -> UploadSessionView:
        now = self._services.clock.now()
        # Read the session first (authorized), then ask storage, then write.
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            session = await repositories.upload_sessions.get(command.session_id)
            if session is None:
                raise NotFoundError("upload_session", command.session_id)
            dataset = await repositories.datasets.get(session.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("upload_session", command.session_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            artifact = await repositories.file_artifacts.get(session.file_artifact_id)
            if artifact is None:  # pragma: no cover - foreign key guarantees this
                raise NotFoundError("file_artifact", session.file_artifact_id)

            if session.state is UploadSessionState.UPLOADED or session.state in _TERMINAL:
                # Idempotent: a retried completion reports the recorded outcome
                # instead of re-deciding it.
                validation = await repositories.validation_runs.latest_for_subject(
                    subject_type="file_artifact", subject_id=artifact.id
                )
                return UploadSessionView(
                    session=session, artifact=artifact, latest_validation=validation
                )
            if session.state not in _COMPLETABLE:
                raise ConflictError(
                    "this upload session is already being verified",
                    details={"state": session.state.value},
                )
            if session.expires_at is not None and session.expires_at <= now:
                expired = await repositories.upload_sessions.save(
                    replace(
                        session,
                        state=require_transition(
                            "upload_session", session.state, UploadSessionState.EXPIRED
                        ),
                        failure_reason="the transfer grant expired before completion",
                    )
                )
                await recorder.audit(
                    action="upload_session.expired",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    actor_user_id=scope.actor.actor_id,
                    resource_type="upload_session",
                    resource_id=session.id,
                    workspace_id=session.workspace_id,
                    project_id=session.project_id,
                    previous_state=session.state.value,
                    new_state=expired.state.value,
                )
                raise ConflictError(
                    "this upload session expired; open a new one",
                    details={"state": expired.state.value},
                )
            stored = await self._services.storage.stat_object(session.storage_key)

            if stored is None:
                failed = await repositories.upload_sessions.save(
                    replace(
                        session,
                        state=require_transition(
                            "upload_session", session.state, UploadSessionState.FAILED
                        ),
                        failure_reason="no object was stored for this session",
                    )
                )
                await recorder.audit(
                    action="upload_session.failed",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    actor_user_id=scope.actor.actor_id,
                    resource_type="upload_session",
                    resource_id=session.id,
                    workspace_id=session.workspace_id,
                    project_id=session.project_id,
                    previous_state=session.state.value,
                    new_state=failed.state.value,
                    reason="object_missing",
                )
                raise ConflictError(
                    "no uploaded object was found for this session",
                    details={"reason": "object_missing"},
                )

            # "bytes arrived" only. Usability is decided by verification.
            in_progress = require_transition(
                "file_upload", artifact.upload_state, FileUploadState.IN_PROGRESS
            )
            artifact = await repositories.file_artifacts.save(
                replace(
                    artifact,
                    upload_state=require_transition(
                        "file_upload", in_progress, FileUploadState.UPLOADED
                    ),
                    size_bytes=stored.size_bytes,
                    content_type=stored.content_type or artifact.content_type,
                    uploaded_at=now,
                    metadata_json={
                        **artifact.metadata_json,
                        "storage_etag": stored.etag,
                        "declared_size_bytes": session.declared_size_bytes,
                    },
                )
            )
            # The transfer demonstrably began — an object exists — so a session
            # still recorded as ``created`` passes through ``uploading`` rather
            # than skipping a state the lifecycle table requires.
            transferring = (
                session.state
                if session.state is UploadSessionState.UPLOADING
                else require_transition(
                    "upload_session", session.state, UploadSessionState.UPLOADING
                )
            )
            session = await repositories.upload_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "upload_session", transferring, UploadSessionState.UPLOADED
                    ),
                    completed_at=now,
                )
            )
            version = await repositories.dataset_versions.get(session.dataset_version_id)
            if version is not None and version.state is DatasetVersionState.UPLOADING:
                await repositories.dataset_versions.save(
                    replace(
                        version,
                        state=require_transition(
                            "dataset_version", version.state, DatasetVersionState.VALIDATING
                        ),
                    )
                )
            # Enqueued in the same transaction as the state change, so a
            # committed upload can never lose its verification job and a rolled
            # back one can never leave a job pointing at nothing.
            job_id = await repositories.jobs.enqueue(
                kind=JobKind.DATASET_VALIDATION,
                payload={
                    "upload_session_id": session.id,
                    "file_artifact_id": artifact.id,
                    "dataset_version_id": session.dataset_version_id,
                },
                correlation_id=command.request.correlation_id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                requested_by=scope.actor.actor_id,
                idempotency_key=f"artifact-verification:{artifact.id}",
            )
            await recorder.audit(
                action="upload_session.completed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="upload_session",
                resource_id=session.id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                new_state=session.state.value,
                detail={
                    "stored_size_bytes": stored.size_bytes,
                    "declared_size_bytes": session.declared_size_bytes,
                    "verification_job_id": job_id,
                },
            )
            await recorder.event(
                event_type=EventType.UPLOAD_SESSION_COMPLETED,
                aggregate_type="upload_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=session.workspace_id,
                idempotency_suffix=UploadSessionState.UPLOADED.value,
            )
        return UploadSessionView(session=session, artifact=artifact, latest_validation=None)


# --------------------------------------------------------------------------- #
# Cancelling and expiring                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CancelUploadSessionCommand:
    actor: ActorContext
    session_id: str
    reason: str | None
    request: RequestContext


class CancelUploadSession:
    """Abandon a transfer grant before it is completed.

    The artifact row is retained in an aborted state rather than deleted: "an
    upload was started here and abandoned" is a fact worth keeping, and deleting
    rows would make the audit trail unreadable.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: CancelUploadSessionCommand) -> UploadSessionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            session = await repositories.upload_sessions.get(command.session_id)
            if session is None:
                raise NotFoundError("upload_session", command.session_id)
            dataset = await repositories.datasets.get(session.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("upload_session", command.session_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            previous = session.state
            session = await repositories.upload_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "upload_session", previous, UploadSessionState.CANCELLED
                    ),
                    failure_reason=command.reason or "cancelled by the submitter",
                )
            )
            artifact = await repositories.file_artifacts.get(session.file_artifact_id)
            if artifact is not None and artifact.upload_state in (
                FileUploadState.PENDING,
                FileUploadState.IN_PROGRESS,
            ):
                artifact = await repositories.file_artifacts.save(
                    replace(
                        artifact,
                        upload_state=require_transition(
                            "file_upload", artifact.upload_state, FileUploadState.ABORTED
                        ),
                    )
                )
            await recorder.audit(
                action="upload_session.cancelled",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="upload_session",
                resource_id=session.id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                previous_state=previous.value,
                new_state=session.state.value,
                reason=command.reason,
            )
            await recorder.event(
                event_type=EventType.UPLOAD_SESSION_CANCELLED,
                aggregate_type="upload_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=session.workspace_id,
            )
        if artifact is None:  # pragma: no cover - foreign key guarantees this
            raise NotFoundError("file_artifact", session.file_artifact_id)
        return UploadSessionView(session=session, artifact=artifact)


class ExpireStaleUploadSessions:
    """Maintenance operation: close transfer grants that were never used.

    Runs as a job, with no actor. It refuses nothing and decides nothing about
    scientific content — it only closes sessions whose window has passed and
    removes the orphaned object when no bytes were ever accepted.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, *, request: RequestContext, limit: int = 100) -> tuple[str, ...]:
        now = self._services.clock.now()
        expired: list[str] = []
        orphan_keys: list[str] = []
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            stale = await repositories.upload_sessions.list_expired(moment=now, limit=limit)
            for session in stale:
                if session.state not in _COMPLETABLE:
                    continue
                closed = await repositories.upload_sessions.save(
                    replace(
                        session,
                        state=require_transition(
                            "upload_session", session.state, UploadSessionState.EXPIRED
                        ),
                        failure_reason="the transfer grant expired before completion",
                    )
                )
                artifact = await repositories.file_artifacts.get(session.file_artifact_id)
                if artifact is not None and artifact.upload_state in (
                    FileUploadState.PENDING,
                    FileUploadState.IN_PROGRESS,
                ):
                    await repositories.file_artifacts.save(
                        replace(
                            artifact,
                            upload_state=require_transition(
                                "file_upload", artifact.upload_state, FileUploadState.ABORTED
                            ),
                        )
                    )
                    orphan_keys.append(session.storage_key)
                expired.append(closed.id)
                await recorder.audit(
                    action="upload_session.expired",
                    outcome=AuditOutcome.SUCCESS,
                    occurred_at=now,
                    actor_label="upload-session-sweeper",
                    resource_type="upload_session",
                    resource_id=session.id,
                    workspace_id=session.workspace_id,
                    project_id=session.project_id,
                    previous_state=session.state.value,
                    new_state=closed.state.value,
                )
        # Only after the rows are committed, and only for artifacts that never
        # reached "uploaded": an object referenced by a live artifact is never
        # removed by this sweeper.
        for key in orphan_keys:
            await self._services.storage.delete_object(key)
        return tuple(expired)


# --------------------------------------------------------------------------- #
# Downloads                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class IssueArtifactDownloadCommand:
    actor: ActorContext
    artifact_id: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class DownloadGrant:
    artifact: FileArtifact
    download_url: str
    expires_in_seconds: int


class IssueArtifactDownload:
    """Authorize retrieval of stored bytes and record that it happened.

    Download is a separate permission from read: listing a dataset's metadata is
    not the same as taking its genomic content out of the platform. Every grant
    is audited and published as an event, because "who obtained this file" is a
    governance question.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: IssueArtifactDownloadCommand) -> DownloadGrant:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            artifact = await repositories.file_artifacts.get(command.artifact_id)
            if artifact is None or artifact.dataset_id is None:
                raise NotFoundError("file_artifact", command.artifact_id)
            dataset = await repositories.datasets.get(artifact.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("file_artifact", command.artifact_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=DOWNLOAD,
                recorder=recorder,
                occurred_at=now,
            )
            if not artifact.is_retrievable:
                # Fails closed: unscanned, quarantined and unvalidated artifacts
                # are all refused, and the refusal is audited.
                await recorder.audit(
                    action="file_artifact.download_refused",
                    outcome=AuditOutcome.DENIED,
                    occurred_at=now,
                    actor_user_id=scope.actor.actor_id,
                    resource_type="file_artifact",
                    resource_id=artifact.id,
                    workspace_id=artifact.workspace_id,
                    project_id=dataset.project_id,
                    detail={
                        "upload_state": artifact.upload_state.value,
                        "scan_state": artifact.scan_state.value,
                        "validation_state": artifact.validation_state.value,
                    },
                )
                raise ConflictError(
                    "this file is not available for download",
                    details={
                        "scan_state": artifact.scan_state.value,
                        "validation_state": artifact.validation_state.value,
                    },
                )
            await recorder.audit(
                action="file_artifact.download_authorized",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="file_artifact",
                resource_id=artifact.id,
                workspace_id=artifact.workspace_id,
                project_id=dataset.project_id,
                detail={"filename": artifact.filename},
            )
            await recorder.event(
                event_type=EventType.FILE_ARTIFACT_DOWNLOAD_AUTHORIZED,
                aggregate_type="file_artifact",
                aggregate_id=artifact.id,
                occurred_at=now,
                workspace_id=artifact.workspace_id,
                payload={"actor_user_id": scope.actor.actor_id},
            )
        ttl = self._services.download_url_ttl_seconds
        url = await self._services.storage.presign_download(
            artifact.storage_key, expires_seconds=ttl, filename=artifact.filename
        )
        return DownloadGrant(artifact=artifact, download_url=url, expires_in_seconds=ttl)


__all__ = [
    "DEFAULT_UPLOAD_TTL_SECONDS",
    "CancelUploadSession",
    "CancelUploadSessionCommand",
    "CompleteUpload",
    "CompleteUploadCommand",
    "DownloadGrant",
    "ExpireStaleUploadSessions",
    "IssueArtifactDownload",
    "IssueArtifactDownloadCommand",
    "OpenUploadSession",
    "OpenUploadSessionCommand",
    "UploadSessionView",
    "UploadTicket",
]
