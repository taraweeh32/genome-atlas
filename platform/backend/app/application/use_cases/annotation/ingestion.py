"""Ingesting an annotation payload produced by the scientific subsystem.

What happens, and why:

* the payload is matched to the run it claims to answer, and to the registered
  resource version it claims to come from — an unmatched payload is refused, never
  stored "as best we can";
* it is validated structurally: contract version, resource identity, checksum,
  reference context, declared fields and types, variant linkage, absence markers.
  Values are never repaired: a record that does not validate is rejected and the
  reason is stored as a finding;
* accepted values are written as ordinary Package 6 variant annotations, each row
  carrying its own resource identity and version, so two resources — or two
  versions of one resource — that disagree produce two rows and the reader sees
  both;
* a result version is registered for the annotated surface. An existing version is
  never overwritten: a re-run with an updated resource adds version *n+1* and the
  previous version is marked superseded but stays readable, which is what keeps a
  historical analysis reproducible;
* a redelivery of the same payload returns the original result version instead of
  storing it twice.

Large annotation output is not inlined. The payload references artifacts and an
analytical location; those references are stored and the bytes stay in object
storage and the analytical layer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.annotation.dependencies import (
    ANNOTATION_EXECUTE,
    AnnotationServices,
    resolve_scope,
)
from app.domain.annotation.entities import AnnotationResultVersionRecord
from app.domain.annotation.validation import validate_annotation_payload
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AnnotationResultState,
    AuditOutcome,
    ValidationSeverity,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.annotation import AnnotationPayload

REJECTION_VALIDATION = "annotation_payload_failed_validation"


@dataclass(frozen=True, slots=True)
class IngestAnnotationCommand:
    request: RequestContext
    payload: AnnotationPayload
    #: Present for a user-driven delivery; absent when a worker ingests.
    actor: ActorContext | None = None
    service_account_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class AnnotationResultView:
    result: AnnotationResultVersionRecord
    stored_record_count: int = 0
    rejected_record_count: int = 0
    findings: tuple[dict[str, Any], ...] = ()


class IngestAnnotationPayload:
    """Validate, store and version one annotation payload."""

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def execute(self, command: IngestAnnotationCommand) -> AnnotationResultView:
        payload = command.payload
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)

            run = await repositories.annotation_runs.get(payload.annotation_run_id)
            if run is None:
                raise NotFoundError("annotation_run", payload.annotation_run_id)

            # Scope comes from the run row, never from the payload: a producer
            # cannot address a workspace it was not run for.
            if command.actor is not None:
                await resolve_scope(
                    self._services,
                    repositories,
                    command.actor,
                    workspace_id=run.workspace_id,
                    project_id=run.project_id,
                    action=ANNOTATION_EXECUTE,
                    recorder=recorder,
                    occurred_at=now,
                )

            resource = await repositories.annotation_resources.get_by_version(
                resource_key=payload.resource.resource_key,
                version=payload.resource.resource_version,
            )
            if resource is None:
                raise NotFoundError(
                    "annotation_resource",
                    f"{payload.resource.resource_key}:{payload.resource.resource_version}",
                )

            profile_version = await repositories.annotation_profiles.get_version(
                run.profile_version_id
            )

            claimed = tuple(
                dict.fromkeys(record.variant_id for record in payload.records)
            )
            known: set[str] = set()
            for variant_id in claimed:
                if await repositories.variants.get(variant_id) is not None:
                    known.add(variant_id)

            outcome = validate_annotation_payload(
                payload=payload,
                run=run,
                resource=resource,
                profile_version=profile_version,
                known_variant_ids=frozenset(known),
                identifiers=lambda: new_id("avf"),
                now=now,
            )

            existing = await repositories.annotation_results.get_by_payload_digest(
                annotation_run_id=run.id, payload_digest=outcome.payload_digest
            )
            if existing is not None:
                # Producers retry. A redelivery must not create a second version.
                return AnnotationResultView(
                    result=existing,
                    stored_record_count=existing.stored_record_count,
                    rejected_record_count=existing.rejected_record_count,
                )

            # Large annotation output stays where it was written: the reference
            # is stored, the rows are not inlined here or in any API response.
            analytical = next(
                (a for a in payload.artifacts if a.analytical_location), None
            )
            analytical_location = analytical.analytical_location if analytical else None
            storage_uri = analytical.storage_uri if analytical else None
            row_count = (
                analytical.row_count
                if analytical and analytical.row_count is not None
                else payload.declared_record_count
            )

            previous = await repositories.annotation_results.latest_for_surface(
                resource_key=resource.resource_key,
                result_set_id=run.result_set_id,
                dataset_version_id=run.dataset_version_id,
            )
            next_number = (previous.version_number + 1) if previous else 1

            result = AnnotationResultVersionRecord(
                id=new_id("arv"),
                annotation_run_id=run.id,
                workspace_id=run.workspace_id,
                resource_id=resource.id,
                resource_key=resource.resource_key,
                resource_version=resource.version,
                version_number=next_number,
                state=AnnotationResultState.REGISTERED,
                project_id=run.project_id,
                result_set_id=run.result_set_id,
                dataset_version_id=run.dataset_version_id,
                profile_version_id=run.profile_version_id,
                scientific_execution_id=payload.scientific_execution_id,
                engine_resource_id=payload.engine_resource_id,
                engine_version=payload.engine_version,
                environment_version=payload.environment_version,
                container_image_digest=payload.container_image_digest,
                node_identity=payload.node_identity,
                genome_assembly=payload.genome_assembly,
                analytical_location=analytical_location,
                storage_uri=storage_uri,
                checksum_algorithm=payload.resource.checksum_algorithm,
                checksum_value=payload.resource.checksum_value,
                row_count=row_count,
                declared_record_count=payload.declared_record_count,
                # Counts are written once, at ingestion: a stored annotation
                # result version is never rewritten afterwards.
                stored_record_count=len(outcome.records),
                rejected_record_count=outcome.rejected_record_count,
                field_keys=outcome.field_keys,
                contract_version=payload.contract_version,
                payload_digest=outcome.payload_digest,
                # The run's frozen configuration digest is the reproducibility
                # anchor when the payload does not declare its own.
                parameters_digest=payload.parameters_digest or run.configuration_digest,
                completeness=payload.completeness,
                is_development_payload=payload.is_development_payload,
                supersedes_id=previous.id if previous else None,
                provenance={
                    "annotation_profile_version_id": run.profile_version_id,
                    "configuration_digest": run.configuration_digest,
                    "configuration_snapshot": dict(run.configuration_snapshot),
                    "resource_identity": {
                        "annotation_resource_id": resource.id,
                        "resource_key": resource.resource_key,
                        "resource_version": resource.version,
                        "schema_version": payload.resource.schema_version,
                    },
                    "scientific_execution_id": payload.scientific_execution_id,
                    "engine_version": payload.engine_version,
                    "environment_version": payload.environment_version,
                    "container_image_digest": payload.container_image_digest,
                    "node_identity": payload.node_identity,
                    "genome_assembly": payload.genome_assembly,
                    "parameters_digest": payload.parameters_digest,
                    "artifacts": [
                        {
                            "artifact_key": artifact.artifact_key,
                            "kind": artifact.kind,
                            "storage_uri": artifact.storage_uri,
                            "analytical_location": artifact.analytical_location,
                            "row_count": artifact.row_count,
                            "checksum_algorithm": artifact.checksum_algorithm,
                            "checksum_value": artifact.checksum_value,
                        }
                        for artifact in payload.artifacts
                    ],
                    "ingested_at": now.isoformat(),
                    "actor_user_id": command.actor.actor_id if command.actor else None,
                    "service_account_id": command.service_account_id,
                    "job_id": command.job_id,
                    "software_version": self._services.software_version,
                },
                metadata=dict(payload.metadata),
                ingested_at=now,
                created_at=now,
            )
            stored = await repositories.annotation_results.add(result)
            if outcome.findings:
                await repositories.annotation_results.add_findings(
                    tuple(
                        replace(finding, annotation_result_version_id=stored.id)
                        for finding in outcome.findings
                    )
                )

            findings_payload = tuple(
                {
                    "code": finding.code,
                    "message": finding.message,
                    "severity": finding.severity.value,
                    "field_key": finding.field_key,
                    "variant_id": finding.variant_id,
                    "record_index": finding.record_index,
                }
                for finding in outcome.findings
            )

            if outcome.is_rejected:
                blocking = outcome.blocking_finding
                stored = await repositories.annotation_results.save(stored.rejected())
                failed_run = await repositories.annotation_runs.save(
                    run.rejected(
                        at=now,
                        code=blocking.code if blocking else REJECTION_VALIDATION,
                        message=blocking.message
                        if blocking
                        else "the annotation payload failed validation",
                    )
                )
                await recorder.audit(
                    action="annotation_result.rejected",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    resource_type="annotation_result_version",
                    resource_id=stored.id,
                    workspace_id=stored.workspace_id,
                    project_id=stored.project_id,
                    new_state=stored.state.value,
                    detail={
                        "annotation_run_id": failed_run.id,
                        "rejection_code": failed_run.failure_code,
                        "finding_count": len(outcome.findings),
                    },
                )
                await recorder.event(
                    event_type=EventType.ANNOTATION_RESULT_REJECTED,
                    aggregate_type="annotation_result_version",
                    aggregate_id=stored.id,
                    occurred_at=now,
                    workspace_id=stored.workspace_id,
                    payload={"rejection_code": failed_run.failure_code},
                )
                raise ValidationError(
                    "the annotation payload failed validation",
                    details={"findings": list(findings_payload)},
                )

            # Values are stored as ordinary Package 6 annotation rows, each with
            # its own resource identity and version.
            if outcome.records:
                await repositories.variant_contexts.add_annotations(outcome.records)

            stored = await repositories.annotation_results.save(stored.validated())
            stored = await repositories.annotation_results.save(stored.available())
            if previous is not None and previous.state is not AnnotationResultState.REJECTED:
                # Superseded, not deleted: the older version stays readable so a
                # historical analysis keeps resolving.
                await repositories.annotation_results.save(
                    previous.superseded_by(stored.id)
                )

            completed = await repositories.annotation_runs.save(
                run.ingesting().completed(at=now, record_count=len(outcome.records))
                if not run.is_terminal
                else run
            )

            await recorder.audit(
                action="annotation_result.ingested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id if command.actor else None,
                resource_type="annotation_result_version",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                new_state=stored.state.value,
                detail={
                    "annotation_run_id": completed.id,
                    "resource_key": stored.resource_key,
                    "resource_version": stored.resource_version,
                    "version_number": stored.version_number,
                    "stored_record_count": stored.stored_record_count,
                    "rejected_record_count": stored.rejected_record_count,
                    "supersedes_id": stored.supersedes_id,
                    "payload_digest": stored.payload_digest,
                },
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_RESULT_INGESTED,
                aggregate_type="annotation_result_version",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={
                    "version_number": stored.version_number,
                    "resource_key": stored.resource_key,
                    "stored_record_count": stored.stored_record_count,
                },
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_RUN_COMPLETED,
                aggregate_type="annotation_run",
                aggregate_id=completed.id,
                occurred_at=now,
                workspace_id=completed.workspace_id,
                payload={"record_count": completed.record_count},
            )
            return AnnotationResultView(
                result=stored,
                stored_record_count=stored.stored_record_count,
                rejected_record_count=stored.rejected_record_count,
                findings=findings_payload,
            )


@dataclass(frozen=True, slots=True)
class AnnotationResultReader:
    """Reads of annotation result metadata, authorized through the run's scope."""

    services: AnnotationServices

    async def list_for_surface(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        result_set_id: str,
        page,
    ):
        now = self.services.clock.now()
        async with self.services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            result_set = await repositories.result_sets.get(result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", result_set_id)
            from app.application.use_cases.annotation.dependencies import (
                ANNOTATION_READ,
            )

            await resolve_scope(
                self.services,
                repositories,
                actor,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                action=ANNOTATION_READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.annotation_results.list_results(
                page=page, result_set_id=result_set_id
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, result_id: str
    ) -> AnnotationResultVersionRecord:
        now = self.services.clock.now()
        async with self.services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            result = await repositories.annotation_results.get(result_id)
            if result is None:
                raise NotFoundError("annotation_result_version", result_id)
            from app.application.use_cases.annotation.dependencies import (
                ANNOTATION_READ,
            )

            await resolve_scope(
                self.services,
                repositories,
                actor,
                workspace_id=result.workspace_id,
                project_id=result.project_id,
                action=ANNOTATION_READ,
                recorder=recorder,
                occurred_at=now,
            )
            if not result.is_readable and result.state is AnnotationResultState.REJECTED:
                raise ConflictError(
                    "this annotation result was rejected",
                    details={"state": result.state.value},
                )
            return result


__all__ = [
    "REJECTION_VALIDATION",
    "AnnotationResultReader",
    "AnnotationResultView",
    "IngestAnnotationCommand",
    "IngestAnnotationPayload",
    "ValidationSeverity",
]
