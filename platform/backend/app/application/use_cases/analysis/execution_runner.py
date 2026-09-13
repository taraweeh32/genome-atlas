"""Runs one analysis execution: the application side of the scientific boundary.

This is the *only* place where an execution crosses into the scientific
subsystem, and it does so exclusively through the versioned contract in
``app.scientific.contracts``. It contains no scientific logic: it selects a node,
submits a declared capability with artifact references and parameters, observes
the outcome, and records provenance.

Invariants:

* The execution row moves ``queued → running → submitted → succeeded/failed``.
  Every transition is validated by the lifecycle map, so a completed run can
  never be rewritten.
* Provenance is written from what the subsystem *reported* — engine, environment,
  container digest, reference resources, node identity — never from what the
  application assumed.
* A cancellation request observed before or during submission ends the run as
  ``cancelled`` instead of fabricating a result.
* No node available is a *retryable* condition: the job returns to the queue with
  a structured reason rather than failing the analysis.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import AnalysisServices
from app.core.logging import get_logger
from app.domain.analysis.entities import (
    AnalysisExecutionRecord,
    ScientificArtifactRecord,
    ScientificExecutionRecord,
)
from app.domain.analysis.policies import ResourceRequirements, node_class_for
from app.domain.analysis.scheduling import select_node
from app.domain.errors import DependencyFailureError, NotFoundError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    ExecutionState,
    JobKind,
    ScientificExecutionState,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.contracts import (
    ArtifactReference,
    ExecutionStatus,
    ScientificExecutionRequest,
    ScientificExecutionResponse,
)

logger = get_logger(__name__)

#: How often the application asks the subsystem for the state of a submitted
#: execution, and how many times. Bounded: a run that never reports a terminal
#: state times out instead of holding a worker forever.
POLL_INTERVAL_SECONDS = 2.0
MAX_POLLS = 900

_TERMINAL_ENGINE_STATUSES = (
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELLED,
)


@dataclass(frozen=True, slots=True)
class RunExecutionCommand:
    analysis_execution_id: str
    request: RequestContext
    job_id: str | None = None
    worker_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunExecutionResult:
    execution: AnalysisExecutionRecord
    scientific_execution_id: str | None = None
    artifact_count: int = 0


class RunAnalysisExecution:
    def __init__(
        self,
        services: AnalysisServices,
        *,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        max_polls: int = MAX_POLLS,
    ) -> None:
        self._services = services
        self._poll_interval_seconds = poll_interval_seconds
        self._max_polls = max_polls

    async def execute(self, command: RunExecutionCommand) -> RunExecutionResult:
        gateway = self._services.scientific
        if gateway is None:
            raise DependencyFailureError(
                "the scientific integration is not configured for this process",
                details={"dependency": "scientific"},
            )
        now = self._services.clock.now()

        async with self._services.unit_of_work.begin() as repositories:
            execution = await repositories.analysis_executions.get(command.analysis_execution_id)
            if execution is None:
                raise NotFoundError("analysis_execution", command.analysis_execution_id)
            if execution.is_terminal:
                # A recovered or duplicated job must not re-run finished work.
                return RunExecutionResult(execution=execution)
            if execution.state is ExecutionState.CANCEL_REQUESTED:
                cancelled = await repositories.analysis_executions.save(
                    execution.cancelled(at=now)
                )
                await ActivityRecorder(repositories, command.request).event(
                    event_type=EventType.ANALYSIS_EXECUTION_CANCELLED,
                    aggregate_type="analysis_execution",
                    aggregate_id=cancelled.id,
                    occurred_at=now,
                    workspace_id=cancelled.workspace_id,
                )
                return RunExecutionResult(execution=cancelled)

            requirements = ResourceRequirements.from_mapping(execution.resource_requirements)
            node_class = node_class_for(JobKind.SCIENTIFIC_EXECUTION)
            nodes = await repositories.compute_nodes.list_nodes(node_class=node_class)
            selection = select_node(
                nodes,
                node_class=node_class,
                queue=execution.queue.value,
                requirements=requirements,
            )
            if not selection.selected:
                # Retryable by design: the analysis is fine, the fleet is busy or
                # mis-provisioned, and an operator gets the reason verbatim.
                raise DependencyFailureError(
                    "no compute node currently satisfies this execution",
                    details={
                        "reason": selection.reason,
                        "considered": list(selection.considered),
                        "node_class": node_class.value,
                        "requirements": requirements.as_mapping(),
                    },
                )
            node = selection.node
            assert node is not None
            # The execution stays queued until the subsystem has accepted it:
            # ``submitted`` then ``running`` is the order the lifecycle allows,
            # and it is also the truth — the application does not run the work.
            running = await repositories.analysis_executions.save(
                execution.assigned_to_node(node.id)
            )
            await ActivityRecorder(repositories, command.request).event(
                event_type=EventType.ANALYSIS_EXECUTION_STARTED,
                aggregate_type="analysis_execution",
                aggregate_id=running.id,
                occurred_at=now,
                workspace_id=running.workspace_id,
                payload={"node_key": node.node_key},
            )

        record, response = await self._submit(running, command, node_identity=node.node_key)
        if response is None:
            return RunExecutionResult(execution=running, scientific_execution_id=record.id)

        response = await self._await_terminal(response, command)
        return await self._finalize(running, record, response, command)

    # -- submission -------------------------------------------------------- #

    async def _submit(
        self,
        execution: AnalysisExecutionRecord,
        command: RunExecutionCommand,
        *,
        node_identity: str,
    ) -> tuple[ScientificExecutionRecord, ScientificExecutionResponse | None]:
        now = self._services.clock.now()
        snapshot = execution.configuration_snapshot or {}
        parameters = dict((snapshot.get("execution") or {}).get("parameters") or {})
        inputs = tuple(
            ArtifactReference(
                artifact_id=item["artifact_id"],
                kind=item.get("kind", "dataset_version"),
                storage_uri=item.get("storage_uri", ""),
                media_type=item.get("media_type"),
            )
            for item in (snapshot.get("inputs") or [])
            if isinstance(item, dict) and item.get("artifact_id")
        )
        record = ScientificExecutionRecord(
            id=new_id("sci"),
            capability_key=execution.capability_key or "integration.echo",
            capability_version=execution.capability_version,
            state=ScientificExecutionState.SUBMITTED,
            submitted_at=now,
            correlation_id=execution.correlation_id,
            analysis_execution_id=execution.id,
            job_id=command.job_id,
            node_identity=node_identity,
            parameters=parameters,
        )
        async with self._services.unit_of_work.begin() as repositories:
            await repositories.scientific_executions.add(record)

        response = await self._services.scientific.submit_execution(
            ScientificExecutionRequest(
                capability_id=record.capability_key,
                capability_version=record.capability_version,
                correlation_id=record.correlation_id,
                inputs=inputs,
                parameters=parameters,
                requested_by_execution_id=execution.id,
            )
        )
        async with self._services.unit_of_work.begin() as repositories:
            submitted = execution.submitted_to_engine(scientific_execution_id=record.id)
            if response.status is ExecutionStatus.RUNNING:
                submitted = submitted.started(at=now)
            await repositories.analysis_executions.save(submitted)
            await repositories.scientific_executions.record_outcome(
                self._merge(record, response, now=now)
            )
        return record, response

    async def _await_terminal(
        self, response: ScientificExecutionResponse, command: RunExecutionCommand
    ) -> ScientificExecutionResponse:
        polls = 0
        while response.status not in _TERMINAL_ENGINE_STATUSES:
            if polls >= self._max_polls:
                raise TimeoutError(
                    "the scientific subsystem did not report a terminal state in time"
                )
            if await self._cancellation_requested(command.analysis_execution_id):
                return ScientificExecutionResponse(
                    execution_id=response.execution_id,
                    status=ExecutionStatus.CANCELLED,
                    correlation_id=response.correlation_id,
                )
            await asyncio.sleep(self._poll_interval_seconds)
            polls += 1
            response = await self._services.scientific.get_execution(response.execution_id)
        return response

    async def _cancellation_requested(self, execution_id: str) -> bool:
        async with self._services.unit_of_work.begin() as repositories:
            current = await repositories.analysis_executions.get(execution_id)
        return current is not None and current.state is ExecutionState.CANCEL_REQUESTED

    # -- completion -------------------------------------------------------- #

    def _merge(
        self,
        record: ScientificExecutionRecord,
        response: ScientificExecutionResponse,
        *,
        now: datetime,
    ) -> ScientificExecutionRecord:
        """Fold the subsystem's report into the provenance mirror."""
        provenance = response.provenance
        state = {
            ExecutionStatus.ACCEPTED: ScientificExecutionState.SUBMITTED,
            ExecutionStatus.RUNNING: ScientificExecutionState.RUNNING,
            ExecutionStatus.SUCCEEDED: ScientificExecutionState.SUCCEEDED,
            ExecutionStatus.FAILED: ScientificExecutionState.FAILED,
            ExecutionStatus.CANCELLED: ScientificExecutionState.CANCELLED,
        }[response.status]
        resources = {
            resource.resource_id: {
                "version": resource.resource_version,
                "genome_assembly": resource.genome_assembly,
                "checksum": resource.checksum,
            }
            for resource in (provenance.reference_resources if provenance else ())
        }
        failure = response.failure
        return ScientificExecutionRecord(
            id=record.id,
            capability_key=record.capability_key,
            capability_version=record.capability_version,
            state=state,
            submitted_at=record.submitted_at,
            correlation_id=record.correlation_id,
            analysis_execution_id=record.analysis_execution_id,
            job_id=record.job_id,
            external_execution_id=response.execution_id,
            engine_version=provenance.engine.engine_version if provenance else None,
            environment_version=(
                provenance.environment.environment_version if provenance else None
            ),
            container_image_digest=(
                provenance.environment.container_digest if provenance else None
            ),
            node_identity=record.node_identity,
            resource_identities=resources,
            parameters=record.parameters,
            started_at=provenance.started_at if provenance else None,
            completed_at=(
                provenance.completed_at
                if provenance and provenance.completed_at
                else (now if state is not ScientificExecutionState.RUNNING else None)
            ),
            failure_code=failure.code if failure else None,
            failure_message=failure.message if failure else None,
            failure_details=dict(failure.details) if failure else {},
        )

    async def _finalize(
        self,
        execution: AnalysisExecutionRecord,
        record: ScientificExecutionRecord,
        response: ScientificExecutionResponse,
        command: RunExecutionCommand,
    ) -> RunExecutionResult:
        now = self._services.clock.now()
        provenance = response.provenance
        environment: dict[str, Any] = {}
        versions: dict[str, Any] = {}
        if provenance is not None:
            environment = {
                "environment_id": provenance.environment.environment_id,
                "environment_version": provenance.environment.environment_version,
                "container_digest": provenance.environment.container_digest,
                "node_identity": record.node_identity,
            }
            versions = {
                "engine_id": provenance.engine.engine_id,
                "engine_version": provenance.engine.engine_version,
                "build_revision": provenance.engine.build_revision,
                "capability_key": record.capability_key,
                "capability_version": record.capability_version,
                "reference_resources": {
                    resource.resource_id: resource.resource_version
                    for resource in provenance.reference_resources
                },
            }

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            current = await repositories.analysis_executions.get(execution.id)
            if current is None:
                raise NotFoundError("analysis_execution", execution.id)
            await repositories.scientific_executions.record_outcome(
                self._merge(record, response, now=now)
            )
            artifacts = tuple(
                ScientificArtifactRecord(
                    id=new_id("sart"),
                    scientific_execution_id=record.id,
                    artifact_key=artifact.artifact_id,
                    artifact_kind=artifact.kind,
                    analytical_location=artifact.storage_uri,
                    content_type=artifact.media_type,
                    size_bytes=artifact.size_bytes,
                    checksum_value=artifact.checksum,
                )
                for artifact in response.artifacts
            )
            if artifacts:
                await repositories.scientific_executions.record_artifacts(artifacts)

            if response.status is ExecutionStatus.SUCCEEDED:
                final = await repositories.analysis_executions.save(
                    current.succeeded(
                        at=now,
                        environment=environment,
                        scientific_versions=versions,
                    )
                )
                await recorder.event(
                    event_type=EventType.ANALYSIS_EXECUTION_SUCCEEDED,
                    aggregate_type="analysis_execution",
                    aggregate_id=final.id,
                    occurred_at=now,
                    workspace_id=final.workspace_id,
                    payload={"artifacts": len(artifacts)},
                )
            elif response.status is ExecutionStatus.CANCELLED:
                final = await repositories.analysis_executions.save(current.cancelled(at=now))
                await recorder.event(
                    event_type=EventType.ANALYSIS_EXECUTION_CANCELLED,
                    aggregate_type="analysis_execution",
                    aggregate_id=final.id,
                    occurred_at=now,
                    workspace_id=final.workspace_id,
                )
            else:
                failure = response.failure
                final = await repositories.analysis_executions.save(
                    current.failed(
                        at=now,
                        code=failure.code if failure else "scientific.execution_failed",
                        message=(
                            failure.message
                            if failure
                            else "the scientific subsystem reported a failure"
                        ),
                        details=dict(failure.details) if failure else {},
                    )
                )
                await recorder.event(
                    event_type=EventType.ANALYSIS_EXECUTION_FAILED,
                    aggregate_type="analysis_execution",
                    aggregate_id=final.id,
                    occurred_at=now,
                    workspace_id=final.workspace_id,
                    payload={"failure_code": final.failure_code},
                )
                if failure is not None and failure.retryable:
                    # Let the job subsystem decide whether attempts remain; the
                    # execution records the failure either way.
                    raise DependencyFailureError(
                        failure.message,
                        details={"code": failure.code, **dict(failure.details)},
                    )
        return RunExecutionResult(
            execution=final,
            scientific_execution_id=record.id,
            artifact_count=len(artifacts),
        )


__all__ = [
    "MAX_POLLS",
    "POLL_INTERVAL_SECONDS",
    "RunAnalysisExecution",
    "RunExecutionCommand",
    "RunExecutionResult",
]
