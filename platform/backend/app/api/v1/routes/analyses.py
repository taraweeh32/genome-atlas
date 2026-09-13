"""Analysis, configuration, execution, job, schedule and compute-node endpoints.

Thin handlers, as everywhere else in this API: parse transport input, hand an
explicit command to a use case, shape the result. No handler decides access, a
state transition or a scope — the use case resolves the owning workspace/project
from the stored row and requires the permission there.

Three boundaries are visible in the layout:

* Requesting an execution is a *request*, never an execution. The API returns a
  queued execution; durable work happens in a worker.
* Cancellation is likewise a request. Only the worker's own observation turns it
  into a terminal cancelled state.
* Job custody (worker id, lease expiry, assigned node) is administrative
  information and is served only from the platform routes, never to a tenant.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.analysis_mapping import (
    administrative_job_response,
    analysis_response,
    compute_node_response,
    configuration_response,
    execution_response,
    job_response,
    queue_statistic_response,
    schedule_response,
    schedule_trigger_response,
    scientific_execution_response,
)
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.schemas.analysis import (
    AdministrativeJobCollection,
    AdministrativeJobResponse,
    AnalysisCollection,
    AnalysisCreatePayload,
    AnalysisDeletePayload,
    AnalysisLifecyclePayload,
    AnalysisResponse,
    AnalysisUpdatePayload,
    ComputeNodeListResponse,
    ComputeNodeResponse,
    ConfigurationCollection,
    ConfigurationCreatePayload,
    ConfigurationResponse,
    ExecutionCancelPayload,
    ExecutionCollection,
    ExecutionProvenanceResponse,
    ExecutionRequestPayload,
    ExecutionResponse,
    JobCancelPayload,
    JobCollection,
    JobResponse,
    NodeLifecyclePayload,
    QueueStatisticsResponse,
    ScheduleCollection,
    ScheduleCreatePayload,
    ScheduleResponse,
    ScheduleStatePayload,
    ScheduleTriggerCollection,
    ScheduleUpdatePayload,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.application.use_cases.analysis.configurations import (
    ActivateConfiguration,
    ActivateConfigurationCommand,
    ConfigurationInputRequest,
    CreateConfigurationVersion,
    CreateConfigurationVersionCommand,
    GetConfiguration,
    GetConfigurationQuery,
    ListConfigurations,
    ListConfigurationsQuery,
)
from app.application.use_cases.analysis.definitions import (
    ChangeAnalysisState,
    ChangeAnalysisStateCommand,
    CreateAnalysis,
    CreateAnalysisCommand,
    DeleteAnalysis,
    DeleteAnalysisCommand,
    GetAnalysis,
    GetAnalysisQuery,
    ListAnalyses,
    ListAnalysesQuery,
    UpdateAnalysis,
    UpdateAnalysisCommand,
)
from app.application.use_cases.analysis.executions import (
    CancelExecution,
    CancelExecutionCommand,
    GetExecution,
    GetExecutionProvenance,
    GetExecutionProvenanceQuery,
    GetExecutionQuery,
    ListExecutions,
    ListExecutionsQuery,
    RequestExecution,
    RequestExecutionCommand,
)
from app.application.use_cases.analysis.jobs import (
    CancelJob,
    CancelJobCommand,
    GetJob,
    GetJobQuery,
    GetQueueStatistics,
    GetQueueStatisticsQuery,
    ListJobs,
    ListJobsQuery,
    ListPlatformJobs,
    ListPlatformJobsQuery,
)
from app.application.use_cases.analysis.nodes import (
    ChangeNodeLifecycle,
    ChangeNodeLifecycleCommand,
    ListNodes,
    ListNodesQuery,
)
from app.application.use_cases.analysis.schedules import (
    ChangeScheduleState,
    ChangeScheduleStateCommand,
    CreateSchedule,
    CreateScheduleCommand,
    ListSchedules,
    ListSchedulesQuery,
    ListScheduleTriggers,
    ListScheduleTriggersQuery,
    UpdateSchedule,
    UpdateScheduleCommand,
)
from app.domain.value_objects.enums import (
    AnalysisKind,
    AnalysisState,
    ExecutionState,
    JobKind,
    JobQueue,
    JobState,
    MissedSchedulePolicy,
    NodeClass,
    NodeLifecycleState,
    ScheduleConcurrencyPolicy,
    ScheduleState,
)

router = APIRouter(prefix="/analyses", tags=["analyses"])
executions_router = APIRouter(prefix="/analysis-executions", tags=["analyses"])
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])
schedules_router = APIRouter(prefix="/analysis-schedules", tags=["schedules"])
platform_jobs_router = APIRouter(prefix="/administration/jobs", tags=["administration"])
compute_router = APIRouter(prefix="/administration/compute-nodes", tags=["administration"])


def _states[EnumT](enum_type: type[EnumT], raw: list[str] | None, *, field: str) -> tuple[EnumT, ...]:
    return tuple(parse_enum(enum_type, item, field=field) for item in raw or ())


# --------------------------------------------------------------------------- #
# Analysis definitions                                                        #
# --------------------------------------------------------------------------- #


@router.post(
    "",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an analysis definition",
    responses=ERROR_RESPONSES,
)
async def create_analysis(
    payload: AnalysisCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnalysisResponse:
    view = await CreateAnalysis(container.analysis_services()).execute(
        CreateAnalysisCommand(
            actor=caller.actor,
            workspace_id="",
            project_id=payload.project_id,
            name=payload.name,
            kind=parse_enum(AnalysisKind, payload.kind, field="kind"),
            description=payload.description,
            capability_key=payload.capability_key,
            request=context,
        )
    )
    return analysis_response(view)


@router.get(
    "",
    response_model=AnalysisCollection,
    summary="List analyses in a workspace or project",
    responses=ERROR_RESPONSES,
)
async def list_analyses(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> AnalysisCollection:
    paged = await ListAnalyses(container.analysis_services()).execute(
        ListAnalysesQuery(
            actor=caller.actor,
            page=page,
            request=context,
            workspace_id=workspace_id,
            project_id=project_id,
            states=_states(AnalysisState, state, field="state"),
            query=query,
        )
    )
    return AnalysisCollection(
        items=[analysis_response(view) for view in paged.items], page=page_meta(paged)
    )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Get an analysis definition",
    responses=ERROR_RESPONSES,
)
async def get_analysis(
    analysis_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnalysisResponse:
    view = await GetAnalysis(container.analysis_services()).execute(
        GetAnalysisQuery(actor=caller.actor, analysis_id=analysis_id, request=context)
    )
    return analysis_response(view)


@router.patch(
    "/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Update analysis metadata and execution defaults",
    responses=ERROR_RESPONSES,
)
async def update_analysis(
    analysis_id: str,
    payload: AnalysisUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnalysisResponse:
    view = await UpdateAnalysis(container.analysis_services()).execute(
        UpdateAnalysisCommand(
            actor=caller.actor,
            analysis_id=analysis_id,
            request=context,
            name=payload.name,
            description=payload.description,
            capability_key=payload.capability_key,
            execution_defaults=(
                dict(payload.execution_defaults)
                if payload.execution_defaults is not None
                else None
            ),
        )
    )
    return analysis_response(view)


@router.post(
    "/{analysis_id}/state",
    response_model=AnalysisResponse,
    summary="Request an analysis lifecycle transition",
    responses=ERROR_RESPONSES,
)
async def change_analysis_state(
    analysis_id: str,
    payload: AnalysisLifecyclePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnalysisResponse:
    view = await ChangeAnalysisState(container.analysis_services()).execute(
        ChangeAnalysisStateCommand(
            actor=caller.actor,
            analysis_id=analysis_id,
            target=parse_enum(AnalysisState, payload.target, field="target"),
            request=context,
        )
    )
    return analysis_response(view)


@router.post(
    "/{analysis_id}/deletion",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an analysis definition",
    responses=ERROR_RESPONSES,
)
async def delete_analysis(
    analysis_id: str,
    payload: AnalysisDeletePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await DeleteAnalysis(container.analysis_services()).execute(
        DeleteAnalysisCommand(
            actor=caller.actor,
            analysis_id=analysis_id,
            reason=payload.reason,
            request=context,
        )
    )


# --------------------------------------------------------------------------- #
# Configurations                                                              #
# --------------------------------------------------------------------------- #


@router.post(
    "/{analysis_id}/configurations",
    response_model=ConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new analysis configuration version",
    responses=ERROR_RESPONSES,
)
async def create_configuration(
    analysis_id: str,
    payload: ConfigurationCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ConfigurationResponse:
    view = await CreateConfigurationVersion(container.analysis_services()).execute(
        CreateConfigurationVersionCommand(
            actor=caller.actor,
            analysis_id=analysis_id,
            request=context,
            label=payload.label,
            inputs=tuple(
                ConfigurationInputRequest(
                    dataset_version_id=item.dataset_version_id, role=item.role
                )
                for item in payload.inputs
            ),
            filtering_configuration=payload.filtering_configuration,
            ranking_configuration=payload.ranking_configuration,
            annotation_configuration=payload.annotation_configuration,
            evidence_configuration=payload.evidence_configuration,
            interpretation_configuration=payload.interpretation_configuration,
            reporting_configuration=payload.reporting_configuration,
            execution_parameters=payload.execution_parameters,
            pipeline_resource_id=payload.pipeline_resource_id,
            engine_resource_id=payload.engine_resource_id,
            reference_genome_resource_id=payload.reference_genome_resource_id,
            ruleset_resource_id=payload.ruleset_resource_id,
            execution_profile_resource_id=payload.execution_profile_resource_id,
            activate=payload.activate,
        )
    )
    return configuration_response(view)


@router.get(
    "/{analysis_id}/configurations",
    response_model=ConfigurationCollection,
    summary="List analysis configuration versions",
    responses=ERROR_RESPONSES,
)
async def list_configurations(
    analysis_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> ConfigurationCollection:
    paged = await ListConfigurations(container.analysis_services()).execute(
        ListConfigurationsQuery(
            actor=caller.actor, analysis_id=analysis_id, page=page, request=context
        )
    )
    return ConfigurationCollection(
        items=[configuration_response(view) for view in paged.items], page=page_meta(paged)
    )


@router.get(
    "/{analysis_id}/configurations/{configuration_id}",
    response_model=ConfigurationResponse,
    summary="Get one analysis configuration version",
    responses=ERROR_RESPONSES,
)
async def get_configuration(
    analysis_id: str,
    configuration_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ConfigurationResponse:
    view = await GetConfiguration(container.analysis_services()).execute(
        GetConfigurationQuery(
            actor=caller.actor,
            analysis_id=analysis_id,
            configuration_id=configuration_id,
            request=context,
        )
    )
    return configuration_response(view)


@router.post(
    "/{analysis_id}/configurations/{configuration_id}/activation",
    response_model=ConfigurationResponse,
    summary="Make a configuration version the analysis' current configuration",
    responses=ERROR_RESPONSES,
)
async def activate_configuration(
    analysis_id: str,
    configuration_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ConfigurationResponse:
    view = await ActivateConfiguration(container.analysis_services()).execute(
        ActivateConfigurationCommand(
            actor=caller.actor,
            analysis_id=analysis_id,
            configuration_id=configuration_id,
            request=context,
        )
    )
    return configuration_response(view)


# --------------------------------------------------------------------------- #
# Executions                                                                  #
# --------------------------------------------------------------------------- #


@router.post(
    "/{analysis_id}/executions",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an analysis execution",
    responses=ERROR_RESPONSES,
)
async def request_execution(
    analysis_id: str,
    payload: ExecutionRequestPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ExecutionResponse:
    view = await RequestExecution(container.analysis_services()).execute(
        RequestExecutionCommand(
            actor=caller.actor,
            analysis_id=analysis_id,
            request=context,
            configuration_id=payload.configuration_id,
            queue=(
                parse_enum(JobQueue, payload.queue, field="queue") if payload.queue else None
            ),
            priority=payload.priority,
            idempotency_key=payload.idempotency_key,
        )
    )
    return execution_response(view)


@executions_router.get(
    "",
    response_model=ExecutionCollection,
    summary="List analysis executions",
    responses=ERROR_RESPONSES,
)
async def list_executions(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    analysis_id: Annotated[str | None, Query()] = None,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
) -> ExecutionCollection:
    paged = await ListExecutions(container.analysis_services()).execute(
        ListExecutionsQuery(
            actor=caller.actor,
            page=page,
            request=context,
            analysis_id=analysis_id,
            workspace_id=workspace_id,
            project_id=project_id,
            states=_states(ExecutionState, state, field="state"),
        )
    )
    return ExecutionCollection(
        items=[execution_response(view) for view in paged.items], page=page_meta(paged)
    )


@executions_router.get(
    "/{execution_id}",
    response_model=ExecutionResponse,
    summary="Get an analysis execution",
    responses=ERROR_RESPONSES,
)
async def get_execution(
    execution_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ExecutionResponse:
    view = await GetExecution(container.analysis_services()).execute(
        GetExecutionQuery(actor=caller.actor, execution_id=execution_id, request=context)
    )
    return execution_response(view)


@executions_router.get(
    "/{execution_id}/provenance",
    response_model=ExecutionProvenanceResponse,
    summary="Get the recorded provenance of an execution",
    responses=ERROR_RESPONSES,
)
async def get_execution_provenance(
    execution_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ExecutionProvenanceResponse:
    view = await GetExecutionProvenance(container.analysis_services()).execute(
        GetExecutionProvenanceQuery(
            actor=caller.actor, execution_id=execution_id, request=context
        )
    )
    return ExecutionProvenanceResponse(
        execution=execution_response(view.execution),
        scientific_executions=[
            scientific_execution_response(record, artifacts)
            for record, artifacts in view.scientific_executions
        ],
        configuration_snapshot=dict(view.configuration_snapshot),
    )


@executions_router.post(
    "/{execution_id}/cancellation",
    response_model=ExecutionResponse,
    summary="Request cancellation of an analysis execution",
    responses=ERROR_RESPONSES,
)
async def cancel_execution(
    execution_id: str,
    payload: ExecutionCancelPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ExecutionResponse:
    view = await CancelExecution(container.analysis_services()).execute(
        CancelExecutionCommand(
            actor=caller.actor,
            execution_id=execution_id,
            reason=payload.reason,
            request=context,
        )
    )
    return execution_response(view)


# --------------------------------------------------------------------------- #
# Jobs (tenant-visible monitoring)                                            #
# --------------------------------------------------------------------------- #


@jobs_router.get(
    "",
    response_model=JobCollection,
    summary="List jobs a caller may observe",
    responses=ERROR_RESPONSES,
)
async def list_jobs(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    queue: Annotated[str | None, Query(max_length=64)] = None,
) -> JobCollection:
    paged = await ListJobs(container.analysis_services()).execute(
        ListJobsQuery(
            actor=caller.actor,
            page=page,
            request=context,
            workspace_id=workspace_id,
            project_id=project_id,
            states=_states(JobState, state, field="state"),
            kinds=_states(JobKind, kind, field="kind"),
            queue=queue,
        )
    )
    return JobCollection(items=[job_response(view) for view in paged.items], page=page_meta(paged))


@jobs_router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get a job a caller may observe",
    responses=ERROR_RESPONSES,
)
async def get_job(
    job_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> JobResponse:
    view = await GetJob(container.analysis_services()).execute(
        GetJobQuery(actor=caller.actor, job_id=job_id, request=context)
    )
    return job_response(view)


# --------------------------------------------------------------------------- #
# Schedules                                                                   #
# --------------------------------------------------------------------------- #


@schedules_router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring analysis schedule",
    responses=ERROR_RESPONSES,
)
async def create_schedule(
    payload: ScheduleCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ScheduleResponse:
    command = CreateScheduleCommand(
        actor=caller.actor,
        analysis_id=payload.analysis_id,
        name=payload.name,
        schedule_expression=payload.schedule_expression,
        timezone_name=payload.timezone_name,
        request=context,
        description=payload.description,
        configuration_id=payload.configuration_id,
        queue=(parse_enum(JobQueue, payload.queue, field="queue") if payload.queue else None),
        priority=payload.priority,
        catch_up_limit=payload.catch_up_limit,
        enabled=payload.enabled,
        **(
            {
                "concurrency_policy": parse_enum(
                    ScheduleConcurrencyPolicy,
                    payload.concurrency_policy,
                    field="concurrency_policy",
                )
            }
            if payload.concurrency_policy
            else {}
        ),
        **(
            {
                "missed_policy": parse_enum(
                    MissedSchedulePolicy, payload.missed_policy, field="missed_policy"
                )
            }
            if payload.missed_policy
            else {}
        ),
    )
    view = await CreateSchedule(container.analysis_services()).execute(command)
    return schedule_response(view)


@schedules_router.get(
    "",
    response_model=ScheduleCollection,
    summary="List analysis schedules",
    responses=ERROR_RESPONSES,
)
async def list_schedules(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
) -> ScheduleCollection:
    paged = await ListSchedules(container.analysis_services()).execute(
        ListSchedulesQuery(
            actor=caller.actor,
            page=page,
            request=context,
            workspace_id=workspace_id,
            project_id=project_id,
            states=_states(ScheduleState, state, field="state"),
        )
    )
    return ScheduleCollection(
        items=[schedule_response(view) for view in paged.items], page=page_meta(paged)
    )


@schedules_router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update a schedule",
    responses=ERROR_RESPONSES,
)
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ScheduleResponse:
    view = await UpdateSchedule(container.analysis_services()).execute(
        UpdateScheduleCommand(
            actor=caller.actor,
            schedule_id=schedule_id,
            request=context,
            schedule_expression=payload.schedule_expression,
            timezone_name=payload.timezone_name,
            description=payload.description,
            priority=payload.priority,
            catch_up_limit=payload.catch_up_limit,
            concurrency_policy=(
                parse_enum(
                    ScheduleConcurrencyPolicy,
                    payload.concurrency_policy,
                    field="concurrency_policy",
                )
                if payload.concurrency_policy
                else None
            ),
            missed_policy=(
                parse_enum(MissedSchedulePolicy, payload.missed_policy, field="missed_policy")
                if payload.missed_policy
                else None
            ),
        )
    )
    return schedule_response(view)


@schedules_router.post(
    "/{schedule_id}/state",
    response_model=ScheduleResponse,
    summary="Enable, disable or archive a schedule",
    responses=ERROR_RESPONSES,
)
async def change_schedule_state(
    schedule_id: str,
    payload: ScheduleStatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ScheduleResponse:
    view = await ChangeScheduleState(container.analysis_services()).execute(
        ChangeScheduleStateCommand(
            actor=caller.actor,
            schedule_id=schedule_id,
            target=parse_enum(ScheduleState, payload.target, field="target"),
            request=context,
        )
    )
    return schedule_response(view)


@schedules_router.get(
    "/{schedule_id}/triggers",
    response_model=ScheduleTriggerCollection,
    summary="List recorded firings of a schedule",
    responses=ERROR_RESPONSES,
)
async def list_schedule_triggers(
    schedule_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> ScheduleTriggerCollection:
    paged = await ListScheduleTriggers(container.analysis_services()).execute(
        ListScheduleTriggersQuery(
            actor=caller.actor, schedule_id=schedule_id, page=page, request=context
        )
    )
    return ScheduleTriggerCollection(
        items=[schedule_trigger_response(trigger) for trigger in paged.items],
        page=page_meta(paged),
    )


# --------------------------------------------------------------------------- #
# Administrative job and compute control                                      #
# --------------------------------------------------------------------------- #


@platform_jobs_router.get(
    "",
    response_model=AdministrativeJobCollection,
    summary="List jobs across the platform",
    responses=ERROR_RESPONSES,
)
async def list_platform_jobs(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    state: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    queue: Annotated[str | None, Query(max_length=64)] = None,
) -> AdministrativeJobCollection:
    paged = await ListPlatformJobs(container.analysis_services()).execute(
        ListPlatformJobsQuery(
            actor=caller.actor,
            page=page,
            request=context,
            states=_states(JobState, state, field="state"),
            kinds=_states(JobKind, kind, field="kind"),
            queue=queue,
        )
    )
    return AdministrativeJobCollection(
        items=[administrative_job_response(view) for view in paged.items], page=page_meta(paged)
    )


@platform_jobs_router.get(
    "/queues",
    response_model=QueueStatisticsResponse,
    summary="Queue depth and age per state",
    responses=ERROR_RESPONSES,
)
async def get_queue_statistics(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> QueueStatisticsResponse:
    rows = await GetQueueStatistics(container.analysis_services()).execute(
        GetQueueStatisticsQuery(actor=caller.actor, request=context)
    )
    return QueueStatisticsResponse(queues=[queue_statistic_response(row) for row in rows])


@platform_jobs_router.post(
    "/{job_id}/cancellation",
    response_model=AdministrativeJobResponse,
    summary="Request cancellation of a job",
    responses=ERROR_RESPONSES,
)
async def cancel_job(
    job_id: str,
    payload: JobCancelPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AdministrativeJobResponse:
    view = await CancelJob(container.analysis_services()).execute(
        CancelJobCommand(
            actor=caller.actor, job_id=job_id, reason=payload.reason, request=context
        )
    )
    return administrative_job_response(view)


@compute_router.get(
    "",
    response_model=ComputeNodeListResponse,
    summary="List registered compute and worker nodes",
    responses=ERROR_RESPONSES,
)
async def list_compute_nodes(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    node_class: Annotated[str | None, Query()] = None,
) -> ComputeNodeListResponse:
    nodes = await ListNodes(container.analysis_services()).execute(
        ListNodesQuery(
            actor=caller.actor,
            request=context,
            node_class=(
                parse_enum(NodeClass, node_class, field="node_class") if node_class else None
            ),
        )
    )
    return ComputeNodeListResponse(items=[compute_node_response(node) for node in nodes])


@compute_router.post(
    "/{node_id}/lifecycle",
    response_model=ComputeNodeResponse,
    summary="Drain, reactivate or retire a node",
    responses=ERROR_RESPONSES,
)
async def change_node_lifecycle(
    node_id: str,
    payload: NodeLifecyclePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ComputeNodeResponse:
    node = await ChangeNodeLifecycle(container.analysis_services()).execute(
        ChangeNodeLifecycleCommand(
            actor=caller.actor,
            node_id=node_id,
            target=parse_enum(NodeLifecycleState, payload.target, field="target"),
            reason=payload.reason,
            request=context,
        )
    )
    return compute_node_response(node)
