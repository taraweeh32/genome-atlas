"""In-memory implementations of the dataset/upload/import/validation ports.

Same intent as ``tests/support/memory.py``: the repository ports are protocols,
so the real use cases — authorization, lifecycle gates, immutability rules,
duplicate detection, optimistic concurrency — can be exercised without
PostgreSQL. These doubles are for persistence only, never a replacement for the
integration tests that run the SQLAlchemy repositories against a live database.

Two behaviours are modelled faithfully because tests depend on them:

* a save whose version does not match the stored version raises
  ``ConcurrencyConflictError``, exactly as the SQL repositories do;
* ``jobs.enqueue`` records the job and returns an identifier without executing
  anything, so a test can assert that work was *scheduled* durably rather than
  performed inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.application.repositories import Page, Paged
from app.domain.data.entities import (
    ColumnMapping,
    Dataset,
    DatasetVersion,
    FileArtifact,
    ImportSession,
    UploadSession,
    ValidationIssue,
    ValidationRun,
)
from app.domain.errors import ConcurrencyConflictError
from app.domain.value_objects.enums import (
    DatasetState,
    DeletionState,
    JobKind,
    UploadSessionState,
)


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


def _bump(entity: Any, stored: Any, label: str) -> Any:
    if entity.version != stored.version:
        raise ConcurrencyConflictError(f"{label} {entity.id} was modified concurrently")
    return replace(entity, version=entity.version + 1)


@dataclass
class MemoryDatasets:
    rows: dict[str, Dataset] = field(default_factory=dict)

    async def add(self, dataset: Dataset) -> Dataset:
        self.rows[dataset.id] = dataset
        return dataset

    async def get(self, dataset_id: str) -> Dataset | None:
        return self.rows.get(dataset_id)

    async def save(self, dataset: Dataset) -> Dataset:
        updated = _bump(dataset, self.rows[dataset.id], "dataset")
        self.rows[dataset.id] = updated
        return updated

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[DatasetState, ...] = (),
        query: str | None = None,
        include_archived: bool = False,
    ) -> Paged[Dataset]:
        items = [
            dataset
            for dataset in self.rows.values()
            # Tenant isolation is a filter on the *resource's own* scope: a
            # dataset outside the caller's readable workspaces is never listed.
            if dataset.workspace_id in workspace_ids
            and dataset.deletion_state is DeletionState.ACTIVE
        ]
        if project_id is not None:
            items = [d for d in items if d.project_id == project_id]
        if states:
            items = [d for d in items if d.state in states]
        if not include_archived:
            items = [d for d in items if d.state is not DatasetState.ARCHIVED]
        if query:
            needle = query.strip().lower()
            items = [d for d in items if needle in d.name.lower()]
        return _paged(sorted(items, key=lambda d: d.name.lower()), page)

    async def name_exists(
        self, *, workspace_id: str, project_id: str | None, name: str
    ) -> bool:
        return any(
            d.workspace_id == workspace_id
            and d.project_id == project_id
            and d.name.strip().lower() == name.strip().lower()
            and d.deletion_state is DeletionState.ACTIVE
            for d in self.rows.values()
        )


@dataclass
class MemoryDatasetVersions:
    rows: dict[str, DatasetVersion] = field(default_factory=dict)

    async def add(self, version: DatasetVersion) -> DatasetVersion:
        self.rows[version.id] = version
        return version

    async def get(self, version_id: str) -> DatasetVersion | None:
        return self.rows.get(version_id)

    async def save(self, version: DatasetVersion) -> DatasetVersion:
        self.rows[version.id] = version
        return version

    async def list_for_dataset(
        self, dataset_id: str, *, page: Page
    ) -> Paged[DatasetVersion]:
        items = [v for v in self.rows.values() if v.dataset_id == dataset_id]
        return _paged(sorted(items, key=lambda v: -v.version_number), page)

    async def next_version_number(self, dataset_id: str) -> int:
        existing = [v.version_number for v in self.rows.values() if v.dataset_id == dataset_id]
        return max(existing, default=0) + 1

    async def list_accepted(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        from app.domain.value_objects.enums import DatasetVersionState

        items = [
            v
            for v in self.rows.values()
            if v.dataset_id == dataset_id and v.state is DatasetVersionState.ACCEPTED
        ]
        return tuple(sorted(items, key=lambda v: v.version_number))


@dataclass
class MemoryFileArtifacts:
    rows: dict[str, FileArtifact] = field(default_factory=dict)

    async def add(self, artifact: FileArtifact) -> FileArtifact:
        self.rows[artifact.id] = artifact
        return artifact

    async def get(self, artifact_id: str) -> FileArtifact | None:
        return self.rows.get(artifact_id)

    async def save(self, artifact: FileArtifact) -> FileArtifact:
        updated = _bump(artifact, self.rows[artifact.id], "file artifact")
        self.rows[artifact.id] = updated
        return updated

    async def list_for_version(self, version_id: str) -> tuple[FileArtifact, ...]:
        items = [a for a in self.rows.values() if a.dataset_version_id == version_id]
        return tuple(sorted(items, key=lambda a: a.filename))

    async def find_by_checksum(
        self, *, workspace_id: str, checksum_algorithm: str, checksum_value: str
    ) -> FileArtifact | None:
        for artifact in self.rows.values():
            if (
                artifact.workspace_id == workspace_id
                and artifact.checksum_algorithm.value == checksum_algorithm
                and artifact.checksum_value == checksum_value
                and artifact.deletion_state is DeletionState.ACTIVE
            ):
                return artifact
        return None

    async def find_by_filename(
        self, *, workspace_id: str, filename: str
    ) -> FileArtifact | None:
        for artifact in self.rows.values():
            if (
                artifact.workspace_id == workspace_id
                and artifact.filename == filename
                and artifact.deletion_state is DeletionState.ACTIVE
            ):
                return artifact
        return None


@dataclass
class MemoryUploadSessions:
    rows: dict[str, UploadSession] = field(default_factory=dict)

    async def add(self, session: UploadSession) -> UploadSession:
        self.rows[session.id] = session
        return session

    async def get(self, session_id: str) -> UploadSession | None:
        return self.rows.get(session_id)

    async def save(self, session: UploadSession) -> UploadSession:
        updated = _bump(session, self.rows[session.id], "upload session")
        self.rows[session.id] = updated
        return updated

    async def get_for_artifact(self, artifact_id: str) -> UploadSession | None:
        for session in self.rows.values():
            if session.file_artifact_id == artifact_id:
                return session
        return None

    async def list_for_version(self, version_id: str) -> tuple[UploadSession, ...]:
        return tuple(s for s in self.rows.values() if s.dataset_version_id == version_id)

    async def list_expired(
        self, *, moment: datetime, limit: int = 100
    ) -> tuple[UploadSession, ...]:
        items = [
            s
            for s in self.rows.values()
            if s.expires_at is not None
            and s.expires_at <= moment
            and s.state in (UploadSessionState.CREATED, UploadSessionState.UPLOADING)
        ]
        return tuple(sorted(items, key=lambda s: s.id)[:limit])


@dataclass
class MemoryImportSessions:
    rows: dict[str, ImportSession] = field(default_factory=dict)

    async def add(self, session: ImportSession) -> ImportSession:
        self.rows[session.id] = session
        return session

    async def get(self, session_id: str) -> ImportSession | None:
        return self.rows.get(session_id)

    async def save(self, session: ImportSession) -> ImportSession:
        updated = _bump(session, self.rows[session.id], "import session")
        self.rows[session.id] = updated
        return updated

    async def get_by_idempotency_key(self, key: str) -> ImportSession | None:
        for session in self.rows.values():
            if session.idempotency_key == key:
                return session
        return None

    async def list_for_dataset(
        self, dataset_id: str, *, page: Page
    ) -> Paged[ImportSession]:
        items = [s for s in self.rows.values() if s.dataset_id == dataset_id]
        return _paged(sorted(items, key=lambda s: s.id), page)


@dataclass
class MemoryColumnMappings:
    rows: dict[str, tuple[ColumnMapping, ...]] = field(default_factory=dict)

    async def replace_all(
        self, import_session_id: str, mappings: tuple[ColumnMapping, ...]
    ) -> tuple[ColumnMapping, ...]:
        self.rows[import_session_id] = mappings
        return mappings

    async def list_for_session(self, import_session_id: str) -> tuple[ColumnMapping, ...]:
        return self.rows.get(import_session_id, ())


@dataclass
class MemoryValidationRuns:
    rows: dict[str, ValidationRun] = field(default_factory=dict)
    #: Insertion order stands in for created_at ordering.
    order: list[str] = field(default_factory=list)

    async def add(self, run: ValidationRun) -> ValidationRun:
        self.rows[run.id] = run
        self.order.append(run.id)
        return run

    async def get(self, run_id: str) -> ValidationRun | None:
        return self.rows.get(run_id)

    async def save(self, run: ValidationRun) -> ValidationRun:
        self.rows[run.id] = run
        return run

    def _for_subject(self, subject_type: str, subject_id: str) -> list[ValidationRun]:
        attribute = {
            "file_artifact": "file_artifact_id",
            "dataset_version": "dataset_version_id",
            "import_session": "import_session_id",
        }[subject_type]
        return [
            self.rows[run_id]
            for run_id in self.order
            if getattr(self.rows[run_id], attribute) == subject_id
        ]

    async def list_for_subject(
        self, *, subject_type: str, subject_id: str, page: Page
    ) -> Paged[ValidationRun]:
        items = list(reversed(self._for_subject(subject_type, subject_id)))
        return _paged(items, page)

    async def latest_for_subject(
        self, *, subject_type: str, subject_id: str
    ) -> ValidationRun | None:
        items = self._for_subject(subject_type, subject_id)
        return items[-1] if items else None


@dataclass
class MemoryValidationIssues:
    rows: list[ValidationIssue] = field(default_factory=list)

    async def add_many(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.rows.extend(issues)

    async def list_for_run(self, run_id: str, *, page: Page) -> Paged[ValidationIssue]:
        items = [issue for issue in self.rows if issue.validation_run_id == run_id]
        return _paged(items, page)


@dataclass
class RecordedJob:
    kind: JobKind
    payload: dict[str, Any]
    correlation_id: str
    queue: str
    priority: int
    workspace_id: str | None
    project_id: str | None
    requested_by: str | None
    idempotency_key: str | None
    available_at: datetime | None
    max_attempts: int


@dataclass
class MemoryJobs:
    """Records enqueued work without executing it.

    Package 4 must not execute jobs inline; that would turn a durable,
    observable, retryable step into an invisible part of a request. Tests assert
    the enqueue happened, and drive the handler explicitly.
    """

    recorded: list[RecordedJob] = field(default_factory=list)

    async def enqueue(
        self,
        *,
        kind: JobKind,
        payload: dict[str, Any],
        correlation_id: str,
        queue: str = "default",
        priority: int = 100,
        workspace_id: str | None = None,
        project_id: str | None = None,
        requested_by: str | None = None,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> str:
        if idempotency_key is not None:
            for index, job in enumerate(self.recorded):
                if job.idempotency_key == idempotency_key:
                    return f"job_{index + 1:032x}"
        self.recorded.append(
            RecordedJob(
                kind=kind,
                payload=dict(payload),
                correlation_id=correlation_id,
                queue=queue,
                priority=priority,
                workspace_id=workspace_id,
                project_id=project_id,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                available_at=available_at,
                max_attempts=max_attempts,
            )
        )
        return f"job_{len(self.recorded):032x}"

    async def get(self, job_id: str) -> dict[str, Any] | None:
        return None

    def of_kind(self, kind: JobKind) -> tuple[RecordedJob, ...]:
        return tuple(job for job in self.recorded if job.kind is kind)


__all__ = [
    "MemoryColumnMappings",
    "MemoryDatasetVersions",
    "MemoryDatasets",
    "MemoryFileArtifacts",
    "MemoryImportSessions",
    "MemoryJobs",
    "MemoryUploadSessions",
    "MemoryValidationIssues",
    "MemoryValidationRuns",
    "RecordedJob",
]
