"""Dataset, dataset-version, file-artifact and upload-session repositories.

Two conventions from the identity/tenancy repositories carry over unchanged:

* Reads are scope-explicit. ``list_for_scope`` takes the workspace identifiers
  the caller has already been authorized for; an empty scope returns nothing
  rather than everything, so a missing authorization check cannot leak rows.
* Mutable rows are saved under the version that was read, so a concurrent edit
  raises ``ConcurrencyConflictError`` instead of silently winning.

Immutable rows (dataset versions past acceptance) are still written through
``save``; refusing an illegal transition is the domain's job, and the lifecycle
map enforces it before a repository is ever reached.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select

from app.application.repositories import Page, Paged
from app.domain.data.entities import Dataset, DatasetVersion, FileArtifact, UploadSession
from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    CompressionKind,
    DatasetKind,
    DatasetState,
    DatasetVersionState,
    DeletionState,
    DuplicateRelation,
    FileUploadState,
    FileValidationState,
    InputFormat,
    MalwareScanState,
    ReferenceBuildDeclaration,
    UploadSessionState,
)
from app.infrastructure.persistence.models.dataset import Dataset as DatasetModel
from app.infrastructure.persistence.models.dataset import DatasetVersion as DatasetVersionModel
from app.infrastructure.persistence.models.dataset import FileArtifact as FileArtifactModel
from app.infrastructure.persistence.models.uploads import UploadSession as UploadSessionModel
from app.infrastructure.persistence.repositories.base import SqlRepository

_DATASETS = DatasetModel.__table__
_VERSIONS = DatasetVersionModel.__table__
_ARTIFACTS = FileArtifactModel.__table__
_UPLOADS = UploadSessionModel.__table__


def to_dataset(row: Mapping[str, Any]) -> Dataset:
    return Dataset(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        name=row["name"],
        kind=DatasetKind(row["kind"]),
        state=DatasetState(row["state"]),
        created_by=row["created_by"],
        owner_user_id=row["owner_user_id"],
        description=row["description"],
        current_version_id=row["current_version_id"],
        reference_build_declared=ReferenceBuildDeclaration(row["reference_build_declared"]),
        source_metadata=row["source_metadata"] or {},
        scientific_metadata=row["scientific_metadata"] or {},
        deletion_state=DeletionState(row["deletion_state"]),
        deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"],
        retention_expires_at=row["retention_expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


def to_dataset_version(row: Mapping[str, Any]) -> DatasetVersion:
    return DatasetVersion(
        id=row["id"],
        dataset_id=row["dataset_id"],
        version_number=row["version_number"],
        state=DatasetVersionState(row["state"]),
        created_by=row["created_by"],
        checksum_algorithm=ChecksumAlgorithm(row["checksum_algorithm"]),
        checksum_value=row["checksum_value"],
        declared_format=InputFormat(row["declared_format"]),
        detected_format=InputFormat(row["detected_format"]),
        compression=CompressionKind(row["compression"]),
        reference_build_declared=ReferenceBuildDeclaration(row["reference_build_declared"]),
        source_representation=row["source_representation"] or {},
        version_metadata=row["version_metadata"] or {},
        scientific_metadata=row["scientific_metadata"] or {},
        derived_from_version_id=row["derived_from_version_id"],
        processing_lineage=row["processing_lineage"] or {},
        validated_at=row["validated_at"],
        accepted_at=row["accepted_at"],
        accepted_by=row["accepted_by"],
        rejected_at=row["rejected_at"],
        rejection_reason=row["rejection_reason"],
        superseded_by_version_id=row["superseded_by_version_id"],
        deletion_state=DeletionState(row["deletion_state"]),
        created_at=row["created_at"],
    )


def to_file_artifact(row: Mapping[str, Any]) -> FileArtifact:
    return FileArtifact(
        id=row["id"],
        workspace_id=row["workspace_id"],
        storage_provider=row["storage_provider"],
        storage_bucket=row["storage_bucket"],
        storage_key=row["storage_key"],
        filename=row["filename"],
        uploaded_by=row["uploaded_by"],
        dataset_id=row["dataset_id"],
        dataset_version_id=row["dataset_version_id"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        checksum_algorithm=ChecksumAlgorithm(row["checksum_algorithm"]),
        checksum_value=row["checksum_value"],
        upload_state=FileUploadState(row["upload_state"]),
        validation_state=FileValidationState(row["validation_state"]),
        scan_state=MalwareScanState(row["scan_state"]),
        scan_detail=row["scan_detail"],
        declared_format=InputFormat(row["declared_format"]),
        detected_format=InputFormat(row["detected_format"]),
        compression=CompressionKind(row["compression"]),
        original_filename=row["original_filename"],
        quarantined_at=row["quarantined_at"],
        quarantine_reason=row["quarantine_reason"],
        uploaded_at=row["uploaded_at"],
        metadata_json=row["metadata_json"] or {},
        deletion_state=DeletionState(row["deletion_state"]),
        created_at=row["created_at"],
        version=row["version"],
    )


def to_upload_session(row: Mapping[str, Any]) -> UploadSession:
    return UploadSession(
        id=row["id"],
        workspace_id=row["workspace_id"],
        dataset_id=row["dataset_id"],
        dataset_version_id=row["dataset_version_id"],
        file_artifact_id=row["file_artifact_id"],
        state=UploadSessionState(row["state"]),
        initiated_by=row["initiated_by"],
        storage_key=row["storage_key"],
        declared_filename=row["declared_filename"],
        declared_size_bytes=row["declared_size_bytes"],
        declared_format=InputFormat(row["declared_format"]),
        declared_checksum_algorithm=ChecksumAlgorithm(row["declared_checksum_algorithm"]),
        declared_checksum_value=row["declared_checksum_value"],
        project_id=row["project_id"],
        expires_at=row["expires_at"],
        completed_at=row["completed_at"],
        failure_reason=row["failure_reason"],
        duplicate_relation=DuplicateRelation(row["duplicate_relation"]),
        duplicate_of_file_artifact_id=row["duplicate_of_file_artifact_id"],
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
        version=row["version"],
    )


class SqlDatasetRepository(SqlRepository):
    async def add(self, dataset: Dataset) -> Dataset:
        await self._session.execute(
            insert(_DATASETS).values(
                id=dataset.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                name=dataset.name,
                description=dataset.description,
                kind=dataset.kind.value,
                state=dataset.state.value,
                created_by=dataset.created_by,
                owner_user_id=dataset.owner_user_id,
                reference_build_declared=dataset.reference_build_declared.value,
                source_metadata=dataset.source_metadata,
                scientific_metadata=dataset.scientific_metadata,
                deletion_state=dataset.deletion_state.value,
                version=1,
            )
        )
        return dataset

    async def get(self, dataset_id: str) -> Dataset | None:
        row = await self._fetch_one(select(_DATASETS).where(_DATASETS.c.id == dataset_id))
        return to_dataset(row) if row else None

    async def save(self, dataset: Dataset) -> Dataset:
        version = await self._versioned_update(
            _DATASETS,
            entity_id=dataset.id,
            expected_version=dataset.version,
            values={
                "name": dataset.name,
                "description": dataset.description,
                "state": dataset.state.value,
                "owner_user_id": dataset.owner_user_id,
                "current_version_id": dataset.current_version_id,
                "reference_build_declared": dataset.reference_build_declared.value,
                "source_metadata": dataset.source_metadata,
                "scientific_metadata": dataset.scientific_metadata,
                "deletion_state": dataset.deletion_state.value,
                "deleted_at": dataset.deleted_at,
                "deleted_by": dataset.deleted_by,
                "retention_expires_at": dataset.retention_expires_at,
            },
        )
        return replace(dataset, version=version)

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
        if not workspace_ids:
            return Paged((), 0, page)
        statement = select(_DATASETS).where(
            _DATASETS.c.workspace_id.in_(workspace_ids),
            # Soft-deleted rows are never part of an ordinary listing; recovery
            # is a separate, explicitly authorized retention concern.
            _DATASETS.c.deletion_state == DeletionState.ACTIVE.value,
        )
        if project_id is not None:
            statement = statement.where(_DATASETS.c.project_id == project_id)
        if states:
            statement = statement.where(
                _DATASETS.c.state.in_([state.value for state in states])
            )
        elif not include_archived:
            statement = statement.where(_DATASETS.c.state != DatasetState.ARCHIVED.value)
        if query:
            statement = statement.where(_DATASETS.c.name.ilike(f"%{query}%"))
        statement = statement.order_by(_DATASETS.c.created_at.desc(), _DATASETS.c.id.desc())
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_dataset(row) for row in rows), total, page)

    async def name_exists(self, *, workspace_id: str, project_id: str | None, name: str) -> bool:
        statement = select(_DATASETS).where(
            _DATASETS.c.workspace_id == workspace_id,
            func.lower(_DATASETS.c.name) == name.lower(),
            _DATASETS.c.deletion_state == DeletionState.ACTIVE.value,
        )
        statement = statement.where(
            _DATASETS.c.project_id.is_(None)
            if project_id is None
            else _DATASETS.c.project_id == project_id
        )
        return await self._count(statement) > 0


class SqlDatasetVersionRepository(SqlRepository):
    async def add(self, version: DatasetVersion) -> DatasetVersion:
        await self._session.execute(
            insert(_VERSIONS).values(
                id=version.id,
                dataset_id=version.dataset_id,
                version_number=version.version_number,
                state=version.state.value,
                created_by=version.created_by,
                checksum_algorithm=version.checksum_algorithm.value,
                checksum_value=version.checksum_value,
                declared_format=version.declared_format.value,
                detected_format=version.detected_format.value,
                compression=version.compression.value,
                reference_build_declared=version.reference_build_declared.value,
                source_representation=version.source_representation,
                version_metadata=version.version_metadata,
                scientific_metadata=version.scientific_metadata,
                derived_from_version_id=version.derived_from_version_id,
                processing_lineage=version.processing_lineage,
                deletion_state=version.deletion_state.value,
            )
        )
        return version

    async def get(self, version_id: str) -> DatasetVersion | None:
        row = await self._fetch_one(select(_VERSIONS).where(_VERSIONS.c.id == version_id))
        return to_dataset_version(row) if row else None

    async def save(self, version: DatasetVersion) -> DatasetVersion:
        await self._session.execute(
            _VERSIONS.update()
            .where(_VERSIONS.c.id == version.id)
            .values(
                state=version.state.value,
                checksum_algorithm=version.checksum_algorithm.value,
                checksum_value=version.checksum_value,
                declared_format=version.declared_format.value,
                detected_format=version.detected_format.value,
                compression=version.compression.value,
                reference_build_declared=version.reference_build_declared.value,
                source_representation=version.source_representation,
                version_metadata=version.version_metadata,
                scientific_metadata=version.scientific_metadata,
                processing_lineage=version.processing_lineage,
                validated_at=version.validated_at,
                accepted_at=version.accepted_at,
                accepted_by=version.accepted_by,
                rejected_at=version.rejected_at,
                rejection_reason=version.rejection_reason,
                superseded_by_version_id=version.superseded_by_version_id,
                deletion_state=version.deletion_state.value,
            )
        )
        return version

    async def list_for_dataset(self, dataset_id: str, *, page: Page) -> Paged[DatasetVersion]:
        statement = (
            select(_VERSIONS)
            .where(_VERSIONS.c.dataset_id == dataset_id)
            .order_by(_VERSIONS.c.version_number.desc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_dataset_version(row) for row in rows), total, page)

    async def next_version_number(self, dataset_id: str) -> int:
        """Next number in sequence.

        The database also carries a unique ``(dataset_id, version_number)``
        constraint, so two concurrent creations cannot both take the same number:
        the loser fails the insert instead of quietly overwriting history.
        """
        result = await self._session.execute(
            select(func.coalesce(func.max(_VERSIONS.c.version_number), 0)).where(
                _VERSIONS.c.dataset_id == dataset_id
            )
        )
        return int(result.scalar_one()) + 1

    async def list_accepted(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        rows = await self._fetch_all(
            select(_VERSIONS)
            .where(
                _VERSIONS.c.dataset_id == dataset_id,
                _VERSIONS.c.state == DatasetVersionState.ACCEPTED.value,
            )
            .order_by(_VERSIONS.c.version_number.desc())
        )
        return tuple(to_dataset_version(row) for row in rows)


class SqlFileArtifactRepository(SqlRepository):
    async def add(self, artifact: FileArtifact) -> FileArtifact:
        await self._session.execute(
            insert(_ARTIFACTS).values(
                id=artifact.id,
                workspace_id=artifact.workspace_id,
                dataset_id=artifact.dataset_id,
                dataset_version_id=artifact.dataset_version_id,
                storage_provider=artifact.storage_provider,
                storage_bucket=artifact.storage_bucket,
                storage_key=artifact.storage_key,
                filename=artifact.filename,
                content_type=artifact.content_type,
                size_bytes=artifact.size_bytes,
                checksum_algorithm=artifact.checksum_algorithm.value,
                checksum_value=artifact.checksum_value,
                upload_state=artifact.upload_state.value,
                validation_state=artifact.validation_state.value,
                scan_state=artifact.scan_state.value,
                declared_format=artifact.declared_format.value,
                detected_format=artifact.detected_format.value,
                compression=artifact.compression.value,
                original_filename=artifact.original_filename,
                uploaded_by=artifact.uploaded_by,
                metadata_json=artifact.metadata_json,
                deletion_state=artifact.deletion_state.value,
                version=1,
            )
        )
        return artifact

    async def get(self, artifact_id: str) -> FileArtifact | None:
        row = await self._fetch_one(select(_ARTIFACTS).where(_ARTIFACTS.c.id == artifact_id))
        return to_file_artifact(row) if row else None

    async def save(self, artifact: FileArtifact) -> FileArtifact:
        version = await self._versioned_update(
            _ARTIFACTS,
            entity_id=artifact.id,
            expected_version=artifact.version,
            values={
                "filename": artifact.filename,
                "content_type": artifact.content_type,
                "size_bytes": artifact.size_bytes,
                "checksum_algorithm": artifact.checksum_algorithm.value,
                "checksum_value": artifact.checksum_value,
                "upload_state": artifact.upload_state.value,
                "validation_state": artifact.validation_state.value,
                "scan_state": artifact.scan_state.value,
                "scan_detail": artifact.scan_detail,
                "declared_format": artifact.declared_format.value,
                "detected_format": artifact.detected_format.value,
                "compression": artifact.compression.value,
                "storage_key": artifact.storage_key,
                "quarantined_at": artifact.quarantined_at,
                "quarantine_reason": artifact.quarantine_reason,
                "uploaded_at": artifact.uploaded_at,
                "metadata_json": artifact.metadata_json,
                "deletion_state": artifact.deletion_state.value,
            },
        )
        return replace(artifact, version=version)

    async def list_for_version(self, version_id: str) -> tuple[FileArtifact, ...]:
        rows = await self._fetch_all(
            select(_ARTIFACTS)
            .where(_ARTIFACTS.c.dataset_version_id == version_id)
            .order_by(_ARTIFACTS.c.created_at.asc())
        )
        return tuple(to_file_artifact(row) for row in rows)

    async def find_by_checksum(
        self, *, workspace_id: str, checksum_algorithm: str, checksum_value: str
    ) -> FileArtifact | None:
        """Duplicate *detection* only — the caller decides what that means.

        Scoped to one workspace on purpose: identical bytes in another tenant are
        none of this workspace's business.
        """
        row = await self._fetch_one(
            select(_ARTIFACTS)
            .where(
                _ARTIFACTS.c.workspace_id == workspace_id,
                _ARTIFACTS.c.checksum_algorithm == checksum_algorithm,
                _ARTIFACTS.c.checksum_value == checksum_value,
                _ARTIFACTS.c.deletion_state == DeletionState.ACTIVE.value,
            )
            .order_by(_ARTIFACTS.c.created_at.asc())
        )
        return to_file_artifact(row) if row else None

    async def find_by_filename(self, *, workspace_id: str, filename: str) -> FileArtifact | None:
        row = await self._fetch_one(
            select(_ARTIFACTS)
            .where(
                _ARTIFACTS.c.workspace_id == workspace_id,
                _ARTIFACTS.c.filename == filename,
                _ARTIFACTS.c.deletion_state == DeletionState.ACTIVE.value,
            )
            .order_by(_ARTIFACTS.c.created_at.asc())
        )
        return to_file_artifact(row) if row else None


class SqlUploadSessionRepository(SqlRepository):
    async def add(self, session: UploadSession) -> UploadSession:
        await self._session.execute(
            insert(_UPLOADS).values(
                id=session.id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                dataset_id=session.dataset_id,
                dataset_version_id=session.dataset_version_id,
                file_artifact_id=session.file_artifact_id,
                state=session.state.value,
                initiated_by=session.initiated_by,
                storage_key=session.storage_key,
                declared_filename=session.declared_filename,
                declared_size_bytes=session.declared_size_bytes,
                declared_format=session.declared_format.value,
                declared_checksum_algorithm=session.declared_checksum_algorithm.value,
                declared_checksum_value=session.declared_checksum_value,
                expires_at=session.expires_at,
                duplicate_relation=session.duplicate_relation.value,
                duplicate_of_file_artifact_id=session.duplicate_of_file_artifact_id,
                correlation_id=session.correlation_id,
                version=1,
            )
        )
        return session

    async def get(self, session_id: str) -> UploadSession | None:
        row = await self._fetch_one(select(_UPLOADS).where(_UPLOADS.c.id == session_id))
        return to_upload_session(row) if row else None

    async def save(self, session: UploadSession) -> UploadSession:
        version = await self._versioned_update(
            _UPLOADS,
            entity_id=session.id,
            expected_version=session.version,
            values={
                "state": session.state.value,
                "completed_at": session.completed_at,
                "failure_reason": session.failure_reason,
                "duplicate_relation": session.duplicate_relation.value,
                "duplicate_of_file_artifact_id": session.duplicate_of_file_artifact_id,
                "expires_at": session.expires_at,
            },
        )
        return replace(session, version=version)

    async def get_for_artifact(self, artifact_id: str) -> UploadSession | None:
        row = await self._fetch_one(
            select(_UPLOADS)
            .where(_UPLOADS.c.file_artifact_id == artifact_id)
            .order_by(_UPLOADS.c.created_at.desc())
        )
        return to_upload_session(row) if row else None

    async def list_for_version(self, version_id: str) -> tuple[UploadSession, ...]:
        rows = await self._fetch_all(
            select(_UPLOADS)
            .where(_UPLOADS.c.dataset_version_id == version_id)
            .order_by(_UPLOADS.c.created_at.asc())
        )
        return tuple(to_upload_session(row) for row in rows)

    async def list_expired(
        self, *, moment: datetime, limit: int = 100
    ) -> tuple[UploadSession, ...]:
        """Sessions whose transfer window has passed while still open.

        Expiry is a backend decision reconciled by a retention job; a client
        holding a stale presigned URL cannot revive one.
        """
        rows = await self._fetch_all(
            select(_UPLOADS)
            .where(
                _UPLOADS.c.expires_at.is_not(None),
                _UPLOADS.c.expires_at < moment,
                _UPLOADS.c.state.in_(
                    (
                        UploadSessionState.CREATED.value,
                        UploadSessionState.UPLOADING.value,
                    )
                ),
            )
            .order_by(_UPLOADS.c.expires_at.asc())
            .limit(limit)
        )
        return tuple(to_upload_session(row) for row in rows)


__all__ = [
    "SqlDatasetRepository",
    "SqlDatasetVersionRepository",
    "SqlFileArtifactRepository",
    "SqlUploadSessionRepository",
    "to_dataset",
    "to_dataset_version",
    "to_file_artifact",
    "to_upload_session",
]
