"""Transport schemas for analyses, configurations, executions, jobs, schedules.

Same conventions as the dataset schemas: request payloads forbid unknown fields,
responses expose enum *values*, and nothing internal to execution custody
(worker ids, lease timestamps, storage locations) is serialized to a tenant
client. Administrative responses expose custody explicitly, because that is what
an operator is being asked to reason about.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel, Collection
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Analyses                                                                    #
# --------------------------------------------------------------------------- #


class AnalysisCreatePayload(ApiModel):
    project_id: str
    name: str = Field(min_length=1, max_length=255)
    kind: str
    description: str | None = Field(default=None, max_length=4000)
    capability_key: str | None = Field(default=None, max_length=128)


class AnalysisUpdatePayload(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    capability_key: str | None = Field(default=None, max_length=128)
    execution_defaults: dict[str, object] | None = None


class AnalysisLifecyclePayload(ApiModel):
    target: str = Field(description="Requested analysis state; the server decides validity.")


class AnalysisDeletePayload(ApiModel):
    reason: str | None = Field(default=None, max_length=1000)


class AnalysisResponse(ApiModel):
    id: str
    workspace_id: str
    project_id: str
    name: str
    kind: str
    state: str
    description: str | None
    capability_key: str | None
    current_configuration_id: str | None
    execution_defaults: dict[str, object]
    deletion_state: str
    is_executable: bool
    configuration_count: int
    active_execution_count: int
    capabilities: list[str]
    created_by: str
    created_at: datetime | None
    updated_at: datetime | None


class AnalysisCollection(Collection[AnalysisResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Configurations                                                              #
# --------------------------------------------------------------------------- #


class ConfigurationInputPayload(ApiModel):
    dataset_version_id: str
    role: str = Field(min_length=1, max_length=64)


class ConfigurationCreatePayload(ApiModel):
    label: str | None = Field(default=None, max_length=255)
    inputs: list[ConfigurationInputPayload] = Field(default_factory=list)
    filtering_configuration: dict[str, object] | None = None
    ranking_configuration: dict[str, object] | None = None
    annotation_configuration: dict[str, object] | None = None
    evidence_configuration: dict[str, object] | None = None
    interpretation_configuration: dict[str, object] | None = None
    reporting_configuration: dict[str, object] | None = None
    execution_parameters: dict[str, object] | None = None
    pipeline_resource_id: str | None = None
    engine_resource_id: str | None = None
    reference_genome_resource_id: str | None = None
    ruleset_resource_id: str | None = None
    execution_profile_resource_id: str | None = None
    activate: bool = False


class ConfigurationInputResponse(ApiModel):
    id: str
    dataset_version_id: str
    role: str


class ConfigurationResponse(ApiModel):
    id: str
    analysis_id: str
    version_number: int
    label: str | None
    validation_state: str
    validation_findings: dict[str, object]
    content_hash: str | None
    is_current: bool
    filtering_configuration: dict[str, object]
    ranking_configuration: dict[str, object]
    annotation_configuration: dict[str, object]
    evidence_configuration: dict[str, object]
    interpretation_configuration: dict[str, object]
    reporting_configuration: dict[str, object]
    execution_parameters: dict[str, object]
    pipeline_resource_id: str | None
    engine_resource_id: str | None
    reference_genome_resource_id: str | None
    ruleset_resource_id: str | None
    execution_profile_resource_id: str | None
    inputs: list[ConfigurationInputResponse]
    created_by: str
    created_at: datetime | None


class ConfigurationCollection(Collection[ConfigurationResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Executions                                                                  #
# --------------------------------------------------------------------------- #


class ExecutionRequestPayload(ApiModel):
    configuration_id: str | None = None
    queue: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    idempotency_key: str | None = Field(default=None, max_length=255)


class ExecutionCancelPayload(ApiModel):
    reason: str | None = Field(default=None, max_length=1000)


class ExecutionInputResponse(ApiModel):
    id: str
    dataset_version_id: str
    role: str


class ExecutionResponse(ApiModel):
    id: str
    analysis_id: str
    analysis_name: str | None
    workspace_id: str
    project_id: str
    analysis_configuration_id: str
    attempt_sequence: int
    state: str
    queue: str
    priority: int
    capability_key: str | None
    capability_version: str | None
    schedule_id: str | None
    scheduled_for: datetime | None
    scheduled_job_id: str | None
    scientific_execution_id: str | None
    compute_node_id: str | None
    progress_percent: int | None
    progress_message: str | None
    requested_by: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    correlation_id: str
    execution_environment: dict[str, object]
    scientific_versions: dict[str, object]
    resource_requirements: dict[str, object]
    failure_code: str | None
    failure_message: str | None
    inputs: list[ExecutionInputResponse]
    can_cancel: bool


class ExecutionCollection(Collection[ExecutionResponse]):
    page: PageMeta


class ScientificExecutionResponse(ApiModel):
    """Provenance mirror of one scientific run. Never scientific content."""

    id: str
    capability_key: str
    capability_version: str | None
    state: str
    external_execution_id: str | None
    engine_version: str | None
    environment_version: str | None
    container_image_digest: str | None
    node_identity: str | None
    resource_identities: dict[str, object]
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    artifacts: list[ScientificArtifactResponse]


class ScientificArtifactResponse(ApiModel):
    id: str
    artifact_key: str
    artifact_kind: str
    content_type: str | None
    size_bytes: int | None
    checksum_algorithm: str | None
    checksum_value: str | None


class ExecutionProvenanceResponse(ApiModel):
    execution: ExecutionResponse
    scientific_executions: list[ScientificExecutionResponse]
    configuration_snapshot: dict[str, object]


# --------------------------------------------------------------------------- #
# Jobs                                                                        #
# --------------------------------------------------------------------------- #


class JobCancelPayload(ApiModel):
    reason: str | None = Field(default=None, max_length=1000)


class JobAttemptResponse(ApiModel):
    attempt_number: int
    state: str
    worker_id: str | None
    node_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    error_class: str | None


class JobResponse(ApiModel):
    id: str
    kind: str
    state: str
    queue: str
    priority: int
    node_class: str
    workspace_id: str | None
    project_id: str | None
    analysis_execution_id: str | None
    attempt_number: int
    max_attempts: int
    available_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    progress_percent: int | None
    progress_message: str | None
    failure_code: str | None
    failure_message: str | None
    error_class: str | None
    cancellation_requested_at: datetime | None
    correlation_id: str
    created_at: datetime | None
    attempts: list[JobAttemptResponse]


class AdministrativeJobResponse(JobResponse):
    """Adds custody detail that only a platform operator is shown."""

    claimed_by_worker_id: str | None
    assigned_node_id: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    requested_by: str | None
    idempotency_key: str | None


class JobCollection(Collection[JobResponse]):
    page: PageMeta


class AdministrativeJobCollection(Collection[AdministrativeJobResponse]):
    page: PageMeta


class QueueStatisticResponse(ApiModel):
    queue: str
    state: str
    job_count: int
    oldest_available_at: datetime | None


class QueueStatisticsResponse(ApiModel):
    queues: list[QueueStatisticResponse]


# --------------------------------------------------------------------------- #
# Schedules                                                                   #
# --------------------------------------------------------------------------- #


class ScheduleCreatePayload(ApiModel):
    analysis_id: str
    name: str = Field(min_length=1, max_length=255)
    schedule_expression: str = Field(min_length=1, max_length=255)
    timezone_name: str = Field(default="UTC", max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    configuration_id: str | None = None
    concurrency_policy: str | None = None
    missed_policy: str | None = None
    queue: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    catch_up_limit: int = Field(default=1, ge=1, le=100)
    enabled: bool = True


class ScheduleUpdatePayload(ApiModel):
    schedule_expression: str | None = Field(default=None, min_length=1, max_length=255)
    timezone_name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    concurrency_policy: str | None = None
    missed_policy: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    catch_up_limit: int | None = Field(default=None, ge=1, le=100)


class ScheduleStatePayload(ApiModel):
    target: str


class ScheduleResponse(ApiModel):
    id: str
    name: str
    description: str | None
    analysis_id: str | None
    analysis_configuration_id: str | None
    workspace_id: str | None
    project_id: str | None
    state: str
    schedule_kind: str
    schedule_expression: str
    timezone_name: str
    concurrency_policy: str
    missed_policy: str
    queue: str
    priority: int
    catch_up_limit: int
    next_execution_at: datetime | None
    previous_execution_at: datetime | None
    last_trigger_outcome: str | None
    consecutive_failure_count: int
    can_manage: bool
    created_at: datetime | None
    updated_at: datetime | None


class ScheduleCollection(Collection[ScheduleResponse]):
    page: PageMeta


class ScheduleTriggerResponse(ApiModel):
    id: str
    scheduled_for: datetime
    triggered_at: datetime
    outcome: str
    analysis_execution_id: str | None
    job_id: str | None
    detail: dict[str, object]


class ScheduleTriggerCollection(Collection[ScheduleTriggerResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Compute nodes                                                               #
# --------------------------------------------------------------------------- #


class NodeLifecyclePayload(ApiModel):
    target: str
    reason: str | None = Field(default=None, max_length=1000)


class ComputeNodeResponse(ApiModel):
    id: str
    node_key: str
    node_class: str
    health_state: str
    lifecycle_state: str
    queues: list[str]
    capabilities: list[str]
    resource_profile: dict[str, object]
    max_concurrency: int
    active_job_count: int
    is_schedulable: bool
    engine_version: str | None
    environment_version: str | None
    heartbeat_at: datetime | None
    registered_at: datetime | None
    drained_at: datetime | None
    drain_reason: str | None
    last_error: str | None


class ComputeNodeListResponse(ApiModel):
    items: list[ComputeNodeResponse]


ScientificExecutionResponse.model_rebuild()
