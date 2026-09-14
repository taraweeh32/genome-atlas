"""Requesting, submitting and reading annotation runs.

The chain, and why it has these steps:

``RequestAnnotationRun``
  → the annotated surface is resolved and **its** tenancy decides authorization;
  → the profile version is read and its configuration is *frozen onto the run*, so
    editing the profile afterwards cannot change what this run claims;
  → a durable ``annotation_execution`` job is enqueued in the same transaction, so
    a committed run always has its job and a rolled-back one has neither.

``SubmitAnnotationRun`` (the job handler's use case)
  → the existing scientific gateway is asked for the declared capability, with
    structured inputs only: artifact references, pinned resource versions,
    reference context, parameters and provenance context. No command, no script,
    no scientific decision is expressed here;
  → the identities the subsystem reports are recorded on the run.

Nothing in this module computes, predicts or interprets anything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.annotation.dependencies import (
    ANNOTATION_EXECUTE,
    ANNOTATION_READ,
    AnnotationServices,
    readable_workspace_scope,
    resolve_scope,
    resolve_surface,
)
from app.domain.analysis.policies import default_queue_for, node_class_for
from app.domain.annotation.entities import (
    AnnotationProfileVersionRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, InfrastructureError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AnnotationRunState,
    AuditOutcome,
    JobKind,
    QueryDefinitionState,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.contracts import (
    ArtifactReference,
    ExecutionStatus,
    ScientificExecutionRequest,
)

EXECUTION_JOB_KIND = JobKind.ANNOTATION_EXECUTION

FAILURE_SUBMISSION = "scientific_submission_failed"
FAILURE_REJECTED = "scientific_execution_rejected"


def _configuration_snapshot(
    version: AnnotationProfileVersionRecord,
    *,
    field_dictionary_version: str | None,
) -> dict[str, Any]:
    """Everything needed to explain this run later, copied at request time."""
    return {
        "annotation_profile_id": version.profile_id,
        "annotation_profile_version_id": version.id,
        "annotation_profile_version_number": version.version_number,
        "capability_id": version.capability_id,
        "capability_version": version.capability_version,
        "configuration_digest": version.configuration_digest,
        "genome_assembly": version.genome_assembly,
        "reference_genome_resource_id": version.reference_genome_resource_id,
        "engine_resource_id": version.engine_resource_id,
        "engine_version": version.engine_version,
        "parameters": dict(version.parameters),
        "provenance_requirements": list(version.provenance_requirements),
        "required_inputs": list(version.required_inputs),
        "output_field_keys": list(version.output_field_keys),
        "field_dictionary_version": field_dictionary_version,
        "resources": [
            {
                "annotation_resource_id": binding.resource_id,
                "resource_key": binding.resource_key,
                "resource_version": binding.resource_version,
                "category": binding.category.value if binding.category else None,
                "role": binding.role,
            }
            for binding in version.resources
        ],
    }


@dataclass(frozen=True, slots=True)
class RequestRunCommand:
    actor: ActorContext
    request: RequestContext
    annotation_profile_id: str
    result_set_id: str | None = None
    dataset_version_id: str | None = None
    #: Pins a specific profile version. Omitted means the profile's latest.
    profile_version_number: int | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AnnotationRunView:
    run: AnnotationRunRecord
    findings: tuple[AnnotationValidationFinding, ...] = ()


class RequestAnnotationRun:
    """Record one annotation run and enqueue its durable execution job."""

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def execute(self, command: RequestRunCommand) -> AnnotationRunView:
        now = self._services.clock.now()
        if (command.result_set_id is None) == (command.dataset_version_id is None):
            raise ValidationError(
                "name exactly one surface to annotate",
                details={"field": "result_set_id"},
            )
        dictionary_version = (
            self._services.dictionary.snapshot().version
            if self._services.dictionary is not None
            else None
        )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            surface = await resolve_surface(
                repositories,
                result_set_id=command.result_set_id,
                dataset_version_id=command.dataset_version_id,
            )
            scope = await resolve_scope(
                self._services,
                repositories,
                command.actor,
                workspace_id=surface.workspace_id,
                project_id=surface.project_id,
                action=ANNOTATION_EXECUTE,
                recorder=recorder,
                occurred_at=now,
            )

            if command.idempotency_key:
                # A retried request returns the original run: annotation is
                # expensive, and two runs for one request would double-charge the
                # compute subsystem and produce two result versions.
                existing = await repositories.annotation_runs.get_by_idempotency_key(
                    workspace_id=surface.workspace_id,
                    idempotency_key=command.idempotency_key,
                )
                if existing is not None:
                    return AnnotationRunView(run=existing)

            profile = await repositories.annotation_profiles.get(
                command.annotation_profile_id
            )
            if profile is None:
                raise NotFoundError(
                    "annotation_profile", command.annotation_profile_id
                )
            if profile.state is QueryDefinitionState.ARCHIVED:
                raise ConflictError(
                    "this annotation profile is archived",
                    details={"state": profile.state.value},
                )
            number = command.profile_version_number or profile.latest_version_number
            if number < 1:
                raise ConflictError("this annotation profile has no version yet")
            version = await repositories.annotation_profiles.get_version_number(
                profile_id=profile.id, version_number=number
            )
            if version is None:
                raise NotFoundError(
                    "annotation_profile_version", f"{profile.id}:{number}"
                )
            if surface.input_kind not in version.required_inputs:
                raise ConflictError(
                    "this profile version does not accept this input kind",
                    details={
                        "input_kind": surface.input_kind,
                        "required_inputs": list(version.required_inputs),
                    },
                )
            if (
                version.genome_assembly
                and surface.genome_assembly
                and version.genome_assembly != surface.genome_assembly
            ):
                # Annotating GRCh38 values onto a GRCh37 surface is not a warning.
                raise ConflictError(
                    "the profile's reference context does not match the surface",
                    details={
                        "profile_genome_assembly": version.genome_assembly,
                        "surface_genome_assembly": surface.genome_assembly,
                    },
                )

            run = AnnotationRunRecord(
                id=new_id("aru"),
                workspace_id=surface.workspace_id,
                profile_id=profile.id,
                profile_version_id=version.id,
                profile_version_number=version.version_number,
                state=AnnotationRunState.REQUESTED,
                project_id=surface.project_id,
                result_set_id=surface.result_set_id,
                dataset_version_id=surface.dataset_version_id,
                requested_by=scope.actor.actor_id,
                requested_at=now,
                capability_id=version.capability_id,
                capability_version=version.capability_version,
                engine_resource_id=version.engine_resource_id,
                engine_version=version.engine_version,
                genome_assembly=version.genome_assembly,
                configuration_snapshot=_configuration_snapshot(
                    version, field_dictionary_version=dictionary_version
                ),
                configuration_digest=version.configuration_digest,
                correlation_id=command.request.correlation_id,
                idempotency_key=command.idempotency_key,
                metadata=dict(command.metadata or {}),
                created_at=now,
            )
            stored = await repositories.annotation_runs.add(run)
            # From here the version is frozen for good: it has been used.
            await repositories.annotation_profiles.mark_version_referenced(version.id)

            job_id = await repositories.jobs.enqueue(
                kind=EXECUTION_JOB_KIND,
                payload={"annotation_run_id": stored.id},
                correlation_id=command.request.correlation_id,
                queue=default_queue_for(EXECUTION_JOB_KIND).value,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                idempotency_key=f"annotation-execution:{stored.id}",
                node_class=node_class_for(EXECUTION_JOB_KIND),
            )
            stored = await repositories.annotation_runs.save(
                replace(stored, job_id=job_id)
            )

            await recorder.audit(
                action="annotation_run.requested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="annotation_run",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                new_state=stored.state.value,
                detail={
                    "annotation_profile_id": profile.id,
                    "profile_version_number": version.version_number,
                    "configuration_digest": stored.configuration_digest,
                    "result_set_id": stored.result_set_id,
                    "dataset_version_id": stored.dataset_version_id,
                },
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_RUN_REQUESTED,
                aggregate_type="annotation_run",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={
                    "annotation_profile_version_id": version.id,
                    "capability_id": version.capability_id,
                },
            )
            return AnnotationRunView(run=stored)


class SubmitAnnotationRun:
    """Submit a requested run to the scientific subsystem through the gateway.

    Called by the ``annotation_execution`` job handler, never from a request. The
    request it builds carries identities and parameters only — the subsystem
    decides how to compute, and this application never expresses a command.
    """

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def execute(
        self, *, annotation_run_id: str, request: RequestContext
    ) -> AnnotationRunRecord:
        if self._services.scientific is None:
            raise InfrastructureError("the scientific gateway is not configured")
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            run = await repositories.annotation_runs.get(annotation_run_id)
            if run is None:
                raise NotFoundError("annotation_run", annotation_run_id)
            if run.is_terminal or run.state is not AnnotationRunState.REQUESTED:
                # Job retries must not resubmit work that already moved on.
                return run
            surface_location = None
            if run.result_set_id:
                result_set = await repositories.result_sets.get(run.result_set_id)
                surface_location = (
                    result_set.analytical_location if result_set else None
                )

        snapshot = dict(run.configuration_snapshot)
        inputs: tuple[ArtifactReference, ...] = ()
        if surface_location:
            inputs = (
                ArtifactReference(
                    artifact_id=run.result_set_id or run.dataset_version_id or run.id,
                    kind="variant_surface",
                    storage_uri=surface_location,
                    media_type="application/vnd.apache.parquet",
                ),
            )
        execution_request = ScientificExecutionRequest(
            capability_id=run.capability_id or snapshot.get("capability_id", ""),
            capability_version=run.capability_version,
            correlation_id=run.correlation_id or request.correlation_id,
            inputs=inputs,
            parameters={
                "annotation_run_id": run.id,
                "annotation_profile_version_id": run.profile_version_id,
                "configuration_digest": run.configuration_digest,
                "reference_context": {
                    "genome_assembly": snapshot.get("genome_assembly"),
                    "reference_genome_resource_id": snapshot.get(
                        "reference_genome_resource_id"
                    ),
                },
                "annotation_resources": snapshot.get("resources", []),
                "output_requirements": {
                    "field_keys": snapshot.get("output_field_keys", []),
                    "contract": "annotation",
                },
                "parameters": snapshot.get("parameters", {}),
                "provenance_context": {
                    "workspace_id": run.workspace_id,
                    "project_id": run.project_id,
                    "requested_by": run.requested_by,
                    "requested_at": run.requested_at.isoformat()
                    if run.requested_at
                    else None,
                    "software_version": self._services.software_version,
                },
            },
        )

        try:
            response = await self._services.scientific.submit_execution(
                execution_request
            )
        except Exception as error:
            async with self._services.unit_of_work.begin() as repositories:
                recorder = ActivityRecorder(repositories, request)
                failed = await repositories.annotation_runs.save(
                    run.failed(
                        at=now, code=FAILURE_SUBMISSION, message=str(error)
                    )
                )
                await self._record_failure(recorder, failed, now=now)
            raise

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            current = await repositories.annotation_runs.get(run.id) or run
            if response.status is ExecutionStatus.FAILED:
                failure = response.failure
                stored = await repositories.annotation_runs.save(
                    current.failed(
                        at=now,
                        code=failure.code if failure else FAILURE_REJECTED,
                        message=failure.message if failure else "execution failed",
                    )
                )
                await self._record_failure(recorder, stored, now=now)
                return stored
            if response.status is ExecutionStatus.CANCELLED:
                return await repositories.annotation_runs.save(current.cancelled(at=now))

            provenance = response.provenance
            stored = current.submitted(
                at=now,
                scientific_execution_id=None,
                external_execution_id=response.execution_id,
            )
            stored = replace(
                stored,
                engine_resource_id=(
                    provenance.engine.engine_id if provenance else stored.engine_resource_id
                ),
                engine_version=(
                    provenance.engine.engine_version
                    if provenance
                    else stored.engine_version
                ),
                environment_version=(
                    provenance.environment.environment_version if provenance else None
                ),
                container_image_digest=(
                    provenance.environment.container_digest if provenance else None
                ),
            )
            stored = await repositories.annotation_runs.save(stored)
            await recorder.audit(
                action="annotation_run.submitted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                resource_type="annotation_run",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                previous_state=current.state.value,
                new_state=stored.state.value,
                detail={
                    "external_execution_id": stored.external_execution_id,
                    "capability_id": stored.capability_id,
                    "engine_version": stored.engine_version,
                },
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_RUN_SUBMITTED,
                aggregate_type="annotation_run",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={"external_execution_id": stored.external_execution_id},
            )
            return stored

    async def _record_failure(
        self, recorder: ActivityRecorder, run: AnnotationRunRecord, *, now
    ) -> None:
        await recorder.audit(
            action="annotation_run.failed",
            outcome=AuditOutcome.FAILURE,
            occurred_at=now,
            resource_type="annotation_run",
            resource_id=run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            new_state=run.state.value,
            detail={
                "failure_code": run.failure_code,
                "failure_message": run.failure_message,
            },
        )
        await recorder.event(
            event_type=EventType.ANNOTATION_RUN_FAILED,
            aggregate_type="annotation_run",
            aggregate_id=run.id,
            occurred_at=now,
            workspace_id=run.workspace_id,
            payload={"failure_code": run.failure_code},
        )


@dataclass(frozen=True, slots=True)
class ListRunsQuery:
    actor: ActorContext
    request: RequestContext
    page: Page
    workspace_id: str | None = None
    project_id: str | None = None
    result_set_id: str | None = None
    state: AnnotationRunState | None = None


class AnnotationRunReader:
    """Reads of annotation runs, always through the caller's own grants."""

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def list(self, query: ListRunsQuery) -> Paged[AnnotationRunRecord]:
        workspaces = frozenset(
            readable_workspace_scope(query.actor, workspace_id=query.workspace_id)
        )
        async with self._services.unit_of_work.begin() as repositories:
            if not workspaces:
                return Paged(items=(), total=0, page=query.page)
            return await repositories.annotation_runs.list_runs(
                page=query.page,
                workspace_ids=workspaces,
                project_id=query.project_id,
                result_set_id=query.result_set_id,
                state=query.state,
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, run_id: str
    ) -> AnnotationRunView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            run = await repositories.annotation_runs.get(run_id)
            if run is None:
                raise NotFoundError("annotation_run", run_id)
            # Authorized through the run's own scope, so knowing an identifier is
            # never enough.
            await resolve_scope(
                self._services,
                repositories,
                actor,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                action=ANNOTATION_READ,
                recorder=recorder,
                occurred_at=now,
            )
            findings = await repositories.annotation_results.list_findings(
                annotation_run_id=run.id, page=Page(number=1, size=100)
            )
            return AnnotationRunView(run=run, findings=findings.items)

    async def cancel(
        self, actor: ActorContext, request: RequestContext, run_id: str
    ) -> AnnotationRunRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            run = await repositories.annotation_runs.get(run_id)
            if run is None:
                raise NotFoundError("annotation_run", run_id)
            scope = await resolve_scope(
                self._services,
                repositories,
                actor,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                action=ANNOTATION_EXECUTE,
                recorder=recorder,
                occurred_at=now,
            )
            if run.is_terminal:
                raise ConflictError(
                    "this annotation run has already finished",
                    details={"state": run.state.value},
                )
            stored = await repositories.annotation_runs.save(run.cancelled(at=now))
            await recorder.audit(
                action="annotation_run.cancelled",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="annotation_run",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                previous_state=run.state.value,
                new_state=stored.state.value,
            )
            return stored


__all__ = [
    "EXECUTION_JOB_KIND",
    "AnnotationRunReader",
    "AnnotationRunView",
    "ListRunsQuery",
    "RequestAnnotationRun",
    "RequestRunCommand",
    "SubmitAnnotationRun",
]
