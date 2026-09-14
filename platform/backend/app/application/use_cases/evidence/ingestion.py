"""Ingesting evidence deliveries.

What ingestion does, in order:

1. resolves and locks onto the registered source version the payload names;
2. validates payload identity (contract, source, release, retrieval time,
   usability) — a mismatch refuses the whole delivery rather than storing evidence
   attributed to a release nobody agrees on;
3. resolves the variant each claim is about, by identity;
4. validates each claim against what the source is registered to supply;
5. writes accepted claims as evidence records, superseding the previous version of
   the *same statement from the same source* and leaving every other source's
   evidence untouched;
6. records a finding for every refusal, and completes the batch.

What ingestion never does: repair a scientific value, normalize a variant, decide
which of two disagreeing sources is right, attribute a strength a source does not
state, or overwrite an earlier version's content. Redelivery of an identical
payload returns the original batch.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.evidence.dependencies import (
    EVIDENCE_CURATE,
    EvidenceServices,
    resolve_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.evidence.entities import (
    HUMAN_ORIGINS,
    EvidenceContext,
    EvidenceIngestionBatch,
    EvidenceRecord,
    EvidenceSourceRecord,
    EvidenceValidationFinding,
    content_digest,
)
from app.domain.evidence.validation import (
    ClaimIssue,
    validate_claim,
    validate_payload_identity,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    EvidenceIngestionState,
    EvidenceRecordState,
    ValidationSeverity,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.evidence import (
    MAX_INLINE_EVIDENCE_RECORDS,
    EvidenceClaim,
    EvidencePayload,
)


@dataclass(frozen=True, slots=True)
class IngestEvidenceCommand:
    request: RequestContext
    payload: EvidencePayload
    #: Tenancy of the delivery. Absent means platform reference evidence, which
    #: only platform governance may write.
    workspace_id: str | None = None
    project_id: str | None = None
    actor: ActorContext | None = None
    service_account_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    batch: EvidenceIngestionBatch
    stored: tuple[EvidenceRecord, ...]
    superseded: tuple[EvidenceRecord, ...]
    findings: tuple[EvidenceValidationFinding, ...]
    #: True when the delivery had already been ingested and nothing was rewritten.
    was_redelivery: bool = False


class IngestEvidencePayload:
    """Validate and store one evidence delivery."""

    def __init__(self, services: EvidenceServices) -> None:
        self._services = services

    async def execute(self, command: IngestEvidenceCommand) -> IngestionOutcome:
        now = self._services.clock.now()
        payload = command.payload
        digest = _payload_digest(payload)

        if len(payload.claims) > MAX_INLINE_EVIDENCE_RECORDS:
            raise ValidationError(
                "this delivery is too large to ingest inline; supply an artifact instead",
                details={
                    "claim_count": len(payload.claims),
                    "limit": MAX_INLINE_EVIDENCE_RECORDS,
                },
            )

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            if command.actor is not None:
                await resolve_scope(
                    self._services,
                    repositories,
                    command.actor,
                    workspace_id=command.workspace_id,
                    project_id=command.project_id,
                    action=EVIDENCE_CURATE,
                    recorder=recorder,
                    occurred_at=now,
                )

            source = await repositories.evidence_sources.get_by_version(
                source_key=payload.source.source_key, version=payload.source.version
            )
            if source is None:
                raise NotFoundError(
                    "evidence_source",
                    f"{payload.source.source_key}@{payload.source.version}",
                )

            existing = await repositories.evidence_ingestions.get_by_payload_digest(
                source_key=source.source_key, payload_digest=digest
            )
            if existing is not None:
                # Idempotent redelivery: the evidence is already stored exactly
                # once, so nothing is written and nothing is duplicated.
                return IngestionOutcome(
                    batch=existing,
                    stored=(),
                    superseded=(),
                    findings=(),
                    was_redelivery=True,
                )

            batch = EvidenceIngestionBatch(
                id=new_id("evb"),
                source_key=source.source_key,
                source_version=source.version,
                source_resource_id=source.id,
                payload_digest=digest,
                state=EvidenceIngestionState.VALIDATING,
                origin=payload.origin,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                claimed_record_count=len(payload.claims),
                retrieved_at=payload.retrieved_at,
                source_released_at=payload.source.released_at,
                requested_by=command.actor.actor_id if command.actor else None,
                service_account_id=command.service_account_id,
                job_id=command.job_id,
                correlation_id=payload.correlation_id,
                provenance=_batch_provenance(payload, source, self._services),
                created_at=now,
            )
            batch = await repositories.evidence_ingestions.add(batch)

            blocking = validate_payload_identity(payload, source)
            if blocking:
                findings = tuple(
                    _finding(batch.id, issue, now) for issue in blocking
                )
                await repositories.evidence_ingestions.add_findings(findings)
                rejected = await repositories.evidence_ingestions.save(
                    replace(
                        batch,
                        state=EvidenceIngestionState.REJECTED,
                        failure_code=blocking[0].code,
                        failure_message=blocking[0].message,
                        completed_at=now,
                        rejected_record_count=len(payload.claims),
                    )
                )
                await recorder.event(
                    event_type=EventType.EVIDENCE_INGESTION_REJECTED,
                    aggregate_type="evidence_ingestion_batch",
                    aggregate_id=batch.id,
                    occurred_at=now,
                    payload={
                        "source_key": source.source_key,
                        "source_version": source.version,
                        "failure_code": blocking[0].code,
                    },
                )
                # A refused delivery is an explicit, explained refusal — never a
                # silent partial write.
                raise ValidationError(
                    blocking[0].message,
                    details={
                        "code": blocking[0].code,
                        "ingestion_batch_id": rejected.id,
                        **(blocking[0].detail or {}),
                    },
                )

            stored: list[EvidenceRecord] = []
            superseded: list[EvidenceRecord] = []
            findings: list[EvidenceValidationFinding] = []
            duplicates = 0
            rejected_count = 0
            seen_digests: set[str] = set()

            for index, claim in enumerate(payload.claims):
                issues = list(
                    validate_claim(
                        claim, source=source, index=index, origin=payload.origin
                    )
                )
                variant_id = await _resolve_variant(repositories, claim)
                if variant_id is None:
                    issues.append(
                        ClaimIssue(
                            code="evidence.variant_unresolved",
                            message="the variant this claim is about could not be resolved",
                            record_index=index,
                            detail={
                                "variant_id": claim.variant_id,
                                "variant_identifier": claim.variant_identifier,
                            },
                        )
                    )
                blockers = [issue for issue in issues if issue.blocks_record]
                findings.extend(_finding(batch.id, issue, now) for issue in issues)
                if blockers:
                    rejected_count += 1
                    continue

                claim_digest = content_digest(_claim_identity(claim, variant_id))
                if claim_digest in seen_digests:
                    # The same claim twice inside one delivery is stored once.
                    duplicates += 1
                    continue
                seen_digests.add(claim_digest)

                already = await repositories.evidence_records.get_by_digest(
                    variant_id=variant_id,
                    source_key=source.source_key,
                    payload_digest=claim_digest,
                )
                if already is not None:
                    duplicates += 1
                    continue

                evidence_key = claim.evidence_key or claim.source_identifier
                previous = None
                if evidence_key:
                    previous = await repositories.evidence_records.current_for_lineage(
                        variant_id=variant_id,
                        source_key=source.source_key,
                        evidence_key=evidence_key,
                    )
                record = _record(
                    claim,
                    variant_id=variant_id,
                    source=source,
                    payload=payload,
                    batch=batch,
                    claim_digest=claim_digest,
                    evidence_key=evidence_key,
                    previous=previous,
                    actor=command.actor,
                    now=now,
                )
                await repositories.evidence_records.add(record)
                stored.append(record)
                if previous is not None:
                    # Same source, same statement: a new version. The old row keeps
                    # its content and stays readable.
                    superseded.append(
                        await repositories.evidence_records.save_lifecycle(
                            previous.supersede(by_id=record.id, at=now)
                        )
                    )

            if findings:
                await repositories.evidence_ingestions.add_findings(tuple(findings))

            state = (
                EvidenceIngestionState.ACCEPTED
                if rejected_count == 0
                else EvidenceIngestionState.PARTIALLY_ACCEPTED
                if stored
                else EvidenceIngestionState.REJECTED
            )
            completed = await repositories.evidence_ingestions.save(
                batch.completed(
                    state=state,
                    at=now,
                    stored=len(stored),
                    superseded=len(superseded),
                    duplicates=duplicates,
                    rejected=rejected_count,
                )
            )
            await recorder.audit(
                action="evidence_ingestion.completed",
                outcome=AuditOutcome.SUCCESS
                if state is not EvidenceIngestionState.REJECTED
                else AuditOutcome.FAILURE,
                occurred_at=now,
                actor_user_id=command.actor.actor_id if command.actor else None,
                resource_type="evidence_ingestion_batch",
                resource_id=completed.id,
                new_state=completed.state.value,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                detail={
                    "source_key": source.source_key,
                    "source_version": source.version,
                    "stored": len(stored),
                    "superseded": len(superseded),
                    "duplicates": duplicates,
                    "rejected": rejected_count,
                },
            )
            await recorder.event(
                event_type=EventType.EVIDENCE_INGESTION_ACCEPTED
                if state is not EvidenceIngestionState.REJECTED
                else EventType.EVIDENCE_INGESTION_REJECTED,
                aggregate_type="evidence_ingestion_batch",
                aggregate_id=completed.id,
                occurred_at=now,
                payload={
                    "source_key": source.source_key,
                    "source_version": source.version,
                    "stored_record_count": len(stored),
                    "state": completed.state.value,
                },
            )
        return IngestionOutcome(
            batch=completed,
            stored=tuple(stored),
            superseded=tuple(superseded),
            findings=tuple(findings),
        )


async def _resolve_variant(repositories: Any, claim: EvidenceClaim) -> str | None:
    """Resolve the variant a claim is about, by identity only.

    ``variant_identifier`` is the platform's canonical variant key. Nothing is
    inferred from position or from a coordinate string the platform would have to
    normalize — normalization is a scientific operation and lives behind the
    scientific boundary.
    """
    if claim.variant_id:
        variant = await repositories.variants.get(claim.variant_id)
        return variant.id if variant is not None else None
    if claim.variant_identifier:
        variant = await repositories.variants.get_by_canonical_key(
            claim.variant_identifier
        )
        return variant.id if variant is not None else None
    return None


def _claim_identity(claim: EvidenceClaim, variant_id: str) -> dict[str, Any]:
    """The delivered content of one claim, as the unit of duplicate detection."""
    return {
        "variant_id": variant_id,
        "category": claim.category.value,
        "direction": claim.direction.value,
        "strength": claim.strength.value,
        "applicability": claim.applicability.value,
        "source_identifier": claim.source_identifier,
        "evidence_key": claim.evidence_key,
        "summary": claim.summary,
        "rationale": claim.rationale,
        "method": claim.method,
        "gene_symbol": claim.gene_symbol,
        "gene_identifier": claim.gene_identifier,
        "transcript_identifier": claim.transcript_identifier,
        "condition_identifier": claim.condition_identifier,
        "condition_term": claim.condition_term,
        "inheritance": claim.inheritance,
        "external_reference": claim.external_reference,
        "values": claim.values,
    }


def _record(
    claim: EvidenceClaim,
    *,
    variant_id: str,
    source: EvidenceSourceRecord,
    payload: EvidencePayload,
    batch: EvidenceIngestionBatch,
    claim_digest: str,
    evidence_key: str | None,
    previous: EvidenceRecord | None,
    actor: ActorContext | None,
    now: datetime,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=new_id("evi"),
        variant_id=variant_id,
        category=claim.category,
        origin=payload.origin,
        source_key=source.source_key,
        source_version=source.version,
        source_resource_id=source.id,
        source_identifier=claim.source_identifier,
        source_released_at=claim.source_released_at or source.released_at,
        retrieved_at=claim.retrieved_at or payload.retrieved_at,
        workspace_id=batch.workspace_id,
        project_id=batch.project_id,
        context=EvidenceContext(
            gene_symbol=claim.gene_symbol,
            gene_identifier=claim.gene_identifier,
            transcript_identifier=claim.transcript_identifier,
            condition_identifier=claim.condition_identifier,
            condition_term=claim.condition_term,
            inheritance=claim.inheritance,
        ),
        direction=claim.direction,
        strength=claim.strength,
        applicability=claim.applicability,
        state=EvidenceRecordState.AVAILABLE,
        summary=claim.summary,
        rationale=claim.rationale,
        external_reference=claim.external_reference,
        method=claim.method,
        evidence_key=evidence_key,
        version_number=(previous.version_number + 1) if previous else 1,
        supersedes_id=previous.id if previous else None,
        ingestion_batch_id=batch.id,
        payload_digest=claim_digest,
        scientific_execution_id=payload.scientific_execution_id,
        # Values exactly as the source stated them.
        payload=dict(claim.values),
        provenance={
            "source_key": source.source_key,
            "source_version": source.version,
            "source_release_label": source.release_label,
            "source_schema_version": source.schema_version,
            "source_checksum_value": source.checksum_value,
            "ingestion_batch_id": batch.id,
            "contract_version": payload.contract_version,
            "correlation_id": payload.correlation_id,
            "scientific_execution_id": payload.scientific_execution_id,
            "is_development_payload": payload.is_development_payload,
            **payload.provenance,
        },
        recorded_at=now,
        created_by=actor.actor_id
        if actor is not None and payload.origin in HUMAN_ORIGINS
        else None,
        created_at=now,
    )


def _batch_provenance(
    payload: EvidencePayload, source: EvidenceSourceRecord, services: EvidenceServices
) -> dict[str, Any]:
    return {
        "contract_version": payload.contract_version,
        "source_release_label": source.release_label,
        "source_schema_version": source.schema_version,
        "source_checksum_algorithm": source.checksum_algorithm,
        "source_checksum_value": source.checksum_value,
        "software_version": services.software_version,
        "is_development_payload": payload.is_development_payload,
        **payload.provenance,
    }


def _payload_digest(payload: EvidencePayload) -> str:
    return content_digest(
        {
            "source_key": payload.source.source_key,
            "version": payload.source.version,
            "release_label": payload.source.release_label,
            "origin": payload.origin.value,
            "retrieved_at": payload.retrieved_at,
            "artifact": payload.artifact.storage_key if payload.artifact else None,
            "claims": [
                _claim_identity(claim, claim.variant_id or claim.variant_identifier or "")
                for claim in payload.claims
            ],
        }
    )


def _finding(
    batch_id: str, issue: ClaimIssue, now: datetime
) -> EvidenceValidationFinding:
    return EvidenceValidationFinding(
        id=new_id("evf"),
        ingestion_batch_id=batch_id,
        code=issue.code,
        message=issue.message,
        severity=issue.severity or ValidationSeverity.ERROR,
        record_index=issue.record_index,
        detail=dict(issue.detail or {}),
        created_at=now,
    )


__all__ = ["IngestEvidenceCommand", "IngestEvidencePayload", "IngestionOutcome"]
