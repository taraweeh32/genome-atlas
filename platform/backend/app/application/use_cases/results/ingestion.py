"""Ingesting a scientific execution's result surface.

The chain, and why it has this many steps:

``ResultPayload`` (engine, versioned contract)
  → ``ResultIngestionRequest`` — RECEIVED: the delivery is a first-class record,
    so a rejected or failed delivery is visible instead of vanishing.
  → structural validation — VALIDATED or REJECTED. Validation is *structural and
    provenance-level only*: is the contract version one we accept, does every
    claim name a producer and a version, are the declared vocabularies known. It
    never judges whether the science is right.
  → ``ResultSetRecord`` registered PENDING → GENERATING → VALIDATED, carrying the
    provenance the engine declared.
  → a durable ``result_ingestion`` job — materialization verifies the bytes and
    reads the surface's declared shape, and only then is the surface AVAILABLE.

Three properties the application owns and the engine cannot override:

* **Idempotency.** A redelivered payload with the same idempotency key returns the
  original request. Engines retry; that must not produce two surfaces.
* **Attribution.** A payload whose attribution names no producer and version is
  rejected. An unattributable scientific result is not storable here.
* **Availability is earned.** A surface becomes readable only after its bytes
  verify. A declared checksum that does not match rejects the artifact and fails
  the surface — it never becomes a result that quietly disagrees with its file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.results.dependencies import (
    RESULT_INGEST,
    ResultServices,
    resolve_scope,
)
from app.domain.analysis.policies import default_queue_for, node_class_for
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, InfrastructureError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.variant.ingestion import validate_result_payload
from app.domain.variant.results import (
    ResultArtifactRecord,
    ResultIngestionRequest,
    ResultProvenance,
    ResultSetRecord,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    ChecksumAlgorithm,
    DataOrigin,
    JobKind,
    ResultArtifactFormat,
    ResultArtifactKind,
    ResultArtifactState,
    ResultCompleteness,
    ResultIngestionState,
    ResultSetState,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.results import RESULT_CONTRACT_VERSION, ResultPayload

INGESTION_JOB_KIND = JobKind.RESULT_INGESTION

#: Contract versions this build accepts. An unknown version is refused rather
#: than best-effort parsed: silently reading an unfamiliar payload shape is how a
#: field gets dropped and a result becomes quietly wrong.
ACCEPTED_CONTRACT_VERSIONS = frozenset({RESULT_CONTRACT_VERSION})

REJECTION_CONTRACT = "unsupported_contract_version"
REJECTION_INVALID = "payload_failed_validation"
REJECTION_UNATTRIBUTED = "payload_names_no_producer"
FAILURE_CHECKSUM = "artifact_checksum_mismatch"
FAILURE_MISSING = "artifact_missing_from_storage"
FAILURE_UNREADABLE = "analytical_surface_unreadable"


@dataclass(frozen=True, slots=True)
class ResultSetView:
    result_set: ResultSetRecord
    artifacts: tuple[ResultArtifactRecord, ...] = ()
    ingestion: ResultIngestionRequest | None = None
    capabilities: tuple[str, ...] = ()


def _enum_or_other(vocabulary: Any, value: str | None, fallback: Any) -> Any:
    """Map a declared vocabulary value, falling back to an explicit 'other'.

    The fallback is a *recorded* value (``other`` / ``binary``), never a guess at
    what the producer meant.
    """
    if value is None:
        return fallback
    try:
        return vocabulary(value)
    except ValueError:
        return fallback


def _provenance(payload: ResultPayload, *, analysis_configuration_id: str | None) -> ResultProvenance:
    attribution = payload.attribution
    return ResultProvenance(
        analysis_execution_id=payload.analysis_execution_id,
        scientific_execution_id=attribution.scientific_execution_id,
        analysis_configuration_id=analysis_configuration_id,
        engine_resource_id=attribution.engine_resource_id,
        engine_version=attribution.engine_version,
        environment_version=payload.environment_version,
        container_image_digest=payload.container_image_digest,
        node_identity=payload.node_identity,
        reference_genome_resource_id=payload.reference_genome_resource_id,
        resource_identities=dict(payload.resource_identities),
        parameters_digest=payload.parameters_digest,
    )


@dataclass(frozen=True, slots=True)
class SubmitResultPayloadCommand:
    payload: ResultPayload
    request: RequestContext
    idempotency_key: str
    payload_digest: str
    #: A user submitting on behalf of an execution (the normal path is the worker,
    #: which carries no user actor).
    actor: ActorContext | None = None
    service_account_id: str | None = None
    job_id: str | None = None


class SubmitResultPayload:
    """Accepts a result surface for an execution and queues its materialization."""

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, command: SubmitResultPayloadCommand) -> ResultSetView:
        now = self._services.clock.now()
        payload = command.payload
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)

            existing = await repositories.result_ingestions.get_by_idempotency_key(
                command.idempotency_key
            )
            if existing is not None:
                # A retried delivery. Return what the first one produced; do not
                # register a second surface for the same work.
                result_set = (
                    await repositories.result_sets.get(existing.result_set_id)
                    if existing.result_set_id
                    else None
                )
                artifacts = (
                    await repositories.result_artifacts.list_for_result_set(result_set.id)
                    if result_set
                    else ()
                )
                if result_set is None:
                    raise ConflictError(
                        "this result delivery was already refused",
                        details={
                            "ingestion_id": existing.id,
                            "state": existing.state.value,
                            "rejection_code": existing.rejection_code,
                        },
                    )
                return ResultSetView(
                    result_set=result_set, artifacts=artifacts, ingestion=existing
                )

            execution = await repositories.analysis_executions.get(
                payload.analysis_execution_id
            )
            if execution is None:
                raise NotFoundError("analysis_execution", payload.analysis_execution_id)

            # Scope comes from the execution row, never from the payload. An
            # engine cannot address a workspace it was not run for.
            scope = None
            if command.actor is not None:
                scope = await resolve_scope(
                    self._services,
                    repositories,
                    command.actor,
                    workspace_id=execution.workspace_id,
                    project_id=execution.project_id,
                    action=RESULT_INGEST,
                    recorder=recorder,
                    occurred_at=now,
                )

            request = ResultIngestionRequest(
                id=new_id("rin"),
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                analysis_execution_id=execution.id,
                result_key=payload.result_key,
                idempotency_key=command.idempotency_key,
                state=ResultIngestionState.RECEIVED,
                payload_digest=command.payload_digest,
                declared_completeness=_enum_or_other(
                    ResultCompleteness, payload.completeness, ResultCompleteness.UNKNOWN
                ),
                scientific_execution_id=payload.attribution.scientific_execution_id,
                engine_resource_id=payload.attribution.engine_resource_id,
                engine_version=payload.attribution.engine_version,
                submitted_by=scope.actor.actor_id if scope else None,
                service_account_id=command.service_account_id,
                job_id=command.job_id,
                correlation_id=command.request.correlation_id,
                declared_row_count=payload.row_count,
                artifact_count=len(payload.artifacts),
                is_development_payload=payload.is_development_payload,
                received_at=now,
            )
            stored_request = await repositories.result_ingestions.add(request)
            await recorder.event(
                event_type=EventType.RESULT_INGESTION_RECEIVED,
                aggregate_type="result_ingestion",
                aggregate_id=stored_request.id,
                occurred_at=now,
                workspace_id=stored_request.workspace_id,
                payload={
                    "analysis_execution_id": execution.id,
                    "result_key": payload.result_key,
                    "is_development_payload": payload.is_development_payload,
                },
            )

            if payload.contract_version not in ACCEPTED_CONTRACT_VERSIONS:
                await self._reject(
                    repositories,
                    recorder,
                    stored_request.validating(),
                    now=now,
                    code=REJECTION_CONTRACT,
                    message=(
                        f"result contract version {payload.contract_version!r} "
                        "is not accepted by this build"
                    ),
                )
                raise ValidationError(
                    "unsupported result contract version",
                    details={
                        "field": "contract_version",
                        "accepted": sorted(ACCEPTED_CONTRACT_VERSIONS),
                    },
                )

            outcome = validate_result_payload(payload)
            if not outcome.accepted:
                await self._reject(
                    repositories,
                    recorder,
                    stored_request.validating(),
                    now=now,
                    code=(
                        REJECTION_UNATTRIBUTED
                        if not payload.attribution.names_a_producer
                        else REJECTION_INVALID
                    ),
                    message="the result payload failed structural validation",
                    findings=outcome.as_dicts(),
                )
                raise ValidationError(
                    "the result payload failed structural validation",
                    details={"findings": list(outcome.as_dicts())},
                )

            validated_request = await repositories.result_ingestions.save(
                stored_request.validating()
            )
            validated_request = await repositories.result_ingestions.save(
                validated_request.validated(findings=outcome.as_dicts())
            )

            result_set = ResultSetRecord(
                id=new_id("rst"),
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                result_key=payload.result_key,
                state=ResultSetState.PENDING,
                provenance=_provenance(
                    payload,
                    analysis_configuration_id=execution.analysis_configuration_id,
                ),
                completeness=validated_request.declared_completeness,
                origin=DataOrigin.GENERATED,
                analytical_location=payload.analytical_location,
                row_count=payload.row_count,
                column_schema=dict(payload.column_schema),
                metadata={
                    **dict(payload.metadata),
                    # Carried on the row itself, so every read surface — API, UI,
                    # report — can say so without re-deriving it.
                    "is_development_payload": payload.is_development_payload,
                },
            )
            stored_set = await repositories.result_sets.add(result_set)
            stored_set = await repositories.result_sets.save(stored_set.generating())
            stored_set = await repositories.result_sets.save(stored_set.validated())

            artifacts = tuple(
                ResultArtifactRecord(
                    id=new_id("rar"),
                    result_set_id=stored_set.id,
                    artifact_key=claim.artifact_key,
                    kind=_enum_or_other(
                        ResultArtifactKind, claim.kind, ResultArtifactKind.OTHER
                    ),
                    artifact_format=_enum_or_other(
                        ResultArtifactFormat,
                        claim.artifact_format,
                        ResultArtifactFormat.OTHER,
                    ),
                    state=ResultArtifactState.REGISTERED,
                    storage_uri=claim.storage_uri,
                    analytical_location=claim.analytical_location,
                    media_type=claim.media_type,
                    size_bytes=claim.size_bytes,
                    checksum_algorithm=_optional_checksum(claim.checksum_algorithm),
                    checksum_value=claim.checksum_value,
                    row_count=claim.row_count,
                    column_schema=dict(claim.column_schema),
                    metadata=dict(claim.metadata),
                )
                for claim in payload.artifacts
            )
            await repositories.result_artifacts.add_many(artifacts)

            materializing = await repositories.result_ingestions.save(
                validated_request.materializing(result_set_id=stored_set.id)
            )

            # Same transaction as the rows above: a committed delivery always has
            # its materialization job, and a rolled-back one has neither.
            job_id = await repositories.jobs.enqueue(
                kind=INGESTION_JOB_KIND,
                payload={
                    "result_ingestion_id": materializing.id,
                    "result_set_id": stored_set.id,
                },
                correlation_id=command.request.correlation_id,
                queue=default_queue_for(INGESTION_JOB_KIND).value,
                workspace_id=stored_set.workspace_id,
                project_id=stored_set.project_id,
                idempotency_key=f"result-ingestion:{materializing.id}",
                analysis_execution_id=execution.id,
                node_class=node_class_for(INGESTION_JOB_KIND),
            )

            await recorder.audit(
                action="result_set.registered",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id if scope else None,
                resource_type="result_set",
                resource_id=stored_set.id,
                workspace_id=stored_set.workspace_id,
                project_id=stored_set.project_id,
                new_state=stored_set.state.value,
                detail={
                    "analysis_execution_id": execution.id,
                    "result_key": stored_set.result_key,
                    "artifact_count": len(artifacts),
                    "ingestion_id": materializing.id,
                    "job_id": job_id,
                    "warnings": len(outcome.warnings),
                },
            )
            await recorder.event(
                event_type=EventType.RESULT_SET_VALIDATED,
                aggregate_type="result_set",
                aggregate_id=stored_set.id,
                occurred_at=now,
                workspace_id=stored_set.workspace_id,
                payload={"ingestion_id": materializing.id, "job_id": job_id},
            )
        return ResultSetView(
            result_set=stored_set, artifacts=artifacts, ingestion=materializing
        )

    async def _reject(
        self,
        repositories: Any,
        recorder: ActivityRecorder,
        request: ResultIngestionRequest,
        *,
        now: Any,
        code: str,
        message: str,
        findings: tuple[dict[str, Any], ...] = (),
    ) -> None:
        saved = await repositories.result_ingestions.save(request)
        rejected = await repositories.result_ingestions.save(
            saved.rejected(at=now, code=code, message=message, findings=findings)
        )
        await recorder.audit(
            action="result_ingestion.rejected",
            outcome=AuditOutcome.FAILURE,
            occurred_at=now,
            resource_type="result_ingestion",
            resource_id=rejected.id,
            workspace_id=rejected.workspace_id,
            project_id=rejected.project_id,
            new_state=rejected.state.value,
            detail={"rejection_code": code, "finding_count": len(findings)},
        )
        await recorder.event(
            event_type=EventType.RESULT_INGESTION_REJECTED,
            aggregate_type="result_ingestion",
            aggregate_id=rejected.id,
            occurred_at=now,
            workspace_id=rejected.workspace_id,
            payload={"rejection_code": code},
        )


def _optional_checksum(value: str | None) -> ChecksumAlgorithm | None:
    if value is None:
        return None
    try:
        return ChecksumAlgorithm(value.lower())
    except ValueError:
        raise ValidationError(
            "unsupported checksum algorithm",
            details={"field": "checksum_algorithm", "value": value},
        ) from None


@dataclass(frozen=True, slots=True)
class MaterializeResultSetCommand:
    """Worker-side. No actor: the job's own authorization already happened."""

    result_ingestion_id: str
    request: RequestContext


class MaterializeResultSet:
    """Verifies the produced bytes, then makes the surface readable.

    Verification is deliberately conservative:

    * a declared checksum must match the stored bytes,
    * an artifact whose bytes are absent is marked ``missing``, not ignored,
    * an analytical location that cannot be read fails the surface.

    A surface only reaches ``AVAILABLE`` when every artifact that declared a
    verifiable fact passed. Anything else fails the surface with a recorded code,
    because presenting unverified rows as results is the failure mode this whole
    step exists to prevent.
    """

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, command: MaterializeResultSetCommand) -> ResultSetView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            request = await repositories.result_ingestions.get(command.result_ingestion_id)
            if request is None:
                raise NotFoundError("result_ingestion", command.result_ingestion_id)
            if request.is_terminal:
                # The job was redelivered after completion. Idempotent no-op.
                result_set = (
                    await repositories.result_sets.get(request.result_set_id)
                    if request.result_set_id
                    else None
                )
                if result_set is None:
                    raise NotFoundError("result_set", str(request.result_set_id))
                artifacts = await repositories.result_artifacts.list_for_result_set(
                    result_set.id
                )
                return ResultSetView(
                    result_set=result_set, artifacts=artifacts, ingestion=request
                )
            if request.result_set_id is None:
                raise ConflictError(
                    "this ingestion has no result set to materialize",
                    details={"ingestion_id": request.id},
                )
            result_set = await repositories.result_sets.get(request.result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", request.result_set_id)

            artifacts = await repositories.result_artifacts.list_for_result_set(
                result_set.id
            )
            problems: list[dict[str, Any]] = []
            for artifact in artifacts:
                verified = await self._verify(artifact, problems=problems, now=now)
                if verified is not artifact:
                    await repositories.result_artifacts.save(verified)

            description = None
            location = result_set.analytical_location
            if location and self._services.analytics is not None:
                try:
                    description = await self._services.analytics.describe(location)
                except InfrastructureError as error:
                    problems.append(
                        {
                            "code": FAILURE_UNREADABLE,
                            "location": location,
                            "message": str(error),
                        }
                    )

            if problems:
                failed_set = await repositories.result_sets.save(
                    result_set.failed(
                        code=problems[0]["code"],
                        message="the produced result surface did not verify",
                    )
                )
                failed_request = await repositories.result_ingestions.save(
                    request.failed(
                        at=now,
                        code=problems[0]["code"],
                        message="the produced result surface did not verify",
                    )
                )
                await recorder.audit(
                    action="result_set.failed",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    resource_type="result_set",
                    resource_id=failed_set.id,
                    workspace_id=failed_set.workspace_id,
                    project_id=failed_set.project_id,
                    new_state=failed_set.state.value,
                    detail={"problems": problems},
                )
                await recorder.event(
                    event_type=EventType.RESULT_SET_FAILED,
                    aggregate_type="result_set",
                    aggregate_id=failed_set.id,
                    occurred_at=now,
                    workspace_id=failed_set.workspace_id,
                    payload={"problems": problems},
                )
                return ResultSetView(
                    result_set=failed_set,
                    artifacts=await repositories.result_artifacts.list_for_result_set(
                        failed_set.id
                    ),
                    ingestion=failed_request,
                )

            available = await repositories.result_sets.save(
                result_set.available(
                    at=now,
                    analytical_location=location,
                    # The file's own row count wins over the declared one: what is
                    # actually stored is the fact, the declaration was a claim.
                    row_count=description.row_count if description else result_set.row_count,
                    column_schema=(
                        description.column_schema() if description else result_set.column_schema
                    ),
                )
            )
            accepted_request = await repositories.result_ingestions.save(
                request.accepted(at=now)
            )
            await recorder.audit(
                action="result_set.available",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                resource_type="result_set",
                resource_id=available.id,
                workspace_id=available.workspace_id,
                project_id=available.project_id,
                previous_state=result_set.state.value,
                new_state=available.state.value,
                detail={
                    "row_count": available.row_count,
                    "artifact_count": len(artifacts),
                    "declared_row_count": request.declared_row_count,
                },
            )
            await recorder.event(
                event_type=EventType.RESULT_SET_AVAILABLE,
                aggregate_type="result_set",
                aggregate_id=available.id,
                occurred_at=now,
                workspace_id=available.workspace_id,
                payload={"result_key": available.result_key},
            )
            final_artifacts = await repositories.result_artifacts.list_for_result_set(
                available.id
            )
        return ResultSetView(
            result_set=available, artifacts=final_artifacts, ingestion=accepted_request
        )

    async def _verify(
        self, artifact: ResultArtifactRecord, *, problems: list[dict[str, Any]], now: Any
    ) -> ResultArtifactRecord:
        """Check one artifact against storage. Returns the artifact's new state."""
        storage = self._services.object_storage
        if artifact.storage_uri is None or storage is None:
            # Nothing to verify against — an analytical-only artifact. It is
            # accepted as registered rather than claimed to be verified.
            return artifact
        verifying = artifact.verifying()
        stored = await storage.stat_object(artifact.storage_uri)
        if stored is None:
            problems.append(
                {
                    "code": FAILURE_MISSING,
                    "artifact_key": artifact.artifact_key,
                    "message": "the declared artifact is not present in storage",
                }
            )
            return verifying.missing(message="not present in object storage")
        if artifact.checksum_algorithm and artifact.checksum_value:
            if self._services.checksums is None:
                return verifying
            computed = await self._services.checksums.checksum(
                artifact.storage_uri, algorithm=artifact.checksum_algorithm.value
            )
            if computed != artifact.checksum_value:
                problems.append(
                    {
                        "code": FAILURE_CHECKSUM,
                        "artifact_key": artifact.artifact_key,
                        "message": "stored bytes do not match the declared checksum",
                    }
                )
                return verifying.rejected(
                    code=FAILURE_CHECKSUM,
                    message="stored bytes do not match the declared checksum",
                )
        return verifying.accepted(
            at=now,
            size_bytes=stored.size_bytes,
        )


__all__ = [
    "ACCEPTED_CONTRACT_VERSIONS",
    "FAILURE_CHECKSUM",
    "FAILURE_MISSING",
    "FAILURE_UNREADABLE",
    "INGESTION_JOB_KIND",
    "REJECTION_CONTRACT",
    "REJECTION_INVALID",
    "REJECTION_UNATTRIBUTED",
    "MaterializeResultSet",
    "MaterializeResultSetCommand",
    "ResultSetView",
    "SubmitResultPayload",
    "SubmitResultPayloadCommand",
]
