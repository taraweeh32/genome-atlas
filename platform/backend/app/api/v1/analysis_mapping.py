"""Mapping between analysis/job domain records and their transport schemas.

Deliberately one-directional and explicit: every field a client sees is named
here, so adding a domain field never leaks it to an API response by accident.
Execution custody (worker id, lease expiry, assigned node) appears only in the
administrative variant.
"""

from __future__ import annotations

from typing import Any

from app.api.v1.schemas.analysis import (
    AdministrativeJobResponse,
    AnalysisResponse,
    ComputeNodeResponse,
    ConfigurationInputResponse,
    ConfigurationResponse,
    ExecutionInputResponse,
    ExecutionResponse,
    JobAttemptResponse,
    JobResponse,
    QueueStatisticResponse,
    ScheduleResponse,
    ScheduleTriggerResponse,
    ScientificArtifactResponse,
    ScientificExecutionResponse,
)
from app.domain.analysis.entities import (
    ComputeNode,
    JobAttemptRecord,
    JobRecord,
    ScheduleTrigger,
    ScientificArtifactRecord,
    ScientificExecutionRecord,
)


def _plain(value: dict[str, Any] | None) -> dict[str, object]:
    return dict(value or {})


def analysis_response(view) -> AnalysisResponse:
    analysis = view.analysis
    return AnalysisResponse(
        id=analysis.id,
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        name=analysis.name,
        kind=analysis.kind.value,
        state=analysis.state.value,
        description=analysis.description,
        capability_key=analysis.capability_key,
        current_configuration_id=analysis.current_configuration_id,
        execution_defaults=_plain(analysis.execution_defaults),
        deletion_state=analysis.deletion_state.value,
        is_executable=analysis.is_executable,
        configuration_count=view.configuration_count,
        active_execution_count=view.active_execution_count,
        capabilities=list(view.capabilities),
        created_by=analysis.created_by,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


def configuration_response(view) -> ConfigurationResponse:
    configuration = view.configuration
    return ConfigurationResponse(
        id=configuration.id,
        analysis_id=configuration.analysis_id,
        version_number=configuration.version_number,
        label=configuration.label,
        validation_state=configuration.validation_state.value,
        validation_findings=_plain(configuration.validation_findings),
        content_hash=configuration.content_hash,
        is_current=view.is_current,
        filtering_configuration=_plain(configuration.filtering_configuration),
        ranking_configuration=_plain(configuration.ranking_configuration),
        annotation_configuration=_plain(configuration.annotation_configuration),
        evidence_configuration=_plain(configuration.evidence_configuration),
        interpretation_configuration=_plain(configuration.interpretation_configuration),
        reporting_configuration=_plain(configuration.reporting_configuration),
        execution_parameters=_plain(configuration.execution_parameters),
        pipeline_resource_id=configuration.pipeline_resource_id,
        engine_resource_id=configuration.engine_resource_id,
        reference_genome_resource_id=configuration.reference_genome_resource_id,
        ruleset_resource_id=configuration.ruleset_resource_id,
        execution_profile_resource_id=configuration.execution_profile_resource_id,
        inputs=[
            ConfigurationInputResponse(
                id=item.id, dataset_version_id=item.dataset_version_id, role=item.role
            )
            for item in view.inputs
        ],
        created_by=configuration.created_by,
        created_at=configuration.created_at,
    )


def execution_response(view) -> ExecutionResponse:
    execution = view.execution
    return ExecutionResponse(
        id=execution.id,
        analysis_id=execution.analysis_id,
        analysis_name=view.analysis_name,
        workspace_id=execution.workspace_id,
        project_id=execution.project_id,
        analysis_configuration_id=execution.analysis_configuration_id,
        attempt_sequence=execution.attempt_sequence,
        state=execution.state.value,
        queue=execution.queue.value,
        priority=execution.priority,
        capability_key=execution.capability_key,
        capability_version=execution.capability_version,
        schedule_id=execution.schedule_id,
        scheduled_for=execution.scheduled_for,
        scheduled_job_id=execution.scheduled_job_id,
        scientific_execution_id=execution.scientific_execution_id,
        compute_node_id=execution.compute_node_id,
        progress_percent=execution.progress_percent,
        progress_message=execution.progress_message,
        requested_by=execution.requested_by,
        requested_at=execution.requested_at,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        correlation_id=execution.correlation_id,
        execution_environment=_plain(execution.execution_environment),
        scientific_versions=_plain(execution.scientific_versions),
        resource_requirements=_plain(execution.resource_requirements),
        failure_code=execution.failure_code,
        failure_message=execution.failure_message,
        inputs=[
            ExecutionInputResponse(
                id=item.id, dataset_version_id=item.dataset_version_id, role=item.role
            )
            for item in view.inputs
        ],
        can_cancel=view.can_cancel,
    )


def scientific_artifact_response(
    artifact: ScientificArtifactRecord,
) -> ScientificArtifactResponse:
    # ``analytical_location`` is intentionally omitted: a storage URI is not a
    # tenant-facing fact, and access to bytes goes through an authorized
    # download endpoint, never through a provenance response.
    return ScientificArtifactResponse(
        id=artifact.id,
        artifact_key=artifact.artifact_key,
        artifact_kind=artifact.artifact_kind,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        checksum_algorithm=artifact.checksum_algorithm,
        checksum_value=artifact.checksum_value,
    )


def scientific_execution_response(
    record: ScientificExecutionRecord,
    artifacts: tuple[ScientificArtifactRecord, ...] = (),
) -> ScientificExecutionResponse:
    return ScientificExecutionResponse(
        id=record.id,
        capability_key=record.capability_key,
        capability_version=record.capability_version,
        state=record.state.value,
        external_execution_id=record.external_execution_id,
        engine_version=record.engine_version,
        environment_version=record.environment_version,
        container_image_digest=record.container_image_digest,
        node_identity=record.node_identity,
        resource_identities=_plain(getattr(record, "resource_identities", None)),
        submitted_at=record.submitted_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        failure_code=record.failure_code,
        failure_message=record.failure_message,
        artifacts=[scientific_artifact_response(item) for item in artifacts],
    )


def _attempts(attempts: tuple[JobAttemptRecord, ...]) -> list[JobAttemptResponse]:
    return [
        JobAttemptResponse(
            attempt_number=attempt.attempt_number,
            state=attempt.state.value,
            worker_id=attempt.worker_id,
            node_id=attempt.node_id,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            failure_code=attempt.failure_code,
            failure_message=attempt.failure_message,
            error_class=attempt.error_class.value if attempt.error_class else None,
        )
        for attempt in attempts
    ]


def _job_fields(job: JobRecord) -> dict[str, object]:
    return {
        "id": job.id,
        "kind": job.kind.value,
        "state": job.state.value,
        "queue": job.queue.value,
        "priority": job.priority,
        "node_class": job.node_class.value,
        "workspace_id": job.workspace_id,
        "project_id": job.project_id,
        "analysis_execution_id": job.analysis_execution_id,
        "attempt_number": job.attempt_number,
        "max_attempts": job.max_attempts,
        "available_at": job.available_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "progress_percent": job.progress_percent,
        "progress_message": job.progress_message,
        "failure_code": job.failure_code,
        "failure_message": job.failure_message,
        "error_class": job.error_class.value if job.error_class else None,
        "cancellation_requested_at": job.cancellation_requested_at,
        "correlation_id": job.correlation_id,
        "created_at": job.created_at,
    }


def job_response(view) -> JobResponse:
    return JobResponse(**_job_fields(view.job), attempts=_attempts(view.attempts))


def administrative_job_response(view) -> AdministrativeJobResponse:
    job = view.job
    return AdministrativeJobResponse(
        **_job_fields(job),
        attempts=_attempts(view.attempts),
        claimed_by_worker_id=job.claimed_by_worker_id,
        assigned_node_id=job.assigned_node_id,
        lease_expires_at=job.lease_expires_at,
        heartbeat_at=job.heartbeat_at,
        requested_by=job.requested_by,
        idempotency_key=job.idempotency_key,
    )


def queue_statistic_response(row: dict[str, Any]) -> QueueStatisticResponse:
    return QueueStatisticResponse(
        queue=str(row.get("queue")),
        state=str(row.get("state")),
        job_count=int(row.get("job_count") or 0),
        oldest_available_at=row.get("oldest_available_at"),
    )


def schedule_response(view) -> ScheduleResponse:
    schedule = view.schedule
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        analysis_id=schedule.analysis_id,
        analysis_configuration_id=schedule.analysis_configuration_id,
        workspace_id=schedule.workspace_id,
        project_id=schedule.project_id,
        state=schedule.state.value,
        schedule_kind=schedule.schedule_kind,
        schedule_expression=schedule.schedule_expression,
        timezone_name=schedule.timezone_name,
        concurrency_policy=schedule.concurrency_policy.value,
        missed_policy=schedule.missed_policy.value,
        queue=schedule.queue.value,
        priority=schedule.priority,
        catch_up_limit=schedule.catch_up_limit,
        next_execution_at=schedule.next_execution_at,
        previous_execution_at=schedule.previous_execution_at,
        last_trigger_outcome=(
            schedule.last_trigger_outcome.value if schedule.last_trigger_outcome else None
        ),
        consecutive_failure_count=schedule.consecutive_failure_count,
        can_manage=view.can_manage,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def schedule_trigger_response(trigger: ScheduleTrigger) -> ScheduleTriggerResponse:
    return ScheduleTriggerResponse(
        id=trigger.id,
        scheduled_for=trigger.scheduled_for,
        triggered_at=trigger.triggered_at,
        outcome=trigger.outcome.value,
        analysis_execution_id=trigger.analysis_execution_id,
        job_id=trigger.job_id,
        detail=_plain(trigger.detail),
    )


def compute_node_response(node: ComputeNode) -> ComputeNodeResponse:
    return ComputeNodeResponse(
        id=node.id,
        node_key=node.node_key,
        node_class=node.node_class.value,
        health_state=node.health_state.value,
        lifecycle_state=node.lifecycle_state.value,
        queues=list(node.queues),
        capabilities=list(node.capabilities),
        resource_profile=_plain(node.resource_profile),
        max_concurrency=node.max_concurrency,
        active_job_count=node.active_job_count,
        is_schedulable=node.is_schedulable,
        engine_version=node.engine_version,
        environment_version=node.environment_version,
        heartbeat_at=node.heartbeat_at,
        registered_at=node.registered_at,
        drained_at=node.drained_at,
        drain_reason=node.drain_reason,
        last_error=node.last_error,
    )


__all__ = [
    "administrative_job_response",
    "analysis_response",
    "compute_node_response",
    "configuration_response",
    "execution_response",
    "job_response",
    "queue_statistic_response",
    "schedule_response",
    "schedule_trigger_response",
    "scientific_execution_response",
]
