"""Persistence for evidence sources, evidence records and ingestion batches.

Properties enforced by the statements themselves:

* **One registry.** An evidence source version is a ``scientific_resources`` row
  of kind ``evidence_resource``; no second registry exists, so evidence sources
  inherit the platform's resource lifecycle and governance.
* **One evidence model.** Evidence records are ``evidence_items`` rows — the table
  Package 2 established, widened by Package 9. Nothing here introduces a parallel
  evidence table.
* **Nothing is overwritten.** The only UPDATE against an evidence row changes its
  lifecycle state and its supersession pointers. Content — source identity,
  values, context, rationale — is written once, so a superseded version stays
  exactly as it was delivered.
* **Idempotency is a constraint, not a convention.** A batch is unique on
  ``(source_key, payload_digest)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Select, insert, select, update

from app.application.repositories import Page, Paged
from app.domain.errors import NotFoundError
from app.domain.evidence.entities import (
    EvidenceContext,
    EvidenceIngestionBatch,
    EvidenceRecord,
    EvidenceSourceRecord,
    EvidenceValidationFinding,
)
from app.domain.value_objects.enums import (
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceIngestionState,
    EvidenceRecordState,
    EvidenceSourceCategory,
    EvidenceStrength,
    ScientificResourceKind,
    ScientificResourceState,
    ValidationSeverity,
)
from app.infrastructure.persistence.models.evidence_registry import (
    EvidenceIngestionBatchRow,
    EvidenceValidationFindingRow,
)
from app.infrastructure.persistence.models.interpretation import EvidenceItem
from app.infrastructure.persistence.models.scientific import ScientificResource
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_RESOURCES = ScientificResource.__table__
_ITEMS = EvidenceItem.__table__
_BATCHES = EvidenceIngestionBatchRow.__table__
_FINDINGS = EvidenceValidationFindingRow.__table__

#: Evidence-source attributes with no dedicated column on the shared resource
#: table. Kept in its metadata rather than widening a table every other resource
#: kind would then have to carry.
_METADATA_KEYS = (
    "category",
    "provider",
    "release_label",
    "released_at",
    "retrieved_at",
    "schema_version",
    "genome_assembly",
    "supplies",
    "supplies_strength",
)

_USABLE = (
    ScientificResourceState.ACTIVE.value,
    ScientificResourceState.DEPRECATED.value,
)
_CURRENT = (
    EvidenceRecordState.RECORDED.value,
    EvidenceRecordState.AVAILABLE.value,
)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class SqlEvidenceSourceRepository(SqlRepository):
    """Evidence source versions, stored in the scientific resource registry."""

    async def add(self, source: EvidenceSourceRecord) -> EvidenceSourceRecord:
        metadata = dict(source.metadata)
        metadata.update(
            {
                "category": source.category.value,
                "provider": source.provider,
                "release_label": source.release_label,
                "released_at": source.released_at.isoformat() if source.released_at else None,
                "retrieved_at": source.retrieved_at.isoformat()
                if source.retrieved_at
                else None,
                "schema_version": source.schema_version,
                "genome_assembly": source.genome_assembly,
                "supplies": [item.value for item in source.supplies],
                "supplies_strength": source.supplies_strength,
            }
        )
        await self._session.execute(
            insert(_RESOURCES).values(
                id=source.id,
                kind=ScientificResourceKind.EVIDENCE_RESOURCE.value,
                resource_key=source.source_key,
                version=source.version,
                display_name=source.display_name,
                description=source.description,
                state=source.state.value,
                activated_at=source.activated_at,
                deprecated_at=source.deprecated_at,
                retired_at=source.retired_at,
                invalidated_at=source.invalidated_at,
                invalidation_reason=source.invalidation_reason,
                checksum_algorithm=source.checksum_algorithm,
                checksum_value=source.checksum_value,
                size_bytes=source.size_bytes,
                provenance=source.provenance or None,
                licensing=source.licensing or None,
                metadata_json=metadata,
                registered_by=source.registered_by,
            )
        )
        return source

    async def get(self, source_id: str) -> EvidenceSourceRecord | None:
        row = await self._fetch_one(
            select(_RESOURCES).where(
                _RESOURCES.c.id == source_id,
                _RESOURCES.c.kind == ScientificResourceKind.EVIDENCE_RESOURCE.value,
            )
        )
        return _to_source(row) if row else None

    async def get_by_version(
        self, *, source_key: str, version: str
    ) -> EvidenceSourceRecord | None:
        row = await self._fetch_one(
            select(_RESOURCES).where(
                _RESOURCES.c.kind == ScientificResourceKind.EVIDENCE_RESOURCE.value,
                _RESOURCES.c.resource_key == source_key,
                _RESOURCES.c.version == version,
            )
        )
        return _to_source(row) if row else None

    async def save(self, source: EvidenceSourceRecord) -> EvidenceSourceRecord:
        """Persist lifecycle state only; registered content is immutable."""
        result = await self._session.execute(
            update(_RESOURCES)
            .where(_RESOURCES.c.id == source.id, _RESOURCES.c.state != source.state.value)
            .values(
                state=source.state.value,
                activated_at=source.activated_at,
                deprecated_at=source.deprecated_at,
                retired_at=source.retired_at,
                invalidated_at=source.invalidated_at,
                invalidation_reason=source.invalidation_reason,
            )
        )
        if result.rowcount == 0:
            existing = await self._fetch_one(
                select(_RESOURCES.c.id).where(_RESOURCES.c.id == source.id)
            )
            if existing is None:
                raise NotFoundError("evidence source", source.id)
        return source

    async def list_sources(
        self,
        *,
        page: Page,
        category: EvidenceSourceCategory | None = None,
        source_key: str | None = None,
        usable_only: bool = False,
    ) -> Paged[EvidenceSourceRecord]:
        statement: Select = select(_RESOURCES).where(
            _RESOURCES.c.kind == ScientificResourceKind.EVIDENCE_RESOURCE.value
        )
        if category is not None:
            statement = statement.where(
                _RESOURCES.c.metadata_json["category"].astext == category.value
            )
        if source_key is not None:
            statement = statement.where(_RESOURCES.c.resource_key == source_key)
        if usable_only:
            statement = statement.where(_RESOURCES.c.state.in_(_USABLE))
        statement = statement.order_by(
            _RESOURCES.c.resource_key.asc(), _RESOURCES.c.version.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_source(row) for row in rows), total=total, page=page)


class SqlEvidenceRecordRepository(SqlRepository):
    """Evidence records, stored as ``evidence_items`` rows."""

    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        await self._session.execute(insert(_ITEMS).values(**_record_values(record)))
        return record

    async def add_many(self, records: tuple[EvidenceRecord, ...]) -> None:
        if not records:
            return
        await self._session.execute(
            insert(_ITEMS), [_record_values(record) for record in records]
        )

    async def get(self, evidence_id: str) -> EvidenceRecord | None:
        row = await self._fetch_one(select(_ITEMS).where(_ITEMS.c.id == evidence_id))
        return _to_record(row) if row else None

    async def get_by_digest(
        self, *, variant_id: str, source_key: str, payload_digest: str
    ) -> EvidenceRecord | None:
        row = await self._fetch_one(
            select(_ITEMS).where(
                _ITEMS.c.variant_id == variant_id,
                _ITEMS.c.source_key == source_key,
                _ITEMS.c.payload_digest == payload_digest,
            )
        )
        return _to_record(row) if row else None

    async def current_for_lineage(
        self, *, variant_id: str, source_key: str, evidence_key: str
    ) -> EvidenceRecord | None:
        """The live version of one statement from one source, if any."""
        statement = (
            select(_ITEMS)
            .where(
                _ITEMS.c.variant_id == variant_id,
                _ITEMS.c.source_key == source_key,
                _ITEMS.c.evidence_key == evidence_key,
                _ITEMS.c.state.in_(_CURRENT),
            )
            .order_by(_ITEMS.c.version_number.desc())
        )
        row = await self._fetch_one(statement)
        return _to_record(row) if row else None

    async def save_lifecycle(self, record: EvidenceRecord) -> EvidenceRecord:
        """Update state, supersession pointers and provenance — never content."""
        result = await self._session.execute(
            update(_ITEMS)
            .where(_ITEMS.c.id == record.id, _ITEMS.c.version == record.record_version)
            .values(
                state=record.state.value,
                superseded_by_id=record.superseded_by_id,
                provenance=record.provenance or None,
                version=record.record_version + 1,
            )
        )
        if result.rowcount == 0:
            raise NotFoundError("evidence record", record.id)
        from dataclasses import replace

        return replace(record, record_version=record.record_version + 1)

    async def list_records(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        variant_id: str | None = None,
        project_id: str | None = None,
        source_key: str | None = None,
        category: EvidenceCategory | None = None,
        state: EvidenceRecordState | None = None,
        include_superseded: bool = False,
    ) -> Paged[EvidenceRecord]:
        statement: Select = select(_ITEMS)
        if workspace_ids is not None:
            # Platform-wide evidence (no workspace) stays visible; tenant evidence
            # is restricted to workspaces the caller may actually read.
            statement = statement.where(
                _ITEMS.c.workspace_id.is_(None)
                | _ITEMS.c.workspace_id.in_(tuple(workspace_ids) or ("",))
            )
        if variant_id is not None:
            statement = statement.where(_ITEMS.c.variant_id == variant_id)
        if project_id is not None:
            statement = statement.where(_ITEMS.c.project_id == project_id)
        if source_key is not None:
            statement = statement.where(_ITEMS.c.source_key == source_key)
        if category is not None:
            statement = statement.where(_ITEMS.c.category == category.value)
        if state is not None:
            statement = statement.where(_ITEMS.c.state == state.value)
        elif not include_superseded:
            statement = statement.where(_ITEMS.c.state.in_(_CURRENT))
        statement = statement.order_by(
            _ITEMS.c.variant_id.asc(),
            _ITEMS.c.source_key.asc(),
            _ITEMS.c.version_number.desc(),
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_record(row) for row in rows), total=total, page=page)

    async def list_for_variant(
        self,
        *,
        variant_id: str,
        workspace_ids: frozenset[str] | None = None,
        include_superseded: bool = False,
        limit: int = 500,
    ) -> tuple[EvidenceRecord, ...]:
        """Every record about one variant, for conflict reporting and history."""
        statement: Select = select(_ITEMS).where(_ITEMS.c.variant_id == variant_id)
        if workspace_ids is not None:
            statement = statement.where(
                _ITEMS.c.workspace_id.is_(None)
                | _ITEMS.c.workspace_id.in_(tuple(workspace_ids) or ("",))
            )
        if not include_superseded:
            statement = statement.where(_ITEMS.c.state.in_(_CURRENT))
        rows = await self._fetch_all(
            statement.order_by(_ITEMS.c.created_at.asc()).limit(limit)
        )
        return tuple(_to_record(row) for row in rows)


class SqlEvidenceIngestionRepository(SqlRepository):
    """Evidence ingestion batches and their validation findings."""

    async def add(self, batch: EvidenceIngestionBatch) -> EvidenceIngestionBatch:
        await self._session.execute(
            insert(_BATCHES).values(
                id=batch.id,
                source_key=batch.source_key,
                source_version=batch.source_version,
                source_resource_id=batch.source_resource_id,
                payload_digest=batch.payload_digest,
                state=batch.state.value,
                origin=batch.origin.value,
                workspace_id=batch.workspace_id,
                project_id=batch.project_id,
                file_artifact_id=batch.file_artifact_id,
                claimed_record_count=batch.claimed_record_count,
                stored_record_count=batch.stored_record_count,
                superseded_record_count=batch.superseded_record_count,
                duplicate_record_count=batch.duplicate_record_count,
                rejected_record_count=batch.rejected_record_count,
                retrieved_at=batch.retrieved_at,
                source_released_at=batch.source_released_at,
                requested_by=batch.requested_by,
                service_account_id=batch.service_account_id,
                job_id=batch.job_id,
                correlation_id=batch.correlation_id,
                provenance=batch.provenance or None,
                failure_code=batch.failure_code,
                failure_message=batch.failure_message,
                completed_at=batch.completed_at,
            )
        )
        return batch

    async def get(self, batch_id: str) -> EvidenceIngestionBatch | None:
        row = await self._fetch_one(select(_BATCHES).where(_BATCHES.c.id == batch_id))
        return _to_batch(row) if row else None

    async def get_by_payload_digest(
        self, *, source_key: str, payload_digest: str
    ) -> EvidenceIngestionBatch | None:
        row = await self._fetch_one(
            select(_BATCHES).where(
                _BATCHES.c.source_key == source_key,
                _BATCHES.c.payload_digest == payload_digest,
            )
        )
        return _to_batch(row) if row else None

    async def save(self, batch: EvidenceIngestionBatch) -> EvidenceIngestionBatch:
        version = await self._versioned_update(
            _BATCHES,
            entity_id=batch.id,
            expected_version=batch.record_version,
            values={
                "state": batch.state.value,
                "stored_record_count": batch.stored_record_count,
                "superseded_record_count": batch.superseded_record_count,
                "duplicate_record_count": batch.duplicate_record_count,
                "rejected_record_count": batch.rejected_record_count,
                "failure_code": batch.failure_code,
                "failure_message": batch.failure_message,
                "completed_at": batch.completed_at,
            },
        )
        from dataclasses import replace

        return replace(batch, record_version=version)

    async def list_batches(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        source_key: str | None = None,
        state: EvidenceIngestionState | None = None,
    ) -> Paged[EvidenceIngestionBatch]:
        statement: Select = select(_BATCHES)
        if workspace_ids is not None:
            statement = statement.where(
                _BATCHES.c.workspace_id.is_(None)
                | _BATCHES.c.workspace_id.in_(tuple(workspace_ids) or ("",))
            )
        if source_key is not None:
            statement = statement.where(_BATCHES.c.source_key == source_key)
        if state is not None:
            statement = statement.where(_BATCHES.c.state == state.value)
        statement = statement.order_by(_BATCHES.c.created_at.desc())
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_batch(row) for row in rows), total=total, page=page)

    async def add_findings(
        self, findings: tuple[EvidenceValidationFinding, ...]
    ) -> None:
        if not findings:
            return
        await self._session.execute(
            insert(_FINDINGS),
            [
                {
                    "id": finding.id or new_id("evf"),
                    "ingestion_batch_id": finding.ingestion_batch_id,
                    "code": finding.code,
                    "message": finding.message,
                    "severity": finding.severity.value,
                    "evidence_id": finding.evidence_id,
                    "variant_id": finding.variant_id,
                    "record_index": finding.record_index,
                    "detail": finding.detail or None,
                }
                for finding in findings
            ],
        )

    async def list_findings(
        self, *, ingestion_batch_id: str, page: Page
    ) -> Paged[EvidenceValidationFinding]:
        statement: Select = (
            select(_FINDINGS)
            .where(_FINDINGS.c.ingestion_batch_id == ingestion_batch_id)
            .order_by(_FINDINGS.c.record_index.asc(), _FINDINGS.c.code.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(
            items=tuple(
                EvidenceValidationFinding(
                    id=row["id"],
                    ingestion_batch_id=row["ingestion_batch_id"],
                    code=row["code"],
                    message=row["message"],
                    severity=ValidationSeverity(row["severity"]),
                    evidence_id=row["evidence_id"],
                    variant_id=row["variant_id"],
                    record_index=row["record_index"],
                    detail=dict(row["detail"] or {}),
                    created_at=row["created_at"],
                )
                for row in rows
            ),
            total=total,
            page=page,
        )


def _record_values(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "variant_id": record.variant_id,
        "workspace_id": record.workspace_id,
        "project_id": record.project_id,
        "category": record.category.value,
        "strength": record.strength.value,
        "direction": record.direction.value,
        "summary": record.summary,
        "rationale": record.rationale,
        "origin": record.origin.value,
        "source_resource_id": record.source_resource_id,
        "clinical_assertion_id": record.clinical_assertion_id,
        "external_reference": record.external_reference,
        "scientific_execution_id": record.scientific_execution_id,
        "created_by": record.created_by,
        "recorded_at": record.recorded_at,
        "payload": record.payload or None,
        "source_key": record.source_key,
        "source_version": record.source_version,
        "source_identifier": record.source_identifier,
        "source_released_at": record.source_released_at,
        "retrieved_at": record.retrieved_at,
        "gene_symbol": record.context.gene_symbol,
        "gene_identifier": record.context.gene_identifier,
        "transcript_identifier": record.context.transcript_identifier,
        "condition_identifier": record.context.condition_identifier,
        "condition_term": record.context.condition_term,
        "inheritance": record.context.inheritance,
        "applicability": record.applicability.value,
        "state": record.state.value,
        "method": record.method,
        "evidence_key": record.evidence_key,
        "version_number": record.version_number,
        "supersedes_id": record.supersedes_id,
        "superseded_by_id": record.superseded_by_id,
        "ingestion_batch_id": record.ingestion_batch_id,
        "payload_digest": record.payload_digest,
        "provenance": record.provenance or None,
    }


def _to_record(row: Mapping[str, Any]) -> EvidenceRecord:
    return EvidenceRecord(
        id=row["id"],
        variant_id=row["variant_id"],
        category=EvidenceCategory(row["category"]),
        origin=DataOrigin(row["origin"]),
        source_key=row["source_key"],
        source_version=row["source_version"],
        source_resource_id=row["source_resource_id"],
        source_identifier=row["source_identifier"],
        source_released_at=row["source_released_at"],
        retrieved_at=row["retrieved_at"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        context=EvidenceContext(
            gene_symbol=row["gene_symbol"],
            gene_identifier=row["gene_identifier"],
            transcript_identifier=row["transcript_identifier"],
            condition_identifier=row["condition_identifier"],
            condition_term=row["condition_term"],
            inheritance=row["inheritance"],
        ),
        direction=CriterionDirection(row["direction"]),
        strength=EvidenceStrength(row["strength"]),
        applicability=EvidenceApplicability(row["applicability"]),
        state=EvidenceRecordState(row["state"]),
        summary=row["summary"],
        rationale=row["rationale"],
        external_reference=row["external_reference"],
        method=row["method"],
        evidence_key=row["evidence_key"],
        version_number=row["version_number"],
        supersedes_id=row["supersedes_id"],
        superseded_by_id=row["superseded_by_id"],
        ingestion_batch_id=row["ingestion_batch_id"],
        payload_digest=row["payload_digest"],
        clinical_assertion_id=row["clinical_assertion_id"],
        scientific_execution_id=row["scientific_execution_id"],
        payload=dict(row["payload"] or {}),
        provenance=dict(row["provenance"] or {}),
        recorded_at=row["recorded_at"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        record_version=row["version"],
    )


def _to_batch(row: Mapping[str, Any]) -> EvidenceIngestionBatch:
    return EvidenceIngestionBatch(
        id=row["id"],
        source_key=row["source_key"],
        source_version=row["source_version"],
        payload_digest=row["payload_digest"],
        state=EvidenceIngestionState(row["state"]),
        source_resource_id=row["source_resource_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        origin=DataOrigin(row["origin"]),
        file_artifact_id=row["file_artifact_id"],
        claimed_record_count=row["claimed_record_count"],
        stored_record_count=row["stored_record_count"],
        superseded_record_count=row["superseded_record_count"],
        duplicate_record_count=row["duplicate_record_count"],
        rejected_record_count=row["rejected_record_count"],
        retrieved_at=row["retrieved_at"],
        source_released_at=row["source_released_at"],
        requested_by=row["requested_by"],
        service_account_id=row["service_account_id"],
        job_id=row["job_id"],
        correlation_id=row["correlation_id"],
        provenance=dict(row["provenance"] or {}),
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        record_version=row["version"],
    )


def _to_source(row: Mapping[str, Any]) -> EvidenceSourceRecord:
    metadata = dict(row["metadata_json"] or {})
    extra = {key: value for key, value in metadata.items() if key not in _METADATA_KEYS}
    return EvidenceSourceRecord(
        id=row["id"],
        source_key=row["resource_key"],
        version=row["version"],
        display_name=row["display_name"],
        category=EvidenceSourceCategory(
            metadata.get("category") or EvidenceSourceCategory.OTHER.value
        ),
        state=ScientificResourceState(row["state"]),
        provider=metadata.get("provider"),
        description=row["description"],
        release_label=metadata.get("release_label"),
        released_at=_parse_datetime(metadata.get("released_at")),
        retrieved_at=_parse_datetime(metadata.get("retrieved_at")),
        schema_version=metadata.get("schema_version"),
        genome_assembly=metadata.get("genome_assembly"),
        checksum_algorithm=row["checksum_algorithm"],
        checksum_value=row["checksum_value"],
        size_bytes=row["size_bytes"],
        supplies=tuple(
            EvidenceCategory(item) for item in (metadata.get("supplies") or ())
        ),
        supplies_strength=bool(metadata.get("supplies_strength")),
        provenance=dict(row["provenance"] or {}),
        licensing=dict(row["licensing"] or {}),
        metadata=extra,
        registered_by=row["registered_by"],
        activated_at=row["activated_at"],
        deprecated_at=row["deprecated_at"],
        retired_at=row["retired_at"],
        invalidated_at=row["invalidated_at"],
        invalidation_reason=row["invalidation_reason"],
        created_at=row["created_at"],
        record_version=1,
    )


__all__ = [
    "SqlEvidenceIngestionRepository",
    "SqlEvidenceRecordRepository",
    "SqlEvidenceSourceRepository",
]
