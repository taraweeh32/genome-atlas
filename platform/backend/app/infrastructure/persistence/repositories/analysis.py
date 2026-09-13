"""Analysis definition, configuration-version and execution repositories.

Conventions carried over from Packages 3-4:

* Reads are scope-explicit: ``list_for_scope`` takes the workspaces the caller
  has already been authorized for, and an empty scope returns nothing rather
  than everything, so a missing authorization check cannot leak rows.
* Mutable rows are saved under the version they were read at, so a concurrent
  edit raises ``ConcurrencyConflictError`` instead of silently winning.
* Configuration versions and executions are history. There is no method that
  rewrites a configuration's scientific sections or an execution's snapshot;
  ``record_validation`` writes a configuration's *own* validation outcome, and
  execution ``save`` only advances lifecycle/progress columns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy import func, insert, select

from app.application.repositories import Page, Paged
from app.domain.analysis.entities import (
    AnalysisConfigurationVersion,
    AnalysisDefinition,
    AnalysisExecutionRecord,
    ConfigurationInput,
    ExecutionInput,
)
from app.domain.lifecycle import ACTIVE_EXECUTION_STATES
from app.domain.value_objects.enums import (
    AnalysisKind,
    AnalysisState,
    ConfigurationValidationState,
    DeletionState,
    ExecutionState,
    JobQueue,
)
from app.infrastructure.persistence.models.analysis import Analysis as AnalysisModel
from app.infrastructure.persistence.models.analysis import (
    AnalysisConfiguration as ConfigurationModel,
)
from app.infrastructure.persistence.models.analysis import (
    AnalysisConfigurationInput as ConfigurationInputModel,
)
from app.infrastructure.persistence.models.analysis import (
    AnalysisExecution as ExecutionModel,
)
from app.infrastructure.persistence.models.analysis import (
    AnalysisExecutionInput as ExecutionInputModel,
)
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_ANALYSES = AnalysisModel.__table__
_CONFIGURATIONS = ConfigurationModel.__table__
_CONFIGURATION_INPUTS = ConfigurationInputModel.__table__
_EXECUTIONS = ExecutionModel.__table__
_EXECUTION_INPUTS = ExecutionInputModel.__table__


def to_analysis(row: Mapping[str, Any]) -> AnalysisDefinition:
    return AnalysisDefinition(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        name=row["name"],
        kind=AnalysisKind(row["kind"]),
        state=AnalysisState(row["state"]),
        created_by=row["created_by"],
        capability_key=row["capability_key"],
        description=row["description"],
        owner_user_id=row["owner_user_id"],
        current_configuration_id=row["current_configuration_id"],
        execution_defaults=row["execution_defaults"] or {},
        metadata=row["metadata_json"] or {},
        deletion_state=DeletionState(row["deletion_state"]),
        deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"],
        retention_expires_at=row["retention_expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


def to_configuration(row: Mapping[str, Any]) -> AnalysisConfigurationVersion:
    return AnalysisConfigurationVersion(
        id=row["id"],
        analysis_id=row["analysis_id"],
        version_number=row["version_number"],
        created_by=row["created_by"],
        label=row["label"],
        filtering_configuration=row["filtering_configuration"] or {},
        ranking_configuration=row["ranking_configuration"] or {},
        annotation_configuration=row["annotation_configuration"] or {},
        evidence_configuration=row["evidence_configuration"] or {},
        interpretation_configuration=row["interpretation_configuration"] or {},
        reporting_configuration=row["reporting_configuration"] or {},
        execution_parameters=row["execution_parameters"] or {},
        pipeline_resource_id=row["pipeline_resource_id"],
        engine_resource_id=row["engine_resource_id"],
        reference_genome_resource_id=row["reference_genome_resource_id"],
        ruleset_resource_id=row["ruleset_resource_id"],
        execution_profile_resource_id=row["execution_profile_resource_id"],
        validation_state=ConfigurationValidationState(row["validation_state"]),
        validation_findings=row["validation_findings"] or {},
        content_hash=row["content_hash"],
        snapshot=row["snapshot"] or {},
        created_at=row["created_at"],
    )


def to_execution(row: Mapping[str, Any]) -> AnalysisExecutionRecord:
    return AnalysisExecutionRecord(
        id=row["id"],
        analysis_id=row["analysis_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        analysis_configuration_id=row["analysis_configuration_id"],
        attempt_sequence=row["attempt_sequence"],
        state=ExecutionState(row["state"]),
        requested_at=row["requested_at"],
        correlation_id=row["correlation_id"],
        requested_by=row["requested_by"],
        configuration_snapshot=row["configuration_snapshot"] or {},
        capability_key=row["capability_key"],
        capability_version=row["capability_version"],
        queue=JobQueue(row["queue"]),
        priority=row["priority"],
        resource_requirements=row["resource_requirements"] or {},
        idempotency_key=row["idempotency_key"],
        schedule_id=row["schedule_id"],
        scheduled_for=row["scheduled_for"],
        scheduled_job_id=row["scheduled_job_id"],
        scientific_execution_id=row["scientific_execution_id"],
        compute_node_id=row["compute_node_id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        progress_percent=row["progress_percent"],
        progress_message=row["progress_message"],
        cancel_requested_at=row["cancel_requested_at"],
        cancel_requested_by=row["cancel_requested_by"],
        cancellation_reason=row["cancellation_reason"],
        execution_environment=row["execution_environment"] or {},
        resource_profile=row["resource_profile"] or {},
        scientific_versions=row["scientific_versions"] or {},
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        failure_details=row["failure_details"] or {},
        created_at=row["created_at"],
    )


class SqlAnalysisRepository(SqlRepository):
    async def add(self, analysis: AnalysisDefinition) -> AnalysisDefinition:
        await self._session.execute(
            insert(_ANALYSES).values(
                id=analysis.id,
                workspace_id=analysis.workspace_id,
                project_id=analysis.project_id,
                name=analysis.name,
                description=analysis.description,
                kind=analysis.kind.value,
                capability_key=analysis.capability_key,
                state=analysis.state.value,
                created_by=analysis.created_by,
                owner_user_id=analysis.owner_user_id,
                current_configuration_id=analysis.current_configuration_id,
                execution_defaults=analysis.execution_defaults,
                metadata_json=analysis.metadata,
                deletion_state=analysis.deletion_state.value,
                version=analysis.version,
            )
        )
        return analysis

    async def get(self, analysis_id: str) -> AnalysisDefinition | None:
        row = await self._fetch_one(select(_ANALYSES).where(_ANALYSES.c.id == analysis_id))
        return to_analysis(row) if row else None

    async def save(self, analysis: AnalysisDefinition) -> AnalysisDefinition:
        version = await self._versioned_update(
            _ANALYSES,
            entity_id=analysis.id,
            expected_version=analysis.version,
            values={
                "name": analysis.name,
                "description": analysis.description,
                "state": analysis.state.value,
                "owner_user_id": analysis.owner_user_id,
                "current_configuration_id": analysis.current_configuration_id,
                "capability_key": analysis.capability_key,
                "execution_defaults": analysis.execution_defaults,
                "metadata_json": analysis.metadata,
                "deletion_state": analysis.deletion_state.value,
                "deleted_at": analysis.deleted_at,
                "deleted_by": analysis.deleted_by,
                "retention_expires_at": analysis.retention_expires_at,
            },
        )
        return replace(analysis, version=version)

    async def name_exists(self, *, project_id: str, name: str) -> bool:
        row = await self._fetch_one(
            select(_ANALYSES.c.id).where(
                _ANALYSES.c.project_id == project_id,
                func.lower(_ANALYSES.c.name) == name.strip().lower(),
                _ANALYSES.c.deletion_state == DeletionState.ACTIVE.value,
            )
        )
        return row is not None

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[AnalysisState, ...] = (),
        query: str | None = None,
    ) -> Paged[AnalysisDefinition]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        statement = select(_ANALYSES).where(
            _ANALYSES.c.workspace_id.in_(workspace_ids),
            _ANALYSES.c.deletion_state == DeletionState.ACTIVE.value,
        )
        if project_id is not None:
            statement = statement.where(_ANALYSES.c.project_id == project_id)
        if states:
            statement = statement.where(_ANALYSES.c.state.in_([s.value for s in states]))
        if query:
            statement = statement.where(_ANALYSES.c.name.ilike(f"%{query.strip()}%"))
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_ANALYSES.c.name).limit(page.size).offset(page.offset)
        )
        return Paged(items=tuple(to_analysis(row) for row in rows), total=total, page=page)


class SqlAnalysisConfigurationRepository(SqlRepository):
    async def add(
        self, configuration: AnalysisConfigurationVersion
    ) -> AnalysisConfigurationVersion:
        await self._session.execute(
            insert(_CONFIGURATIONS).values(
                id=configuration.id,
                analysis_id=configuration.analysis_id,
                version_number=configuration.version_number,
                created_by=configuration.created_by,
                label=configuration.label,
                filtering_configuration=configuration.filtering_configuration,
                ranking_configuration=configuration.ranking_configuration,
                annotation_configuration=configuration.annotation_configuration,
                evidence_configuration=configuration.evidence_configuration,
                interpretation_configuration=configuration.interpretation_configuration,
                reporting_configuration=configuration.reporting_configuration,
                execution_parameters=configuration.execution_parameters,
                pipeline_resource_id=configuration.pipeline_resource_id,
                engine_resource_id=configuration.engine_resource_id,
                reference_genome_resource_id=configuration.reference_genome_resource_id,
                ruleset_resource_id=configuration.ruleset_resource_id,
                execution_profile_resource_id=configuration.execution_profile_resource_id,
                validation_state=configuration.validation_state.value,
                validation_findings=configuration.validation_findings,
                content_hash=configuration.content_hash,
                snapshot=configuration.snapshot,
            )
        )
        return configuration

    async def get(self, configuration_id: str) -> AnalysisConfigurationVersion | None:
        row = await self._fetch_one(
            select(_CONFIGURATIONS).where(_CONFIGURATIONS.c.id == configuration_id)
        )
        return to_configuration(row) if row else None

    async def record_validation(
        self, configuration: AnalysisConfigurationVersion
    ) -> AnalysisConfigurationVersion:
        """Write only this version's own validation outcome.

        Deliberately narrow: the scientific sections are never updated here, so
        an execution that referenced this version stays reproducible.
        """
        from sqlalchemy import update

        await self._session.execute(
            update(_CONFIGURATIONS)
            .where(_CONFIGURATIONS.c.id == configuration.id)
            .values(
                validation_state=configuration.validation_state.value,
                validation_findings=configuration.validation_findings,
                content_hash=configuration.content_hash,
            )
        )
        return configuration

    async def next_version_number(self, analysis_id: str) -> int:
        current = await self._session.scalar(
            select(func.max(_CONFIGURATIONS.c.version_number)).where(
                _CONFIGURATIONS.c.analysis_id == analysis_id
            )
        )
        return int(current or 0) + 1

    async def list_for_analysis(
        self, analysis_id: str, *, page: Page
    ) -> Paged[AnalysisConfigurationVersion]:
        statement = select(_CONFIGURATIONS).where(_CONFIGURATIONS.c.analysis_id == analysis_id)
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_CONFIGURATIONS.c.version_number.desc())
            .limit(page.size)
            .offset(page.offset)
        )
        return Paged(items=tuple(to_configuration(row) for row in rows), total=total, page=page)

    async def add_inputs(self, inputs: tuple[ConfigurationInput, ...]) -> None:
        if not inputs:
            return
        await self._session.execute(
            insert(_CONFIGURATION_INPUTS),
            [
                {
                    "id": item.id or new_id("acin"),
                    "analysis_configuration_id": item.analysis_configuration_id,
                    "dataset_version_id": item.dataset_version_id,
                    "role": item.role,
                }
                for item in inputs
            ],
        )

    async def list_inputs(self, configuration_id: str) -> tuple[ConfigurationInput, ...]:
        rows = await self._fetch_all(
            select(_CONFIGURATION_INPUTS).where(
                _CONFIGURATION_INPUTS.c.analysis_configuration_id == configuration_id
            )
        )
        return tuple(
            ConfigurationInput(
                id=row["id"],
                analysis_configuration_id=row["analysis_configuration_id"],
                dataset_version_id=row["dataset_version_id"],
                role=row["role"],
            )
            for row in rows
        )


class SqlAnalysisExecutionRepository(SqlRepository):
    async def add(self, execution: AnalysisExecutionRecord) -> AnalysisExecutionRecord:
        await self._session.execute(
            insert(_EXECUTIONS).values(
                id=execution.id,
                analysis_id=execution.analysis_id,
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                analysis_configuration_id=execution.analysis_configuration_id,
                configuration_snapshot=execution.configuration_snapshot,
                attempt_sequence=execution.attempt_sequence,
                state=execution.state.value,
                requested_by=execution.requested_by,
                requested_at=execution.requested_at,
                correlation_id=execution.correlation_id,
                capability_key=execution.capability_key,
                capability_version=execution.capability_version,
                queue=execution.queue.value,
                priority=execution.priority,
                resource_requirements=execution.resource_requirements,
                idempotency_key=execution.idempotency_key,
                schedule_id=execution.schedule_id,
                scheduled_for=execution.scheduled_for,
                execution_environment=execution.execution_environment,
                resource_profile=execution.resource_profile,
                scientific_versions=execution.scientific_versions,
            )
        )
        return execution

    async def get(self, execution_id: str) -> AnalysisExecutionRecord | None:
        row = await self._fetch_one(select(_EXECUTIONS).where(_EXECUTIONS.c.id == execution_id))
        return to_execution(row) if row else None

    async def save(self, execution: AnalysisExecutionRecord) -> AnalysisExecutionRecord:
        """Advance lifecycle bookkeeping only.

        The request-time snapshot, inputs, attempt sequence and requester are
        absent on purpose: historical scientific context is never rewritten.
        """
        from sqlalchemy import update

        await self._session.execute(
            update(_EXECUTIONS)
            .where(_EXECUTIONS.c.id == execution.id)
            .values(
                state=execution.state.value,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                scheduled_job_id=execution.scheduled_job_id,
                scientific_execution_id=execution.scientific_execution_id,
                compute_node_id=execution.compute_node_id,
                progress_percent=execution.progress_percent,
                progress_message=execution.progress_message,
                cancel_requested_at=execution.cancel_requested_at,
                cancel_requested_by=execution.cancel_requested_by,
                cancellation_reason=execution.cancellation_reason,
                execution_environment=execution.execution_environment,
                resource_profile=execution.resource_profile,
                scientific_versions=execution.scientific_versions,
                failure_code=execution.failure_code,
                failure_message=execution.failure_message,
                failure_details=execution.failure_details,
            )
        )
        return execution

    async def find_by_idempotency_key(self, key: str) -> AnalysisExecutionRecord | None:
        row = await self._fetch_one(
            select(_EXECUTIONS).where(_EXECUTIONS.c.idempotency_key == key)
        )
        return to_execution(row) if row else None

    async def next_attempt_sequence(self, analysis_id: str) -> int:
        current = await self._session.scalar(
            select(func.max(_EXECUTIONS.c.attempt_sequence)).where(
                _EXECUTIONS.c.analysis_id == analysis_id
            )
        )
        return int(current or 0) + 1

    async def count_active_for_analysis(self, analysis_id: str) -> int:
        total = await self._session.scalar(
            select(func.count()).where(
                _EXECUTIONS.c.analysis_id == analysis_id,
                _EXECUTIONS.c.state.in_([s.value for s in ACTIVE_EXECUTION_STATES]),
            )
        )
        return int(total or 0)

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        analysis_id: str | None = None,
        project_id: str | None = None,
        states: tuple[ExecutionState, ...] = (),
    ) -> Paged[AnalysisExecutionRecord]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        statement = select(_EXECUTIONS).where(_EXECUTIONS.c.workspace_id.in_(workspace_ids))
        if analysis_id is not None:
            statement = statement.where(_EXECUTIONS.c.analysis_id == analysis_id)
        if project_id is not None:
            statement = statement.where(_EXECUTIONS.c.project_id == project_id)
        if states:
            statement = statement.where(_EXECUTIONS.c.state.in_([s.value for s in states]))
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_EXECUTIONS.c.requested_at.desc())
            .limit(page.size)
            .offset(page.offset)
        )
        return Paged(items=tuple(to_execution(row) for row in rows), total=total, page=page)

    async def add_inputs(self, inputs: tuple[ExecutionInput, ...]) -> None:
        if not inputs:
            return
        await self._session.execute(
            insert(_EXECUTION_INPUTS),
            [
                {
                    "id": item.id or new_id("aein"),
                    "analysis_execution_id": item.analysis_execution_id,
                    "dataset_version_id": item.dataset_version_id,
                    "role": item.role,
                }
                for item in inputs
            ],
        )

    async def list_inputs(self, execution_id: str) -> tuple[ExecutionInput, ...]:
        rows = await self._fetch_all(
            select(_EXECUTION_INPUTS).where(
                _EXECUTION_INPUTS.c.analysis_execution_id == execution_id
            )
        )
        return tuple(
            ExecutionInput(
                id=row["id"],
                analysis_execution_id=row["analysis_execution_id"],
                dataset_version_id=row["dataset_version_id"],
                role=row["role"],
            )
            for row in rows
        )


__all__ = [
    "SqlAnalysisConfigurationRepository",
    "SqlAnalysisExecutionRepository",
    "SqlAnalysisRepository",
    "to_analysis",
    "to_configuration",
    "to_execution",
]
