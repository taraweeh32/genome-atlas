"""In-memory doubles for the evidence repositories.

They mirror the SQL repositories' *semantics*, which for this package means:

* a source version is identified by ``(source_key, version)`` and its content is
  never rewritten — only lifecycle state moves;
* evidence records are append-only: a new version is a new row and the previous one
  is marked superseded, never edited;
* a delivery is unique per ``(source_key, payload_digest)``, so redelivery is
  detected here exactly as the unique constraint detects it in PostgreSQL;
* listings apply the same scope clause the SQL builds — platform-wide evidence
  stays visible, tenant evidence is restricted to the caller's workspaces — so a
  test that leaks across tenants in memory would leak in PostgreSQL too.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.application.repositories import Page, Paged
from app.domain.errors import ConcurrencyConflictError, ConflictError
from app.domain.evidence.entities import (
    EvidenceIngestionBatch,
    EvidenceRecord,
    EvidenceSourceRecord,
    EvidenceValidationFinding,
)
from app.domain.value_objects.enums import (
    EvidenceCategory,
    EvidenceIngestionState,
    EvidenceRecordState,
    EvidenceSourceCategory,
    ScientificResourceState,
)

_CURRENT = {EvidenceRecordState.RECORDED, EvidenceRecordState.AVAILABLE}
_USABLE = {ScientificResourceState.ACTIVE, ScientificResourceState.DEPRECATED}


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


def _visible(row, workspace_ids: frozenset[str] | None) -> bool:
    if workspace_ids is None:
        return True
    return row.workspace_id is None or row.workspace_id in workspace_ids


@dataclass
class MemoryEvidenceSources:
    items: dict[str, EvidenceSourceRecord] = field(default_factory=dict)

    async def add(self, source: EvidenceSourceRecord) -> EvidenceSourceRecord:
        for existing in self.items.values():
            if (
                existing.source_key == source.source_key
                and existing.version == source.version
            ):
                raise ConflictError("this evidence source version already exists")
        self.items[source.id] = source
        return source

    async def get(self, source_id: str) -> EvidenceSourceRecord | None:
        return self.items.get(source_id)

    async def get_by_version(
        self, *, source_key: str, version: str
    ) -> EvidenceSourceRecord | None:
        for source in self.items.values():
            if source.source_key == source_key and source.version == version:
                return source
        return None

    async def save(self, source: EvidenceSourceRecord) -> EvidenceSourceRecord:
        current = self.items[source.id]
        # Content is immutable; only the lifecycle fields are carried over.
        self.items[source.id] = replace(
            current,
            state=source.state,
            activated_at=source.activated_at,
            deprecated_at=source.deprecated_at,
            retired_at=source.retired_at,
            invalidated_at=source.invalidated_at,
            invalidation_reason=source.invalidation_reason,
            record_version=current.record_version + 1,
        )
        return self.items[source.id]

    async def list_sources(
        self,
        *,
        page: Page,
        category: EvidenceSourceCategory | None = None,
        source_key: str | None = None,
        usable_only: bool = False,
    ) -> Paged[EvidenceSourceRecord]:
        items = [
            source
            for source in self.items.values()
            if (category is None or source.category is category)
            and (source_key is None or source.source_key == source_key)
            and (not usable_only or source.state in _USABLE)
        ]
        items.sort(key=lambda source: (source.source_key, source.version))
        return _paged(items, page)


@dataclass
class MemoryEvidenceRecords:
    items: dict[str, EvidenceRecord] = field(default_factory=dict)

    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        self.items[record.id] = record
        return record

    async def add_many(self, records: tuple[EvidenceRecord, ...]) -> None:
        for record in records:
            self.items[record.id] = record

    async def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self.items.get(evidence_id)

    async def get_by_digest(
        self, *, variant_id: str, source_key: str, payload_digest: str
    ) -> EvidenceRecord | None:
        for record in self.items.values():
            if (
                record.variant_id == variant_id
                and record.source_key == source_key
                and record.payload_digest == payload_digest
            ):
                return record
        return None

    async def current_for_lineage(
        self, *, variant_id: str, source_key: str, evidence_key: str
    ) -> EvidenceRecord | None:
        candidates = [
            record
            for record in self.items.values()
            if record.variant_id == variant_id
            and record.source_key == source_key
            and record.evidence_key == evidence_key
            and record.state in _CURRENT
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda record: record.version_number)

    async def save_lifecycle(self, record: EvidenceRecord) -> EvidenceRecord:
        current = self.items[record.id]
        if current.record_version != record.record_version:
            raise ConcurrencyConflictError(
                f"evidence {record.id} was modified concurrently"
            )
        # State, supersession pointers and provenance only — never content.
        self.items[record.id] = replace(
            current,
            state=record.state,
            superseded_by_id=record.superseded_by_id,
            provenance=dict(record.provenance),
            record_version=current.record_version + 1,
        )
        return self.items[record.id]

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
        items = [
            record
            for record in self.items.values()
            if _visible(record, workspace_ids)
            and (variant_id is None or record.variant_id == variant_id)
            and (project_id is None or record.project_id == project_id)
            and (source_key is None or record.source_key == source_key)
            and (category is None or record.category is category)
            and (
                record.state is state
                if state is not None
                else (include_superseded or record.state in _CURRENT)
            )
        ]
        items.sort(
            key=lambda record: (
                record.variant_id,
                record.source_key or "",
                -record.version_number,
            )
        )
        return _paged(items, page)

    async def list_for_variant(
        self,
        *,
        variant_id: str,
        workspace_ids: frozenset[str] | None = None,
        include_superseded: bool = False,
        limit: int = 500,
    ) -> tuple[EvidenceRecord, ...]:
        items = [
            record
            for record in self.items.values()
            if record.variant_id == variant_id
            and _visible(record, workspace_ids)
            and (include_superseded or record.state in _CURRENT)
        ]
        items.sort(key=lambda record: (record.created_at, record.id))
        return tuple(items[:limit])


@dataclass
class MemoryEvidenceIngestions:
    items: dict[str, EvidenceIngestionBatch] = field(default_factory=dict)
    findings: list[EvidenceValidationFinding] = field(default_factory=list)

    async def add(self, batch: EvidenceIngestionBatch) -> EvidenceIngestionBatch:
        for existing in self.items.values():
            if (
                existing.source_key == batch.source_key
                and existing.payload_digest == batch.payload_digest
            ):
                raise ConflictError("this evidence delivery was already ingested")
        self.items[batch.id] = batch
        return batch

    async def get(self, batch_id: str) -> EvidenceIngestionBatch | None:
        return self.items.get(batch_id)

    async def get_by_payload_digest(
        self, *, source_key: str, payload_digest: str
    ) -> EvidenceIngestionBatch | None:
        for batch in self.items.values():
            if (
                batch.source_key == source_key
                and batch.payload_digest == payload_digest
            ):
                return batch
        return None

    async def save(self, batch: EvidenceIngestionBatch) -> EvidenceIngestionBatch:
        current = self.items[batch.id]
        if current.record_version != batch.record_version:
            raise ConcurrencyConflictError(
                f"evidence delivery {batch.id} was modified concurrently"
            )
        self.items[batch.id] = replace(batch, record_version=current.record_version + 1)
        return self.items[batch.id]

    async def list_batches(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        source_key: str | None = None,
        state: EvidenceIngestionState | None = None,
    ) -> Paged[EvidenceIngestionBatch]:
        items = [
            batch
            for batch in self.items.values()
            if _visible(batch, workspace_ids)
            and (source_key is None or batch.source_key == source_key)
            and (state is None or batch.state is state)
        ]
        items.sort(key=lambda batch: (batch.created_at, batch.id), reverse=True)
        return _paged(items, page)

    async def add_findings(
        self, findings: tuple[EvidenceValidationFinding, ...]
    ) -> None:
        self.findings.extend(findings)

    async def list_findings(
        self, *, ingestion_batch_id: str, page: Page
    ) -> Paged[EvidenceValidationFinding]:
        items = [
            finding
            for finding in self.findings
            if finding.ingestion_batch_id == ingestion_batch_id
        ]
        items.sort(key=lambda finding: (finding.record_index or -1, finding.code))
        return _paged(items, page)


__all__ = [
    "MemoryEvidenceIngestions",
    "MemoryEvidenceRecords",
    "MemoryEvidenceSources",
]
