"""Immutable domain entities for analyses, executions, jobs, schedules, nodes.

Same conventions as the Package 3/4 entities: frozen dataclasses, no ORM types,
no transport types, and every state change expressed as a named method that
returns a *new* instance. A mutable row carries ``version`` for optimistic
concurrency; an append-only record does not carry one at all, because there is
nothing to overwrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ValidationError
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    AnalysisKind,
    AnalysisState,
    ConfigurationValidationState,
    DeletionState,
    ExecutionState,
    JobErrorClass,
    JobKind,
    JobQueue,
    JobState,
    MissedSchedulePolicy,
    NodeClass,
    NodeHealthState,
    NodeLifecycleState,
    ScheduleConcurrencyPolicy,
    ScheduleState,
    ScheduleTriggerOutcome,
    ScientificExecutionState,
)

#: Priority is a small bounded integer so no caller can starve every other
#: tenant by submitting ``priority = -10**9``. Lower value = sooner.
MIN_PRIORITY = 1
MAX_PRIORITY = 1000
DEFAULT_PRIORITY = 100


def clamp_priority(value: int | None) -> int:
    """Clamp instead of reject: a priority is a hint, never an authorization."""
    if value is None:
        return DEFAULT_PRIORITY
    return max(MIN_PRIORITY, min(MAX_PRIORITY, int(value)))


# --------------------------------------------------------------------------- #
# Analysis definition                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AnalysisDefinition:
    """What a user defined. Carries no execution state whatsoever."""

    id: str
    workspace_id: str
    project_id: str
    name: str
    kind: AnalysisKind
    state: AnalysisState
    created_by: str
    capability_key: str | None = None
    description: str | None = None
    owner_user_id: str | None = None
    current_configuration_id: str | None = None
    #: Queue/priority/retry/timeout defaults applied when an execution is
    #: requested without explicit overrides. Never scientific parameters.
    execution_defaults: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    deletion_state: DeletionState = DeletionState.ACTIVE
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    retention_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1

    @property
    def is_active(self) -> bool:
        return self.deletion_state is DeletionState.ACTIVE

    @property
    def is_executable(self) -> bool:
        """Only a definition with a current configuration may be executed."""
        return (
            self.is_active
            and self.state in (AnalysisState.READY, AnalysisState.ACTIVE)
            and self.current_configuration_id is not None
        )

    def rename(self, *, name: str, description: str | None) -> AnalysisDefinition:
        return replace(self, name=name, description=description)

    def with_state(self, target: AnalysisState) -> AnalysisDefinition:
        require_transition("analysis", self.state, target)
        return replace(self, state=target)

    def with_current_configuration(self, configuration_id: str) -> AnalysisDefinition:
        return replace(self, current_configuration_id=configuration_id)

    def with_execution_defaults(self, defaults: dict[str, Any]) -> AnalysisDefinition:
        return replace(self, execution_defaults=dict(defaults))

    def soft_deleted(
        self, *, at: datetime, by: str, retention_expires_at: datetime
    ) -> AnalysisDefinition:
        require_transition("deletion", self.deletion_state, DeletionState.SOFT_DELETED)
        return replace(
            self,
            deletion_state=DeletionState.SOFT_DELETED,
            deleted_at=at,
            deleted_by=by,
            retention_expires_at=retention_expires_at,
        )


# --------------------------------------------------------------------------- #
# Analysis configuration version                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AnalysisConfigurationVersion:
    """An immutable, numbered parameter set.

    Immutable by construction: there is no method that changes a scientific
    section. Editing a configuration always produces a new version, so an
    execution that referenced version 3 can still be reproduced after version 4
    exists. The only post-creation mutation is recording its *own* validation
    outcome, which happens once.
    """

    id: str
    analysis_id: str
    version_number: int
    created_by: str
    label: str | None = None
    filtering_configuration: dict[str, Any] = field(default_factory=dict)
    ranking_configuration: dict[str, Any] = field(default_factory=dict)
    annotation_configuration: dict[str, Any] = field(default_factory=dict)
    evidence_configuration: dict[str, Any] = field(default_factory=dict)
    interpretation_configuration: dict[str, Any] = field(default_factory=dict)
    reporting_configuration: dict[str, Any] = field(default_factory=dict)
    execution_parameters: dict[str, Any] = field(default_factory=dict)
    pipeline_resource_id: str | None = None
    engine_resource_id: str | None = None
    reference_genome_resource_id: str | None = None
    ruleset_resource_id: str | None = None
    execution_profile_resource_id: str | None = None
    validation_state: ConfigurationValidationState = ConfigurationValidationState.UNVALIDATED
    validation_findings: dict[str, Any] = field(default_factory=dict)
    #: Digest over the scientific sections. Two versions with the same hash are
    #: parameter-identical; it is never used to *replace* a version.
    content_hash: str | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    @property
    def is_valid(self) -> bool:
        return self.validation_state is ConfigurationValidationState.VALID

    def validated(self, findings: dict[str, Any] | None = None) -> AnalysisConfigurationVersion:
        return replace(
            self,
            validation_state=ConfigurationValidationState.VALID,
            validation_findings=dict(findings or {}),
        )

    def invalidated(self, findings: dict[str, Any]) -> AnalysisConfigurationVersion:
        return replace(
            self,
            validation_state=ConfigurationValidationState.INVALID,
            validation_findings=dict(findings),
        )


@dataclass(frozen=True, slots=True)
class ConfigurationInput:
    """A dataset version a configuration declares as input, with its role."""

    id: str
    analysis_configuration_id: str
    dataset_version_id: str
    role: str


# --------------------------------------------------------------------------- #
# Analysis execution                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AnalysisExecutionRecord:
    """One run. Append-only history; a re-run is a new row.

    ``configuration_snapshot`` is captured at request time and never rewritten,
    so a later configuration edit cannot change what this run actually used.
    """

    id: str
    analysis_id: str
    workspace_id: str
    project_id: str
    analysis_configuration_id: str
    attempt_sequence: int
    state: ExecutionState
    requested_at: datetime
    correlation_id: str
    requested_by: str | None = None
    configuration_snapshot: dict[str, Any] = field(default_factory=dict)
    capability_key: str | None = None
    capability_version: str | None = None
    queue: JobQueue = JobQueue.DEFAULT
    priority: int = DEFAULT_PRIORITY
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    schedule_id: str | None = None
    scheduled_for: datetime | None = None
    scheduled_job_id: str | None = None
    scientific_execution_id: str | None = None
    compute_node_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress_percent: int | None = None
    progress_message: str | None = None
    cancel_requested_at: datetime | None = None
    cancel_requested_by: str | None = None
    cancellation_reason: str | None = None
    execution_environment: dict[str, Any] = field(default_factory=dict)
    resource_profile: dict[str, Any] = field(default_factory=dict)
    scientific_versions: dict[str, Any] = field(default_factory=dict)
    failure_code: str | None = None
    failure_message: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        from app.domain.lifecycle import TERMINAL_EXECUTION_STATES

        return self.state in TERMINAL_EXECUTION_STATES

    def with_state(self, target: ExecutionState) -> AnalysisExecutionRecord:
        require_transition("analysis_execution", self.state, target)
        return replace(self, state=target)

    def queued(self, *, job_id: str) -> AnalysisExecutionRecord:
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, ExecutionState.QUEUED),
            scheduled_job_id=job_id,
        )

    def started(self, *, at: datetime, node_id: str | None = None) -> AnalysisExecutionRecord:
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, ExecutionState.RUNNING),
            started_at=self.started_at or at,
            compute_node_id=node_id or self.compute_node_id,
        )

    def submitted_to_engine(
        self, *, scientific_execution_id: str, node_id: str | None = None
    ) -> AnalysisExecutionRecord:
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, ExecutionState.SUBMITTED),
            scientific_execution_id=scientific_execution_id,
            compute_node_id=node_id or self.compute_node_id,
        )

    def with_progress(self, *, percent: int | None, message: str | None) -> AnalysisExecutionRecord:
        if percent is not None and not 0 <= percent <= 100:
            raise ValidationError(
                "progress percent must be between 0 and 100", details={"field": "progress_percent"}
            )
        return replace(self, progress_percent=percent, progress_message=message)

    def succeeded(
        self,
        *,
        at: datetime,
        environment: dict[str, Any] | None = None,
        scientific_versions: dict[str, Any] | None = None,
        resource_profile: dict[str, Any] | None = None,
    ) -> AnalysisExecutionRecord:
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, ExecutionState.SUCCEEDED),
            completed_at=at,
            progress_percent=100,
            execution_environment=dict(environment or self.execution_environment),
            scientific_versions=dict(scientific_versions or self.scientific_versions),
            resource_profile=dict(resource_profile or self.resource_profile),
        )

    def failed(
        self,
        *,
        at: datetime,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        timed_out: bool = False,
    ) -> AnalysisExecutionRecord:
        target = ExecutionState.TIMED_OUT if timed_out else ExecutionState.FAILED
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, target),
            completed_at=at,
            failure_code=code,
            failure_message=message,
            failure_details=dict(details or {}),
        )

    def requeued(self) -> AnalysisExecutionRecord:
        """A retryable failure returns the same execution to the queue."""
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, ExecutionState.QUEUED),
        )

    def cancellation_requested(
        self, *, at: datetime, by: str | None, reason: str | None
    ) -> AnalysisExecutionRecord:
        return replace(
            self,
            state=require_transition(
                "analysis_execution", self.state, ExecutionState.CANCEL_REQUESTED
            ),
            cancel_requested_at=at,
            cancel_requested_by=by,
            cancellation_reason=reason,
        )

    def cancelled(self, *, at: datetime) -> AnalysisExecutionRecord:
        return replace(
            self,
            state=require_transition("analysis_execution", self.state, ExecutionState.CANCELLED),
            completed_at=at,
        )


@dataclass(frozen=True, slots=True)
class ExecutionInput:
    """The exact dataset version an execution consumed, with its role."""

    id: str
    analysis_execution_id: str
    dataset_version_id: str
    role: str


# --------------------------------------------------------------------------- #
# Jobs                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class JobRecord:
    """A durable unit of background work.

    The lease fields are the whole basis of safe distributed execution: a job is
    held by exactly one worker until ``lease_expires_at``, and only a heartbeat
    extends that hold. Losing the worker therefore expires the hold instead of
    stranding the job forever.
    """

    id: str
    kind: JobKind
    state: JobState
    queue: JobQueue
    priority: int
    correlation_id: str
    attempt_number: int = 0
    max_attempts: int = 3
    payload: dict[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None
    project_id: str | None = None
    analysis_execution_id: str | None = None
    scientific_execution_id: str | None = None
    scheduled_job_id: str | None = None
    requested_by: str | None = None
    idempotency_key: str | None = None
    execution_context_ref: str | None = None
    available_at: datetime | None = None
    claimed_at: datetime | None = None
    claimed_by_worker_id: str | None = None
    assigned_node_id: str | None = None
    lease_expires_at: datetime | None = None
    lease_duration_seconds: int = 60
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_requested_by: str | None = None
    progress_percent: int | None = None
    progress_message: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)
    error_class: JobErrorClass | None = None
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()
    node_class: NodeClass = NodeClass.APPLICATION_WORKER
    causation_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1

    @property
    def is_terminal(self) -> bool:
        from app.domain.lifecycle import TERMINAL_JOB_STATES

        return self.state in TERMINAL_JOB_STATES

    @property
    def cancellation_requested(self) -> bool:
        return self.cancellation_requested_at is not None

    @property
    def attempts_remaining(self) -> int:
        return max(0, self.max_attempts - self.attempt_number)

    def lease_expired_at(self, moment: datetime) -> bool:
        return self.lease_expires_at is not None and self.lease_expires_at <= moment

    def with_state(self, target: JobState) -> JobRecord:
        require_transition("job", self.state, target)
        return replace(self, state=target)


@dataclass(frozen=True, slots=True)
class JobAttemptRecord:
    """Append-only attempt record. Never updated after it is written."""

    id: str
    job_id: str
    attempt_number: int
    state: JobState
    worker_id: str | None = None
    node_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    error_class: JobErrorClass | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Schedules                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AnalysisSchedule:
    """A recurring analysis definition. Each firing creates a new execution."""

    id: str
    name: str
    owner_scope: str
    owner_id: str | None
    job_kind: JobKind
    state: ScheduleState
    schedule_kind: str
    schedule_expression: str
    timezone_name: str
    concurrency_policy: ScheduleConcurrencyPolicy
    missed_policy: MissedSchedulePolicy
    analysis_id: str | None = None
    analysis_configuration_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    description: str | None = None
    queue: JobQueue = JobQueue.DEFAULT
    priority: int = DEFAULT_PRIORITY
    catch_up_limit: int = 1
    schedule_configuration: dict[str, Any] = field(default_factory=dict)
    next_execution_at: datetime | None = None
    previous_execution_at: datetime | None = None
    previous_job_id: str | None = None
    last_trigger_outcome: ScheduleTriggerOutcome | None = None
    consecutive_failure_count: int = 0
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1

    @property
    def is_enabled(self) -> bool:
        return self.state is ScheduleState.ENABLED

    def with_state(self, target: ScheduleState) -> AnalysisSchedule:
        require_transition("schedule", self.state, target)
        return replace(self, state=target)

    def with_next_execution(self, moment: datetime | None) -> AnalysisSchedule:
        return replace(self, next_execution_at=moment)

    def fired(
        self,
        *,
        at: datetime,
        next_execution_at: datetime | None,
        outcome: ScheduleTriggerOutcome,
        job_id: str | None = None,
    ) -> AnalysisSchedule:
        failures = (
            self.consecutive_failure_count + 1
            if outcome is ScheduleTriggerOutcome.FAILED
            else 0
        )
        return replace(
            self,
            previous_execution_at=at,
            previous_job_id=job_id or self.previous_job_id,
            next_execution_at=next_execution_at,
            last_trigger_outcome=outcome,
            consecutive_failure_count=failures,
        )


@dataclass(frozen=True, slots=True)
class ScheduleTrigger:
    """One firing of a schedule, recorded before any work is created.

    Uniqueness on ``(schedule_id, scheduled_for)`` is what makes recurring
    execution idempotent: two schedulers racing for the same slot cannot both
    create an execution.
    """

    id: str
    schedule_id: str
    scheduled_for: datetime
    outcome: ScheduleTriggerOutcome
    triggered_at: datetime
    analysis_execution_id: str | None = None
    job_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Compute / worker nodes                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ComputeNode:
    """A registered worker or scientific compute node.

    Application workers and scientific compute nodes are the same *registry* but
    never the same fleet: ``node_class`` keeps them apart, and a scientific job
    is never offered to an application worker.
    """

    id: str
    node_key: str
    node_class: NodeClass
    health_state: NodeHealthState
    lifecycle_state: NodeLifecycleState
    queues: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    resource_profile: dict[str, Any] = field(default_factory=dict)
    max_concurrency: int = 1
    active_job_count: int = 0
    engine_version: str | None = None
    environment_version: str | None = None
    heartbeat_at: datetime | None = None
    registered_at: datetime | None = None
    drained_at: datetime | None = None
    drain_reason: str | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1

    @property
    def has_capacity(self) -> bool:
        return self.active_job_count < self.max_concurrency

    @property
    def is_schedulable(self) -> bool:
        """Fail closed: only an active, healthy node with spare capacity."""
        return (
            self.lifecycle_state is NodeLifecycleState.ACTIVE
            and self.health_state is NodeHealthState.HEALTHY
            and self.has_capacity
        )

    def with_lifecycle(self, target: NodeLifecycleState) -> ComputeNode:
        require_transition("compute_node", self.lifecycle_state, target)
        return replace(self, lifecycle_state=target)

    def with_health(self, health: NodeHealthState, *, at: datetime | None = None) -> ComputeNode:
        return replace(self, health_state=health, heartbeat_at=at or self.heartbeat_at)


@dataclass(frozen=True, slots=True)
class ScientificExecutionRecord:
    """Local mirror of one scientific-subsystem run, kept for provenance."""

    id: str
    capability_key: str
    state: ScientificExecutionState
    submitted_at: datetime
    correlation_id: str
    analysis_execution_id: str | None = None
    job_id: str | None = None
    external_execution_id: str | None = None
    capability_version: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    resource_identities: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)

    def with_state(self, target: ScientificExecutionState) -> ScientificExecutionRecord:
        require_transition("scientific_execution", self.state, target)
        return replace(self, state=target)


@dataclass(frozen=True, slots=True)
class ScientificArtifactRecord:
    """A reference to an artifact a scientific execution produced.

    The bytes never enter the transactional database: this row records where the
    artifact lives, what it is, and how to verify it.
    """

    id: str
    scientific_execution_id: str
    artifact_key: str
    artifact_kind: str
    analytical_location: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "DEFAULT_PRIORITY",
    "MAX_PRIORITY",
    "MIN_PRIORITY",
    "AnalysisConfigurationVersion",
    "AnalysisDefinition",
    "AnalysisExecutionRecord",
    "AnalysisSchedule",
    "ComputeNode",
    "ConfigurationInput",
    "ExecutionInput",
    "JobAttemptRecord",
    "JobRecord",
    "ScheduleTrigger",
    "ScientificArtifactRecord",
    "ScientificExecutionRecord",
    "clamp_priority",
]
