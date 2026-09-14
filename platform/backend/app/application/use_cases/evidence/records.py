"""Reading evidence, recording curated evidence, and withdrawing it.

Reads are scope-filtered from the caller's own grants; a listing cannot reach a
workspace the caller has no evidence-read grant in, whatever identifier the
request contains. Disagreement between sources is reported as conflicts computed
on read — the platform never resolves it, and never rewrites one source's
evidence because another disagrees.

Curation records what a person stated, with that person attached and the origin
marked as human-entered, so a curated item can never be mistaken for something a
source delivered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.evidence.dependencies import (
    EVIDENCE_CURATE,
    EVIDENCE_READ,
    EvidenceServices,
    readable_workspace_scope,
    resolve_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import AuthorizationError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.evidence.entities import (
    EvidenceConflict,
    EvidenceContext,
    EvidenceRecord,
    EvidenceValidationFinding,
)
from app.domain.evidence.validation import detect_conflicts
from app.domain.value_objects.enums import (
    AuditOutcome,
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceIngestionState,
    EvidenceRecordState,
    EvidenceStrength,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class ListEvidenceQuery:
    actor: ActorContext
    request: RequestContext
    page: Page
    variant_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    source_key: str | None = None
    category: EvidenceCategory | None = None
    include_superseded: bool = False


@dataclass(frozen=True, slots=True)
class RecordEvidenceCommand:
    """A person recording evidence they are stating themselves."""

    actor: ActorContext
    request: RequestContext
    variant_id: str
    category: EvidenceCategory
    source_key: str
    source_version: str
    workspace_id: str | None = None
    project_id: str | None = None
    direction: CriterionDirection = CriterionDirection.NEUTRAL
    strength: EvidenceStrength = EvidenceStrength.NOT_APPLICABLE
    applicability: EvidenceApplicability = EvidenceApplicability.UNDETERMINED
    summary: str | None = None
    rationale: str | None = None
    method: str | None = None
    external_reference: str | None = None
    gene_symbol: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    inheritance: str | None = None
    values: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WithdrawEvidenceCommand:
    actor: ActorContext
    request: RequestContext
    evidence_id: str
    reason: str | None = None


class EvidenceRecords:
    """Evidence reads, human curation and withdrawal."""

    def __init__(self, services: EvidenceServices) -> None:
        self._services = services

    # ---------------------------------------------------------------- reads --

    async def list(self, query: ListEvidenceQuery) -> Paged[EvidenceRecord]:
        scope = readable_workspace_scope(
            query.actor, workspace_id=query.workspace_id, action=EVIDENCE_READ
        )
        async with self._services.unit_of_work.begin() as repositories:
            return await repositories.evidence_records.list_records(
                page=query.page,
                workspace_ids=frozenset(scope),
                variant_id=query.variant_id,
                project_id=query.project_id,
                source_key=query.source_key,
                category=query.category,
                include_superseded=query.include_superseded,
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, evidence_id: str
    ) -> EvidenceRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            record = await repositories.evidence_records.get(evidence_id)
            if record is None:
                raise NotFoundError("evidence", evidence_id)
            recorder = ActivityRecorder(repositories, request)
            await self._require_read(record, actor, repositories, recorder, now)
            return record

    async def history(
        self, actor: ActorContext, request: RequestContext, *, variant_id: str
    ) -> tuple[EvidenceRecord, ...]:
        """Every version of every record about one variant, superseded included."""
        scope = readable_workspace_scope(actor, action=EVIDENCE_READ)
        async with self._services.unit_of_work.begin() as repositories:
            return await repositories.evidence_records.list_for_variant(
                variant_id=variant_id,
                workspace_ids=frozenset(scope),
                include_superseded=True,
            )

    async def conflicts(
        self, actor: ActorContext, request: RequestContext, *, variant_id: str
    ) -> tuple[EvidenceConflict, ...]:
        """Report which retained records disagree. Nothing is resolved or rewritten."""
        scope = readable_workspace_scope(actor, action=EVIDENCE_READ)
        async with self._services.unit_of_work.begin() as repositories:
            records = await repositories.evidence_records.list_for_variant(
                variant_id=variant_id, workspace_ids=frozenset(scope)
            )
        return detect_conflicts(records)

    async def list_batches(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        page: Page,
        source_key: str | None = None,
        state: EvidenceIngestionState | None = None,
    ) -> Paged[Any]:
        scope = readable_workspace_scope(actor, action=EVIDENCE_READ)
        async with self._services.unit_of_work.begin() as repositories:
            return await repositories.evidence_ingestions.list_batches(
                page=page,
                workspace_ids=frozenset(scope),
                source_key=source_key,
                state=state,
            )

    async def batch_findings(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        batch_id: str,
        page: Page,
    ) -> Paged[EvidenceValidationFinding]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            batch = await repositories.evidence_ingestions.get(batch_id)
            if batch is None:
                raise NotFoundError("evidence_ingestion_batch", batch_id)
            recorder = ActivityRecorder(repositories, request)
            await self._require_read(batch, actor, repositories, recorder, now)
            return await repositories.evidence_ingestions.list_findings(
                ingestion_batch_id=batch_id, page=page
            )

    # ------------------------------------------------------------- curation --

    async def record(self, command: RecordEvidenceCommand) -> EvidenceRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
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
            variant = await repositories.variants.get(command.variant_id)
            if variant is None:
                raise NotFoundError("variant", command.variant_id)
            source = await repositories.evidence_sources.get_by_version(
                source_key=command.source_key, version=command.source_version
            )
            if source is None:
                raise NotFoundError(
                    "evidence_source", f"{command.source_key}@{command.source_version}"
                )
            if not source.is_usable:
                raise ValidationError(
                    "this evidence source version may not be used",
                    details={"state": source.state.value},
                )
            if not source.supplies_category(command.category):
                raise ValidationError(
                    "this source is not registered as supplying that evidence category",
                    details={"category": command.category.value},
                )
            record = EvidenceRecord(
                id=new_id("evi"),
                variant_id=variant.id,
                category=command.category,
                # Human-entered stays distinguishable from anything a source
                # delivered, forever.
                origin=DataOrigin.HUMAN_ENTERED,
                source_key=source.source_key,
                source_version=source.version,
                source_resource_id=source.id,
                retrieved_at=now,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                context=EvidenceContext(
                    gene_symbol=command.gene_symbol,
                    condition_identifier=command.condition_identifier,
                    condition_term=command.condition_term,
                    inheritance=command.inheritance,
                ),
                direction=command.direction,
                strength=command.strength,
                applicability=command.applicability,
                state=EvidenceRecordState.AVAILABLE,
                summary=command.summary,
                rationale=command.rationale,
                external_reference=command.external_reference,
                method=command.method,
                payload=dict(command.values or {}),
                provenance={
                    "source_key": source.source_key,
                    "source_version": source.version,
                    "curated_by": command.actor.actor_id,
                    "software_version": self._services.software_version,
                },
                recorded_at=now,
                created_by=command.actor.actor_id,
                created_at=now,
            )
            stored = await repositories.evidence_records.add(record)
            await recorder.audit(
                action="evidence.recorded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="evidence",
                resource_id=stored.id,
                new_state=stored.state.value,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                detail={
                    "variant_id": stored.variant_id,
                    "category": stored.category.value,
                    "source_key": stored.source_key,
                    "source_version": stored.source_version,
                    "origin": stored.origin.value,
                },
            )
            await recorder.event(
                event_type=EventType.EVIDENCE_RECORDED,
                aggregate_type="evidence",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "variant_id": stored.variant_id,
                    "category": stored.category.value,
                    "origin": stored.origin.value,
                },
            )
            return stored

    async def withdraw(self, command: WithdrawEvidenceCommand) -> EvidenceRecord:
        """Mark evidence withdrawn. Nothing is deleted and content is unchanged."""
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record = await repositories.evidence_records.get(command.evidence_id)
            if record is None:
                raise NotFoundError("evidence", command.evidence_id)
            await resolve_scope(
                self._services,
                repositories,
                command.actor,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                action=EVIDENCE_CURATE,
                recorder=recorder,
                occurred_at=now,
            )
            stored = await repositories.evidence_records.save_lifecycle(
                record.withdraw(at=now, reason=command.reason)
            )
            await recorder.audit(
                action="evidence.withdrawn",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="evidence",
                resource_id=stored.id,
                previous_state=record.state.value,
                new_state=stored.state.value,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={"reason": command.reason},
            )
            await recorder.event(
                event_type=EventType.EVIDENCE_WITHDRAWN,
                aggregate_type="evidence",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={"variant_id": stored.variant_id, "reason": command.reason},
            )
            return stored

    # ------------------------------------------------------------ internals --

    async def _require_read(
        self,
        subject: Any,
        actor: ActorContext,
        repositories: Any,
        recorder: ActivityRecorder,
        now: Any,
    ) -> None:
        """Authorize against the scope the *stored row* declares."""
        workspace_id = getattr(subject, "workspace_id", None)
        project_id = getattr(subject, "project_id", None)
        if workspace_id is None and project_id is None:
            # Platform reference evidence: readable by anyone who may read
            # evidence anywhere, since it is not tenant content.
            if not readable_workspace_scope(actor, action=EVIDENCE_READ):
                await self._services.authorization.require(
                    actor,
                    EVIDENCE_READ.workspace,
                    recorder=recorder,
                    occurred_at=now,
                )
            return
        allowed = readable_workspace_scope(
            actor, workspace_id=workspace_id, action=EVIDENCE_READ
        )
        if project_id is not None:
            capabilities = actor.project_capabilities(project_id)
            if EVIDENCE_READ.project in capabilities:
                return
        if workspace_id in allowed:
            return
        # Deliberately the same refusal a caller gets for evidence in a tenant
        # they cannot see, so no existence is leaked by the error itself.
        raise AuthorizationError("this evidence is not accessible")


__all__ = [
    "EvidenceRecords",
    "ListEvidenceQuery",
    "RecordEvidenceCommand",
    "WithdrawEvidenceCommand",
]
