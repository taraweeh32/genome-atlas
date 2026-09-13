"""Provenance mirror of scientific-subsystem runs.

Append-only by design: the application records *that* a scientific execution was
requested, which engine/environment/resource versions answered, and how it
ended. It never stores or recomputes scientific content, and it never rewrites
the identity of a historical run — only the outcome fields of the run it created.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domain.analysis.entities import (
    ScientificArtifactRecord,
    ScientificExecutionRecord,
)
from app.domain.value_objects.enums import ScientificExecutionState
from app.infrastructure.persistence.models.scientific import ScientificArtifact
from app.infrastructure.persistence.models.scientific import ScientificExecution as Model
from app.infrastructure.persistence.repositories.base import SqlRepository

_EXECUTIONS = Model.__table__
_ARTIFACTS = ScientificArtifact.__table__


def to_record(row: Mapping[str, Any]) -> ScientificExecutionRecord:
    return ScientificExecutionRecord(
        id=row["id"],
        capability_key=row["capability_key"],
        state=ScientificExecutionState(row["state"]),
        submitted_at=row["submitted_at"],
        correlation_id=row["correlation_id"],
        analysis_execution_id=row["analysis_execution_id"],
        job_id=row["job_id"],
        external_execution_id=row["external_execution_id"],
        capability_version=row["capability_version"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        container_image_digest=row["container_image_digest"],
        node_identity=row["node_identity"],
        resource_identities=row["resource_identities"] or {},
        parameters=row["parameters"] or {},
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        failure_details=row["failure_details"] or {},
    )

def to_artifact(row: Mapping[str, Any]) -> ScientificArtifactRecord:
    return ScientificArtifactRecord(
        id=row["id"],
        scientific_execution_id=row["scientific_execution_id"],
        artifact_key=row["artifact_key"],
        artifact_kind=row["artifact_kind"],
        analytical_location=row["analytical_location"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        checksum_algorithm=row["checksum_algorithm"],
        checksum_value=row["checksum_value"],
        metadata=row["metadata_json"] or {},
    )


class SqlScientificExecutionRepository(SqlRepository):
    async def add(self, record: ScientificExecutionRecord) -> ScientificExecutionRecord:
        await self._session.execute(
            insert(_EXECUTIONS).values(
                id=record.id,
                analysis_execution_id=record.analysis_execution_id,
                job_id=record.job_id,
                external_execution_id=record.external_execution_id,
                capability_key=record.capability_key,
                capability_version=record.capability_version,
                engine_version=record.engine_version,
                environment_version=record.environment_version,
                container_image_digest=record.container_image_digest,
                node_identity=record.node_identity,
                resource_identities=record.resource_identities,
                parameters=record.parameters,
                state=record.state.value,
                submitted_at=record.submitted_at,
                started_at=record.started_at,
                correlation_id=record.correlation_id,
            )
        )
        return record

    async def get(self, record_id: str) -> ScientificExecutionRecord | None:
        row = await self._fetch_one(select(_EXECUTIONS).where(_EXECUTIONS.c.id == record_id))
        return to_record(row) if row else None

    async def record_outcome(
        self, record: ScientificExecutionRecord
    ) -> ScientificExecutionRecord:
        await self._session.execute(
            update(_EXECUTIONS)
            .where(_EXECUTIONS.c.id == record.id)
            .values(
                state=record.state.value,
                external_execution_id=record.external_execution_id,
                engine_version=record.engine_version,
                environment_version=record.environment_version,
                container_image_digest=record.container_image_digest,
                node_identity=record.node_identity,
                resource_identities=record.resource_identities,
                started_at=record.started_at,
                completed_at=record.completed_at,
                failure_code=record.failure_code,
                failure_message=record.failure_message,
                failure_details=record.failure_details,
            )
        )
        return record

    async def record_artifacts(
        self, artifacts: tuple[ScientificArtifactRecord, ...]
    ) -> tuple[ScientificArtifactRecord, ...]:
        """Record produced artifacts. Re-reporting the same key is idempotent."""
        for artifact in artifacts:
            await self._session.execute(
                pg_insert(_ARTIFACTS)
                .values(
                    id=artifact.id,
                    scientific_execution_id=artifact.scientific_execution_id,
                    artifact_key=artifact.artifact_key,
                    artifact_kind=artifact.artifact_kind,
                    analytical_location=artifact.analytical_location,
                    content_type=artifact.content_type,
                    size_bytes=artifact.size_bytes,
                    checksum_algorithm=artifact.checksum_algorithm,
                    checksum_value=artifact.checksum_value,
                    metadata_json=artifact.metadata,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _ARTIFACTS.c.scientific_execution_id,
                        _ARTIFACTS.c.artifact_key,
                    ]
                )
            )
        return artifacts

    async def list_artifacts(
        self, scientific_execution_id: str
    ) -> tuple[ScientificArtifactRecord, ...]:
        rows = await self._fetch_all(
            select(_ARTIFACTS)
            .where(_ARTIFACTS.c.scientific_execution_id == scientific_execution_id)
            .order_by(_ARTIFACTS.c.artifact_key)
        )
        return tuple(to_artifact(row) for row in rows)

    async def list_for_execution(
        self, analysis_execution_id: str
    ) -> tuple[ScientificExecutionRecord, ...]:
        rows = await self._fetch_all(
            select(_EXECUTIONS)
            .where(_EXECUTIONS.c.analysis_execution_id == analysis_execution_id)
            .order_by(_EXECUTIONS.c.submitted_at)
        )
        return tuple(to_record(row) for row in rows)


__all__ = ["SqlScientificExecutionRepository", "to_artifact", "to_record"]
