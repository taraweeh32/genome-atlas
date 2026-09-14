"""Evidence source, record, delivery and conflict endpoints.

Thin handlers, as everywhere else: parse transport input, hand an explicit command
to a use case, shape the result. No handler decides access, a state transition or a
scope.

Three boundaries are visible in the layout:

* **Sources are platform-governed, records are tenant content.** Registering,
  activating or retiring a source version sits under ``/administration`` behind the
  platform evidence-administration permission; reading and curating records is
  authorized in the workspace or project the record itself declares.
* **A delivery carries structured claims only.** The ingestion endpoint accepts
  claims, an artifact reference and provenance — never a command, a path to execute
  or a tenant scope it can choose freely.
* **Nothing here classifies.** No endpoint states whether evidence satisfies an
  interpretation criterion or what a variant's classification is. Disagreement is
  exposed as conflicts, unresolved, for the interpretation layer and for people to
  judge.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.evidence_mapping import (
    batch_response,
    conflict_response,
    finding_response,
    ingestion_payload,
    record_response,
    source_response,
)
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.evidence import (
    EvidenceConflictCollection,
    EvidenceHistoryResponse,
    EvidenceIngestionBatchCollection,
    EvidenceIngestionResponse,
    EvidenceRecordCollection,
    EvidenceRecordResponse,
    EvidenceSourceCollection,
    EvidenceSourceResponse,
    EvidenceValidationFindingCollection,
    IngestEvidencePayloadBody,
    RecordEvidencePayload,
    RegisterEvidenceSourcePayload,
    TransitionEvidenceSourcePayload,
    WithdrawEvidencePayload,
)
from app.application.use_cases.evidence.ingestion import (
    IngestEvidenceCommand,
    IngestEvidencePayload,
)
from app.application.use_cases.evidence.records import (
    EvidenceRecords,
    ListEvidenceQuery,
    RecordEvidenceCommand,
    WithdrawEvidenceCommand,
)
from app.application.use_cases.evidence.sources import (
    EvidenceSourceCatalogue,
    ListSourcesQuery,
    RegisterEvidenceSource,
    RegisterSourceCommand,
    TransitionEvidenceSource,
    TransitionSourceCommand,
)
from app.domain.value_objects.enums import (
    CriterionDirection,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceIngestionState,
    EvidenceSourceCategory,
    EvidenceStrength,
    ScientificResourceState,
)

sources_router = APIRouter(prefix="/evidence-sources", tags=["evidence"])
records_router = APIRouter(prefix="/evidence-records", tags=["evidence"])
ingestion_router = APIRouter(prefix="/evidence-deliveries", tags=["evidence"])
admin_sources_router = APIRouter(
    prefix="/administration/evidence-sources", tags=["administration"]
)


# --------------------------------------------------------------------------- #
# Source registry reads                                                       #
# --------------------------------------------------------------------------- #


@sources_router.get(
    "",
    response_model=EvidenceSourceCollection,
    summary="List registered evidence source versions",
    responses=ERROR_RESPONSES,
)
async def list_evidence_sources(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    category: Annotated[str | None, Query()] = None,
    source_key: Annotated[str | None, Query()] = None,
    usable_only: Annotated[bool, Query()] = False,
) -> EvidenceSourceCollection:
    catalogue = EvidenceSourceCatalogue(container.evidence_services())
    paged = await catalogue.list(
        ListSourcesQuery(
            actor=caller.actor,
            request=context,
            page=page,
            category=parse_enum(EvidenceSourceCategory, category, field="category")
            if category
            else None,
            source_key=source_key,
            usable_only=usable_only,
        )
    )
    return EvidenceSourceCollection(
        items=[source_response(item) for item in paged.items], page=page_meta(paged)
    )


@sources_router.get(
    "/{source_id}",
    response_model=EvidenceSourceResponse,
    summary="Read one evidence source version",
    responses=ERROR_RESPONSES,
)
async def get_evidence_source(
    source_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceSourceResponse:
    catalogue = EvidenceSourceCatalogue(container.evidence_services())
    return source_response(await catalogue.get(caller.actor, context, source_id))


# --------------------------------------------------------------------------- #
# Records                                                                     #
# --------------------------------------------------------------------------- #


@records_router.get(
    "",
    response_model=EvidenceRecordCollection,
    summary="List evidence records",
    responses=ERROR_RESPONSES,
)
async def list_evidence_records(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    variant_id: Annotated[str | None, Query()] = None,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    source_key: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    include_superseded: Annotated[bool, Query()] = False,
) -> EvidenceRecordCollection:
    records = EvidenceRecords(container.evidence_services())
    paged = await records.list(
        ListEvidenceQuery(
            actor=caller.actor,
            request=context,
            page=page,
            variant_id=variant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            source_key=source_key,
            category=parse_enum(EvidenceCategory, category, field="category")
            if category
            else None,
            include_superseded=include_superseded,
        )
    )
    return EvidenceRecordCollection(
        items=[record_response(item) for item in paged.items], page=page_meta(paged)
    )


@records_router.get(
    "/{evidence_id}",
    response_model=EvidenceRecordResponse,
    summary="Read one evidence record",
    responses=ERROR_RESPONSES,
)
async def get_evidence_record(
    evidence_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceRecordResponse:
    records = EvidenceRecords(container.evidence_services())
    return record_response(await records.get(caller.actor, context, evidence_id))


@records_router.post(
    "",
    response_model=EvidenceRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record evidence stated by a person",
    responses=ERROR_RESPONSES,
)
async def record_evidence(
    body: RecordEvidencePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceRecordResponse:
    records = EvidenceRecords(container.evidence_services())
    stored = await records.record(
        RecordEvidenceCommand(
            actor=caller.actor,
            request=context,
            variant_id=body.variant_id,
            category=parse_enum(EvidenceCategory, body.category, field="category"),
            source_key=body.source_key,
            source_version=body.source_version,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            direction=parse_enum(CriterionDirection, body.direction, field="direction")
            if body.direction
            else CriterionDirection.NEUTRAL,
            strength=parse_enum(EvidenceStrength, body.strength, field="strength")
            if body.strength
            else EvidenceStrength.NOT_APPLICABLE,
            applicability=parse_enum(
                EvidenceApplicability, body.applicability, field="applicability"
            )
            if body.applicability
            else EvidenceApplicability.UNDETERMINED,
            summary=body.summary,
            rationale=body.rationale,
            method=body.method,
            external_reference=body.external_reference,
            gene_symbol=body.gene_symbol,
            condition_identifier=body.condition_identifier,
            condition_term=body.condition_term,
            inheritance=body.inheritance,
            values=body.values,
        )
    )
    return record_response(stored)


@records_router.post(
    "/{evidence_id}/withdrawal",
    response_model=EvidenceRecordResponse,
    summary="Withdraw an evidence record without deleting it",
    responses=ERROR_RESPONSES,
)
async def withdraw_evidence_record(
    evidence_id: str,
    body: WithdrawEvidencePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceRecordResponse:
    records = EvidenceRecords(container.evidence_services())
    stored = await records.withdraw(
        WithdrawEvidenceCommand(
            actor=caller.actor,
            request=context,
            evidence_id=evidence_id,
            reason=body.reason,
        )
    )
    return record_response(stored)


@records_router.get(
    "/variants/{variant_id}/history",
    response_model=EvidenceHistoryResponse,
    summary="Read every evidence version recorded about one variant",
    responses=ERROR_RESPONSES,
)
async def evidence_history(
    variant_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceHistoryResponse:
    records = EvidenceRecords(container.evidence_services())
    history = await records.history(caller.actor, context, variant_id=variant_id)
    return EvidenceHistoryResponse(
        variant_id=variant_id, records=[record_response(item) for item in history]
    )


@records_router.get(
    "/variants/{variant_id}/conflicts",
    response_model=EvidenceConflictCollection,
    summary="Report where retained evidence about one variant disagrees",
    responses=ERROR_RESPONSES,
)
async def evidence_conflicts(
    variant_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceConflictCollection:
    records = EvidenceRecords(container.evidence_services())
    conflicts = await records.conflicts(caller.actor, context, variant_id=variant_id)
    return EvidenceConflictCollection(
        variant_id=variant_id,
        conflicts=[conflict_response(item) for item in conflicts],
    )


# --------------------------------------------------------------------------- #
# Deliveries                                                                  #
# --------------------------------------------------------------------------- #


@ingestion_router.post(
    "",
    response_model=EvidenceIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest one evidence delivery",
    responses=ERROR_RESPONSES,
)
async def ingest_evidence(
    body: IngestEvidencePayloadBody,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceIngestionResponse:
    use_case = IngestEvidencePayload(container.evidence_services())
    outcome = await use_case.execute(
        IngestEvidenceCommand(
            request=context,
            payload=ingestion_payload(body),
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            actor=caller.actor,
        )
    )
    return EvidenceIngestionResponse(
        batch=batch_response(outcome.batch),
        redelivery=outcome.was_redelivery,
        stored=[record_response(item) for item in outcome.stored],
        superseded_evidence_ids=[item.id for item in outcome.superseded],
        findings=[finding_response(item) for item in outcome.findings],
    )


@ingestion_router.get(
    "",
    response_model=EvidenceIngestionBatchCollection,
    summary="List evidence deliveries",
    responses=ERROR_RESPONSES,
)
async def list_evidence_deliveries(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    source_key: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> EvidenceIngestionBatchCollection:
    records = EvidenceRecords(container.evidence_services())
    paged = await records.list_batches(
        caller.actor,
        context,
        page=page,
        source_key=source_key,
        state=parse_enum(EvidenceIngestionState, state, field="state")
        if state
        else None,
    )
    return EvidenceIngestionBatchCollection(
        items=[batch_response(item) for item in paged.items], page=page_meta(paged)
    )


@ingestion_router.get(
    "/{batch_id}/findings",
    response_model=EvidenceValidationFindingCollection,
    summary="Read why records in a delivery were refused or flagged",
    responses=ERROR_RESPONSES,
)
async def list_delivery_findings(
    batch_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> EvidenceValidationFindingCollection:
    records = EvidenceRecords(container.evidence_services())
    paged = await records.batch_findings(
        caller.actor, context, batch_id=batch_id, page=page
    )
    return EvidenceValidationFindingCollection(
        items=[finding_response(item) for item in paged.items], page=page_meta(paged)
    )


# --------------------------------------------------------------------------- #
# Source governance (platform administration)                                 #
# --------------------------------------------------------------------------- #


@admin_sources_router.post(
    "",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register one evidence source version",
    responses=ERROR_RESPONSES,
)
async def register_evidence_source(
    body: RegisterEvidenceSourcePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceSourceResponse:
    use_case = RegisterEvidenceSource(container.evidence_services())
    stored = await use_case.execute(
        RegisterSourceCommand(
            actor=caller.actor,
            request=context,
            source_key=body.source_key,
            version=body.version,
            display_name=body.display_name,
            category=parse_enum(
                EvidenceSourceCategory, body.category, field="category"
            ),
            provider=body.provider,
            description=body.description,
            release_label=body.release_label,
            released_at=body.released_at,
            retrieved_at=body.retrieved_at,
            schema_version=body.schema_version,
            genome_assembly=body.genome_assembly,
            checksum_algorithm=body.checksum_algorithm,
            checksum_value=body.checksum_value,
            size_bytes=body.size_bytes,
            supplies=tuple(
                parse_enum(EvidenceCategory, item, field="supplies")
                for item in body.supplies
            ),
            supplies_strength=body.supplies_strength,
            provenance=body.provenance,
            licensing=body.licensing,
            metadata=body.metadata,
        )
    )
    return source_response(stored)


@admin_sources_router.post(
    "/{source_id}/state",
    response_model=EvidenceSourceResponse,
    summary="Activate, deprecate, retire or invalidate a source version",
    responses=ERROR_RESPONSES,
)
async def transition_evidence_source(
    source_id: str,
    body: TransitionEvidenceSourcePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> EvidenceSourceResponse:
    use_case = TransitionEvidenceSource(container.evidence_services())
    stored = await use_case.execute(
        TransitionSourceCommand(
            actor=caller.actor,
            request=context,
            source_id=source_id,
            state=parse_enum(ScientificResourceState, body.state, field="state"),
            reason=body.reason,
        )
    )
    return source_response(stored)


__all__ = [
    "admin_sources_router",
    "ingestion_router",
    "records_router",
    "sources_router",
]
