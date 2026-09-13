"""Persistence for result sets, result artifacts and ingestion requests.

Result *content* never appears in these statements. PostgreSQL holds the surface
— who produced it, from what, in which version, whether the bytes verify, and
whether the surface is still presentable — while the rows themselves live in
object storage as Parquet and are read through DuckDB.

Updates are version-checked (``UPDATE ... WHERE version = :expected``) because
two workers may legitimately race to complete the same ingestion. What they may
never do is both mark the same surface available with different content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.application.repositories import Page, Paged
from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    DataOrigin,
    DeletionState,
    ResultArtifactFormat,
    ResultArtifactKind,
    ResultArtifactState,
    ResultCompleteness,
    ResultIngestionState,
    ResultSetState,
)
from app.domain.variant.results import (
    ResultArtifactRecord,
    ResultIngestionRequest,
    ResultProvenance,
    ResultSetRecord,
)
from app.infrastructure.persistence.models.results import ResultSet
from app.infrastructure.persistence.models.variant_results import (
    ResultArtifact,
    ResultIngestionRequest as IngestionModel,
)
from app.infrastructure.persistence.repositories.base import SqlRepository

_RESULT_SETS = ResultSet.__table__
_ARTIFACTS = ResultArtifact.__table__
_INGESTIONS = IngestionModel.__table__


def to_result_set(row: Mapping[str, Any]) -> ResultSetRecord:
    provenance = ResultProvenance(
        analysis_execution_id=row["analysis_execution_id"],
        scientific_execution_id=row["scientific_execution_id"],
        analysis_configuration_id=row["analysis_configuration_id"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        container_image_digest=row["container_image_digest"],
        node_identity=row["node_identity"],
        reference_genome_resource_id=row["reference_genome_resource_id"],
        resource_identities=row["resource_identities"] or {},
        parameters_digest=row["parameters_digest"],
        provenance_manifest_id=row["provenance_manifest_id"],
    )
    return ResultSetRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        result_key=row["result_key"],
        state=ResultSetState(row["state"]),
        provenance=provenance,
        completeness=ResultCompleteness(row["completeness"]),
        origin=DataOrigin(row["origin"]),
        analytical_location=row["analytical_location"],
        scientific_artifact_id=row["scientific_artifact_id"],
        row_count=row["row_count"],
        column_schema=row["column_schema"] or {},
        superseded_by_result_set_id=row["superseded_by_result_set_id"],
        invalidation_reason=row["invalidation_reason"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        metadata=row["metadata_json"] or {},
        available_at=row["available_at"],
        deletion_state=DeletionState(row["deletion_state"]),
        deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"],
        retention_expires_at=row["retention_expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


def to_artifact(row: Mapping[str, Any]) -> ResultArtifactRecord:
    checksum = row["checksum_algorithm"]
    return ResultArtifactRecord(
        id=row["id"],
        result_set_id=row["result_set_id"],
        artifact_key=row["artifact_key"],
        kind=ResultArtifactKind(row["kind"]),
        artifact_format=ResultArtifactFormat(row["artifact_format"]),
        state=ResultArtifactState(row["state"]),
        storage_uri=row["storage_uri"],
        file_artifact_id=row["file_artifact_id"],
        analytical_location=row["analytical_location"],
        scientific_artifact_id=row["scientific_artifact_id"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        checksum_algorithm=ChecksumAlgorithm(checksum) if checksum else None,
        checksum_value=row["checksum_value"],
        row_count=row["row_count"],
        column_schema=row["column_schema"] or {},
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        metadata=row["metadata_json"] or {},
        verified_at=row["verified_at"],
        created_at=row["created_at"],
        version=row["version"],
    )


def to_ingestion(row: Mapping[str, Any]) -> ResultIngestionRequest:
    findings = row["findings"] or {}
    return ResultIngestionRequest(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        analysis_execution_id=row["analysis_execution_id"],
        result_key=row["result_key"],
        idempotency_key=row["idempotency_key"],
        state=ResultIngestionState(row["state"]),
        payload_digest=row["payload_digest"],
        declared_completeness=ResultCompleteness(row["declared_completeness"]),
        scientific_execution_id=row["scientific_execution_id"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        submitted_by=row["submitted_by"],
        service_account_id=row["service_account_id"],
        job_id=row["job_id"],
        correlation_id=row["correlation_id"],
        result_set_id=row["result_set_id"],
        declared_row_count=row["declared_row_count"],
        artifact_count=row["artifact_count"],
        is_development_payload=bool(row["is_development_payload"]),
        findings=tuple(findings.get("items", ())),
        rejection_code=row["rejection_code"],
        rejection_message=row["rejection_message"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        received_at=row["received_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        version=row["version"],
    )


class SqlResultSetRepository(SqlRepository):
    async def add(self, result_set: ResultSetRecord) -> ResultSetRecord:
        provenance = result_set.provenance
        await self._session.execute(
            insert(_RESULT_SETS).values(
                id=result_set.id,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                analysis_execution_id=provenance.analysis_execution_id,
                result_key=result_set.result_key,
                state=result_set.state.value,
                analytical_location=result_set.analytical_location,
                scientific_artifact_id=result_set.scientific_artifact_id,
                row_count=result_set.row_count,
                column_schema=result_set.column_schema,
                provenance_manifest_id=provenance.provenance_manifest_id,
                metadata_json=result_set.metadata,
                completeness=result_set.completeness.value,
                origin=result_set.origin.value,
                scientific_execution_id=provenance.scientific_execution_id,
                analysis_configuration_id=provenance.analysis_configuration_id,
                engine_resource_id=provenance.engine_resource_id,
                engine_version=provenance.engine_version,
                environment_version=provenance.environment_version,
                container_image_digest=provenance.container_image_digest,
                node_identity=provenance.node_identity,
                reference_genome_resource_id=provenance.reference_genome_resource_id,
                resource_identities=provenance.resource_identities,
                parameters_digest=provenance.parameters_digest,
                available_at=result_set.available_at,
                deletion_state=result_set.deletion_state.value,
            )
        )
        return result_set

    async def get(self, result_set_id: str) -> ResultSetRecord | None:
        row = await self._fetch_one(
            select(_RESULT_SETS).where(_RESULT_SETS.c.id == result_set_id)
        )
        return to_result_set(row) if row else None

    async def save(self, result_set: ResultSetRecord) -> ResultSetRecord:
        """Persist a lifecycle transition. Scientific content is not updated here.

        Only state, lineage and the location/shape facts established at
        materialization time are written. There is deliberately no path that
        rewrites the provenance of an existing surface.
        """
        version = await self._versioned_update(
            _RESULT_SETS,
            entity_id=result_set.id,
            expected_version=result_set.version,
            values={
                "state": result_set.state.value,
                "completeness": result_set.completeness.value,
                "analytical_location": result_set.analytical_location,
                "scientific_artifact_id": result_set.scientific_artifact_id,
                "row_count": result_set.row_count,
                "column_schema": result_set.column_schema,
                "superseded_by_result_set_id": result_set.superseded_by_result_set_id,
                "invalidation_reason": result_set.invalidation_reason,
                "failure_code": result_set.failure_code,
                "failure_message": result_set.failure_message,
                "metadata_json": result_set.metadata,
                "available_at": result_set.available_at,
                "deletion_state": result_set.deletion_state.value,
                "deleted_at": result_set.deleted_at,
                "deleted_by": result_set.deleted_by,
                "retention_expires_at": result_set.retention_expires_at,
            },
        )
        return ResultSetRecord(**{**_as_dict(result_set), "version": version})

    async def find_by_result_key(
        self, *, analysis_execution_id: str, result_key: str
    ) -> ResultSetRecord | None:
        row = await self._fetch_one(
            select(_RESULT_SETS)
            .where(
                _RESULT_SETS.c.analysis_execution_id == analysis_execution_id,
                _RESULT_SETS.c.result_key == result_key,
            )
            # Newest first: an older surface for the same key is superseded, not
            # replaced, so both rows exist and the caller wants the current one.
            .order_by(_RESULT_SETS.c.created_at.desc(), _RESULT_SETS.c.id.desc())
        )
        return to_result_set(row) if row else None

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        analysis_execution_id: str | None = None,
        states: tuple[ResultSetState, ...] = (),
    ) -> Paged[ResultSetRecord]:
        if not workspace_ids:
            # No accessible workspace means no rows — never "all rows".
            return Paged(items=(), total=0, page=page)
        statement = select(_RESULT_SETS).where(
            _RESULT_SETS.c.workspace_id.in_(workspace_ids),
            _RESULT_SETS.c.deletion_state == DeletionState.ACTIVE.value,
        )
        if project_id is not None:
            statement = statement.where(_RESULT_SETS.c.project_id == project_id)
        if analysis_execution_id is not None:
            statement = statement.where(
                _RESULT_SETS.c.analysis_execution_id == analysis_execution_id
            )
        if states:
            statement = statement.where(
                _RESULT_SETS.c.state.in_([state.value for state in states])
            )
        return await self._paged(statement, page)

    async def list_all(
        self, *, page: Page, states: tuple[ResultSetState, ...] = ()
    ) -> Paged[ResultSetRecord]:
        statement = select(_RESULT_SETS)
        if states:
            statement = statement.where(
                _RESULT_SETS.c.state.in_([state.value for state in states])
            )
        return await self._paged(statement, page)

    async def _paged(self, statement: Select, page: Page) -> Paged[ResultSetRecord]:
        statement = statement.order_by(
            _RESULT_SETS.c.created_at.desc(), _RESULT_SETS.c.id.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.limit).offset(page.offset))
        return Paged(items=tuple(to_result_set(row) for row in rows), total=total, page=page)


def _as_dict(result_set: ResultSetRecord) -> dict[str, Any]:
    return {
        field: getattr(result_set, field) for field in ResultSetRecord.__dataclass_fields__
    }


class SqlResultArtifactRepository(SqlRepository):
    async def add_many(
        self, artifacts: tuple[ResultArtifactRecord, ...]
    ) -> tuple[ResultArtifactRecord, ...]:
        for item in artifacts:
            await self._session.execute(
                pg_insert(_ARTIFACTS)
                .values(
                    id=item.id,
                    result_set_id=item.result_set_id,
                    artifact_key=item.artifact_key,
                    kind=item.kind.value,
                    artifact_format=item.artifact_format.value,
                    state=item.state.value,
                    storage_uri=item.storage_uri,
                    file_artifact_id=item.file_artifact_id,
                    analytical_location=item.analytical_location,
                    scientific_artifact_id=item.scientific_artifact_id,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                    checksum_algorithm=(
                        item.checksum_algorithm.value if item.checksum_algorithm else None
                    ),
                    checksum_value=item.checksum_value,
                    row_count=item.row_count,
                    column_schema=item.column_schema,
                    metadata_json=item.metadata,
                    verified_at=item.verified_at,
                )
                # A redelivered payload registers the same artifact keys; that is
                # the idempotent case, not a conflict.
                .on_conflict_do_nothing(
                    index_elements=[_ARTIFACTS.c.result_set_id, _ARTIFACTS.c.artifact_key]
                )
            )
        return artifacts

    async def get(self, artifact_id: str) -> ResultArtifactRecord | None:
        row = await self._fetch_one(select(_ARTIFACTS).where(_ARTIFACTS.c.id == artifact_id))
        return to_artifact(row) if row else None

    async def save(self, artifact: ResultArtifactRecord) -> ResultArtifactRecord:
        version = await self._versioned_update(
            _ARTIFACTS,
            entity_id=artifact.id,
            expected_version=artifact.version,
            values={
                "state": artifact.state.value,
                "size_bytes": artifact.size_bytes,
                "row_count": artifact.row_count,
                "column_schema": artifact.column_schema,
                "failure_code": artifact.failure_code,
                "failure_message": artifact.failure_message,
                "metadata_json": artifact.metadata,
                "verified_at": artifact.verified_at,
            },
        )
        return ResultArtifactRecord(
            **{
                **{
                    field: getattr(artifact, field)
                    for field in ResultArtifactRecord.__dataclass_fields__
                },
                "version": version,
            }
        )

    async def list_for_result_set(
        self, result_set_id: str
    ) -> tuple[ResultArtifactRecord, ...]:
        rows = await self._fetch_all(
            select(_ARTIFACTS)
            .where(_ARTIFACTS.c.result_set_id == result_set_id)
            .order_by(_ARTIFACTS.c.artifact_key)
        )
        return tuple(to_artifact(row) for row in rows)


class SqlResultIngestionRepository(SqlRepository):
    async def add(self, request: ResultIngestionRequest) -> ResultIngestionRequest:
        await self._session.execute(
            insert(_INGESTIONS).values(
                id=request.id,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                analysis_execution_id=request.analysis_execution_id,
                scientific_execution_id=request.scientific_execution_id,
                result_set_id=request.result_set_id,
                result_key=request.result_key,
                idempotency_key=request.idempotency_key,
                payload_digest=request.payload_digest,
                state=request.state.value,
                declared_completeness=request.declared_completeness.value,
                declared_row_count=request.declared_row_count,
                artifact_count=request.artifact_count,
                engine_resource_id=request.engine_resource_id,
                engine_version=request.engine_version,
                submitted_by=request.submitted_by,
                service_account_id=request.service_account_id,
                job_id=request.job_id,
                correlation_id=request.correlation_id,
                is_development_payload=request.is_development_payload,
                findings={"items": list(request.findings)},
                received_at=request.received_at,
            )
        )
        return request

    async def get(self, request_id: str) -> ResultIngestionRequest | None:
        row = await self._fetch_one(select(_INGESTIONS).where(_INGESTIONS.c.id == request_id))
        return to_ingestion(row) if row else None

    async def save(self, request: ResultIngestionRequest) -> ResultIngestionRequest:
        version = await self._versioned_update(
            _INGESTIONS,
            entity_id=request.id,
            expected_version=request.version,
            values={
                "state": request.state.value,
                "result_set_id": request.result_set_id,
                "artifact_count": request.artifact_count,
                "findings": {"items": list(request.findings)},
                "rejection_code": request.rejection_code,
                "rejection_message": request.rejection_message,
                "failure_code": request.failure_code,
                "failure_message": request.failure_message,
                "completed_at": request.completed_at,
            },
        )
        return ResultIngestionRequest(
            **{
                **{
                    field: getattr(request, field)
                    for field in ResultIngestionRequest.__dataclass_fields__
                },
                "version": version,
            }
        )

    async def get_by_idempotency_key(self, key: str) -> ResultIngestionRequest | None:
        row = await self._fetch_one(
            select(_INGESTIONS).where(_INGESTIONS.c.idempotency_key == key)
        )
        return to_ingestion(row) if row else None

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[ResultIngestionState, ...] = (),
    ) -> Paged[ResultIngestionRequest]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        statement = select(_INGESTIONS).where(
            _INGESTIONS.c.workspace_id.in_(workspace_ids)
        )
        if project_id is not None:
            statement = statement.where(_INGESTIONS.c.project_id == project_id)
        if states:
            statement = statement.where(
                _INGESTIONS.c.state.in_([state.value for state in states])
            )
        statement = statement.order_by(
            _INGESTIONS.c.received_at.desc(), _INGESTIONS.c.id.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.limit).offset(page.offset))
        return Paged(items=tuple(to_ingestion(row) for row in rows), total=total, page=page)


__all__ = [
    "SqlResultArtifactRepository",
    "SqlResultIngestionRepository",
    "SqlResultSetRepository",
    "to_artifact",
    "to_ingestion",
    "to_result_set",
]
