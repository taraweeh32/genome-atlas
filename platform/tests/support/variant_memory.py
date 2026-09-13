"""In-memory doubles for the scientific data layer's repositories.

These mirror the SQL repositories' *semantics*, not their statements — in
particular the three that the use cases depend on for correctness:

* canonical variants converge on one row per canonical key (``get_or_add``
  reports whether it created the row, so a caller can tell a new variant from a
  re-observed one);
* a source representation can be linked to a canonical variant only while it has
  none, so an import can never re-point history;
* result sets, artifacts and ingestion requests enforce optimistic concurrency,
  so a lost update surfaces as a conflict instead of a silently discarded state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.application.repositories import Page, Paged
from app.domain.errors import ConcurrencyConflictError
from app.domain.value_objects.enums import (
    DeletionState,
    ResultIngestionState,
    ResultSetState,
)
from app.domain.variant.entities import (
    ClinicalAssertionRecord,
    DatasetVersionVariant,
    GeneReference,
    PopulationFrequencyRecord,
    PopulationRecord,
    SampleObservation,
    SampleRecord,
    TranscriptContext,
    TranscriptReference,
    VariantAnnotationRecord,
    VariantExternalIdentifier,
    VariantRecord,
    VariantRepresentation,
    VariantSourceRepresentation,
)
from app.domain.variant.results import (
    ResultArtifactRecord,
    ResultIngestionRequest,
    ResultSetRecord,
)


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


def _bump(entity, expected_version: int):  # noqa: ANN001, ANN202
    if entity.version != expected_version:
        raise ConcurrencyConflictError(
            f"{type(entity).__name__.lower()} {entity.id} was modified concurrently"
        )
    return replace(entity, version=entity.version + 1)


@dataclass
class MemoryVariants:
    rows: dict[str, VariantRecord] = field(default_factory=dict)
    by_key: dict[str, str] = field(default_factory=dict)

    async def get(self, variant_id: str) -> VariantRecord | None:
        return self.rows.get(variant_id)

    async def get_by_canonical_key(self, canonical_key: str) -> VariantRecord | None:
        variant_id = self.by_key.get(canonical_key)
        return self.rows.get(variant_id) if variant_id else None

    async def add(self, variant: VariantRecord) -> VariantRecord:
        self.rows[variant.id] = variant
        self.by_key[variant.canonical_key] = variant.id
        return variant

    async def get_or_add(self, variant: VariantRecord) -> tuple[VariantRecord, bool]:
        existing = await self.get_by_canonical_key(variant.canonical_key)
        if existing is not None:
            return existing, False
        return await self.add(variant), True

    async def list_for_dataset_version(
        self,
        dataset_version_id: str,
        *,
        page: Page,
        contig: str | None = None,
        position_from: int | None = None,
        position_to: int | None = None,
        query: str | None = None,
        memberships: "MemoryDatasetVersionVariants | None" = None,
    ) -> Paged[VariantRecord]:
        source = memberships or self.memberships
        variant_ids = {
            row.variant_id
            for row in source.rows.values()
            if row.dataset_version_id == dataset_version_id
        }
        items = [self.rows[v] for v in variant_ids if v in self.rows]
        if contig is not None:
            items = [v for v in items if v.identity.contig.canonical == contig]
        if position_from is not None:
            items = [v for v in items if v.identity.position >= position_from]
        if position_to is not None:
            items = [v for v in items if v.identity.position <= position_to]
        if query:
            needle = query.lower()
            items = [v for v in items if needle in v.canonical_key.lower()]
        items.sort(key=lambda v: (v.identity.contig.canonical, v.identity.position, v.id))
        return _paged(items, page)

    async def count_for_dataset_version(self, dataset_version_id: str) -> int:
        return sum(
            1
            for row in self.memberships.rows.values()
            if row.dataset_version_id == dataset_version_id
        )

    #: Set by ``MemoryRepositories.__post_init__``; the SQL repository reaches the
    #: same rows with a join.
    memberships: "MemoryDatasetVersionVariants" = None  # type: ignore[assignment]


@dataclass
class MemoryVariantRepresentations:
    rows: dict[str, VariantRepresentation] = field(default_factory=dict)

    async def add_many(
        self, representations: tuple[VariantRepresentation, ...]
    ) -> tuple[VariantRepresentation, ...]:
        for item in representations:
            key = (item.source_representation_id, item.normalization_version)
            if any(
                (r.source_representation_id, r.normalization_version) == key
                for r in self.rows.values()
                if item.source_representation_id is not None
            ):
                continue
            self.rows[item.id] = item
        return representations

    async def list_for_variant(self, variant_id: str) -> tuple[VariantRepresentation, ...]:
        items = [r for r in self.rows.values() if r.variant_id == variant_id]
        return tuple(sorted(items, key=lambda r: (r.recorded_at or 0, r.id)))

    async def list_for_source_representation(
        self, source_representation_id: str
    ) -> tuple[VariantRepresentation, ...]:
        items = [
            r
            for r in self.rows.values()
            if r.source_representation_id == source_representation_id
        ]
        return tuple(sorted(items, key=lambda r: (r.recorded_at or 0, r.id)))


@dataclass
class MemoryVariantSourceRepresentations:
    rows: dict[str, VariantSourceRepresentation] = field(default_factory=dict)

    async def add_many(
        self, representations: tuple[VariantSourceRepresentation, ...]
    ) -> tuple[VariantSourceRepresentation, ...]:
        for item in representations:
            if await self.find_by_source_key(
                dataset_version_id=item.dataset_version_id,
                source_record_key=item.source_record_key,
            ):
                continue
            self.rows[item.id] = item
        return representations

    async def get(self, representation_id: str) -> VariantSourceRepresentation | None:
        return self.rows.get(representation_id)

    async def link_variant(
        self, *, representation_id: str, variant_id: str
    ) -> VariantSourceRepresentation | None:
        current = self.rows.get(representation_id)
        if current is None:
            return None
        if current.variant_id is not None:
            # Already resolved: the earlier link stands. Silently re-pointing it
            # would rewrite what a past analysis was run against.
            return current
        updated = current.linked_to(variant_id=variant_id)
        self.rows[representation_id] = updated
        return updated

    async def list_for_variant(
        self, variant_id: str, *, dataset_version_id: str | None = None
    ) -> tuple[VariantSourceRepresentation, ...]:
        items = [r for r in self.rows.values() if r.variant_id == variant_id]
        if dataset_version_id is not None:
            items = [r for r in items if r.dataset_version_id == dataset_version_id]
        return tuple(sorted(items, key=lambda r: r.id))

    async def find_by_source_key(
        self, *, dataset_version_id: str, source_record_key: str
    ) -> VariantSourceRepresentation | None:
        for row in self.rows.values():
            if (
                row.dataset_version_id == dataset_version_id
                and row.source_record_key == source_record_key
            ):
                return row
        return None


@dataclass
class MemoryDatasetVersionVariants:
    rows: dict[str, DatasetVersionVariant] = field(default_factory=dict)

    async def add_many(
        self, memberships: tuple[DatasetVersionVariant, ...]
    ) -> tuple[DatasetVersionVariant, ...]:
        for item in memberships:
            pair = (item.dataset_version_id, item.variant_id)
            if any(
                (r.dataset_version_id, r.variant_id) == pair for r in self.rows.values()
            ):
                continue
            self.rows[item.id] = item
        return memberships

    async def workspace_ids_for_variant(self, variant_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {r.workspace_id for r in self.rows.values() if r.variant_id == variant_id}
            )
        )

    async def list_dataset_versions(self, variant_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    r.dataset_version_id
                    for r in self.rows.values()
                    if r.variant_id == variant_id
                }
            )
        )


@dataclass
class MemoryVariantIdentifiers:
    rows: dict[str, VariantExternalIdentifier] = field(default_factory=dict)

    async def add_many(
        self, identifiers: tuple[VariantExternalIdentifier, ...]
    ) -> tuple[VariantExternalIdentifier, ...]:
        for item in identifiers:
            triple = (item.variant_id, item.namespace, item.external_identifier)
            if any(
                (r.variant_id, r.namespace, r.external_identifier) == triple
                for r in self.rows.values()
            ):
                continue
            self.rows[item.id] = item
        return identifiers

    async def list_for_variant(
        self, variant_id: str
    ) -> tuple[VariantExternalIdentifier, ...]:
        items = [r for r in self.rows.values() if r.variant_id == variant_id]
        return tuple(sorted(items, key=lambda r: (r.namespace, r.external_identifier)))


@dataclass
class MemoryVariantContexts:
    transcript_contexts: dict[str, TranscriptContext] = field(default_factory=dict)
    observations: dict[str, SampleObservation] = field(default_factory=dict)
    annotations: dict[str, VariantAnnotationRecord] = field(default_factory=dict)
    frequencies: dict[str, PopulationFrequencyRecord] = field(default_factory=dict)
    clinical_assertions: dict[str, ClinicalAssertionRecord] = field(default_factory=dict)
    populations: dict[str, PopulationRecord] = field(default_factory=dict)

    async def get_or_add_population(
        self, population: PopulationRecord
    ) -> tuple[PopulationRecord, bool]:
        for row in self.populations.values():
            if (
                row.population_resource_id == population.population_resource_id
                and row.population_key == population.population_key
            ):
                return row, False
        self.populations[population.id] = population
        return population, True

    async def add_transcript_contexts(
        self, contexts: tuple[TranscriptContext, ...]
    ) -> tuple[TranscriptContext, ...]:
        for item in contexts:
            self.transcript_contexts[item.id] = item
        return contexts

    async def list_transcript_contexts(
        self, variant_id: str, *, page: Page
    ) -> Paged[TranscriptContext]:
        items = [
            c for c in self.transcript_contexts.values() if c.variant_id == variant_id
        ]
        return _paged(sorted(items, key=lambda c: (c.transcript_id or "", c.id)), page)

    async def add_observations(
        self, observations: tuple[SampleObservation, ...]
    ) -> tuple[SampleObservation, ...]:
        for item in observations:
            triple = (item.sample_id, item.variant_id, item.dataset_version_id)
            if any(
                (o.sample_id, o.variant_id, o.dataset_version_id) == triple
                for o in self.observations.values()
            ):
                continue
            self.observations[item.id] = item
        return observations

    async def list_observations(
        self,
        variant_id: str,
        *,
        page: Page,
        dataset_version_id: str | None = None,
    ) -> Paged[SampleObservation]:
        items = [o for o in self.observations.values() if o.variant_id == variant_id]
        if dataset_version_id is not None:
            items = [o for o in items if o.dataset_version_id == dataset_version_id]
        return _paged(sorted(items, key=lambda o: (o.sample_id, o.id)), page)

    async def add_annotations(
        self, annotations: tuple[VariantAnnotationRecord, ...]
    ) -> tuple[VariantAnnotationRecord, ...]:
        for item in annotations:
            self.annotations[item.id] = item
        return annotations

    async def list_annotations(
        self, variant_id: str, *, page: Page, source_key: str | None = None
    ) -> Paged[VariantAnnotationRecord]:
        items = [a for a in self.annotations.values() if a.variant_id == variant_id]
        if source_key is not None:
            items = [a for a in items if a.annotation_resource_id == source_key]
        return _paged(
            sorted(items, key=lambda a: (a.field_key, a.resource_version or "", a.id)), page
        )

    async def add_frequencies(
        self, frequencies: tuple[PopulationFrequencyRecord, ...]
    ) -> tuple[PopulationFrequencyRecord, ...]:
        for item in frequencies:
            quad = (
                item.variant_id,
                item.population_id,
                item.population_resource_id,
                item.resource_version,
            )
            if any(
                (f.variant_id, f.population_id, f.population_resource_id, f.resource_version)
                == quad
                for f in self.frequencies.values()
            ):
                continue
            self.frequencies[item.id] = item
        return frequencies

    async def list_frequencies(
        self, variant_id: str, *, page: Page
    ) -> Paged[PopulationFrequencyRecord]:
        items = [f for f in self.frequencies.values() if f.variant_id == variant_id]
        return _paged(
            sorted(
                items,
                key=lambda f: (
                    f.population_resource_id,
                    f.resource_version or "",
                    f.population_id,
                ),
            ),
            page,
        )

    async def add_clinical_assertions(
        self, assertions: tuple[ClinicalAssertionRecord, ...]
    ) -> tuple[ClinicalAssertionRecord, ...]:
        for item in assertions:
            triple = (item.source_id, item.external_record_identifier, item.variant_id)
            if any(
                (a.source_id, a.external_record_identifier, a.variant_id) == triple
                for a in self.clinical_assertions.values()
            ):
                continue
            self.clinical_assertions[item.id] = item
        return assertions

    async def list_clinical_assertions(
        self, variant_id: str, *, page: Page
    ) -> Paged[ClinicalAssertionRecord]:
        items = [
            a for a in self.clinical_assertions.values() if a.variant_id == variant_id
        ]
        return _paged(
            sorted(items, key=lambda a: (a.source_id, a.external_record_identifier)), page
        )


@dataclass
class MemorySamples:
    rows: dict[str, SampleRecord] = field(default_factory=dict)

    async def get(self, sample_id: str) -> SampleRecord | None:
        return self.rows.get(sample_id)

    async def get_or_add(self, sample: SampleRecord) -> tuple[SampleRecord, bool]:
        for row in self.rows.values():
            if (
                row.dataset_version_id == sample.dataset_version_id
                and row.sample_key == sample.sample_key
            ):
                return row, False
        self.rows[sample.id] = sample
        return sample, True

    async def find_by_key(
        self, *, workspace_id: str, sample_key: str
    ) -> SampleRecord | None:
        for row in self.rows.values():
            if row.workspace_id == workspace_id and row.sample_key == sample_key:
                return row
        return None

    async def list_for_workspace(
        self, workspace_id: str, *, page: Page
    ) -> Paged[SampleRecord]:
        items = [s for s in self.rows.values() if s.workspace_id == workspace_id]
        return _paged(sorted(items, key=lambda s: s.sample_key), page)


@dataclass
class MemoryGenesTranscripts:
    genes: dict[str, GeneReference] = field(default_factory=dict)
    transcripts: dict[str, TranscriptReference] = field(default_factory=dict)

    async def get_or_add_gene(self, gene: GeneReference) -> tuple[GeneReference, bool]:
        existing = await self.find_gene(
            source_key=gene.namespace, gene_identifier=gene.gene_identifier
        )
        if existing is not None:
            return existing, False
        self.genes[gene.id] = gene
        return gene, True

    async def get_or_add_transcript(
        self, transcript: TranscriptReference
    ) -> tuple[TranscriptReference, bool]:
        existing = await self.find_transcript(
            source_key=transcript.namespace,
            transcript_identifier=transcript.transcript_identifier,
        )
        if existing is not None and existing.transcript_version == (
            transcript.transcript_version
        ):
            return existing, False
        self.transcripts[transcript.id] = transcript
        return transcript, True

    async def find_gene(
        self, *, source_key: str, gene_identifier: str
    ) -> GeneReference | None:
        for row in self.genes.values():
            if row.namespace == source_key and row.gene_identifier == gene_identifier:
                return row
        return None

    async def find_transcript(
        self, *, source_key: str, transcript_identifier: str
    ) -> TranscriptReference | None:
        matches = [
            row
            for row in self.transcripts.values()
            if row.namespace == source_key
            and row.transcript_identifier == transcript_identifier
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda r: r.transcript_version or "")[-1]


@dataclass
class MemoryResultSets:
    rows: dict[str, ResultSetRecord] = field(default_factory=dict)

    async def add(self, result_set: ResultSetRecord) -> ResultSetRecord:
        self.rows[result_set.id] = result_set
        return result_set

    async def get(self, result_set_id: str) -> ResultSetRecord | None:
        return self.rows.get(result_set_id)

    async def save(self, result_set: ResultSetRecord) -> ResultSetRecord:
        updated = _bump(result_set, self.rows[result_set.id].version)
        self.rows[result_set.id] = updated
        return updated

    async def find_by_result_key(
        self, *, analysis_execution_id: str, result_key: str
    ) -> ResultSetRecord | None:
        matches = [
            r
            for r in self.rows.values()
            if r.provenance.analysis_execution_id == analysis_execution_id
            and r.result_key == result_key
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda r: r.id)[-1]

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        analysis_execution_id: str | None = None,
        states: tuple[ResultSetState, ...] = (),
    ) -> Paged[ResultSetRecord]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        items = [
            r
            for r in self.rows.values()
            if r.workspace_id in workspace_ids
            and r.deletion_state is DeletionState.ACTIVE
        ]
        if project_id is not None:
            items = [r for r in items if r.project_id == project_id]
        if analysis_execution_id is not None:
            items = [
                r
                for r in items
                if r.provenance.analysis_execution_id == analysis_execution_id
            ]
        if states:
            items = [r for r in items if r.state in states]
        return _paged(sorted(items, key=lambda r: r.id, reverse=True), page)

    async def list_all(
        self, *, page: Page, states: tuple[ResultSetState, ...] = ()
    ) -> Paged[ResultSetRecord]:
        items = list(self.rows.values())
        if states:
            items = [r for r in items if r.state in states]
        return _paged(sorted(items, key=lambda r: r.id, reverse=True), page)


@dataclass
class MemoryResultArtifacts:
    rows: dict[str, ResultArtifactRecord] = field(default_factory=dict)

    async def add_many(
        self, artifacts: tuple[ResultArtifactRecord, ...]
    ) -> tuple[ResultArtifactRecord, ...]:
        for item in artifacts:
            pair = (item.result_set_id, item.artifact_key)
            if any(
                (a.result_set_id, a.artifact_key) == pair for a in self.rows.values()
            ):
                continue
            self.rows[item.id] = item
        return artifacts

    async def get(self, artifact_id: str) -> ResultArtifactRecord | None:
        return self.rows.get(artifact_id)

    async def save(self, artifact: ResultArtifactRecord) -> ResultArtifactRecord:
        updated = _bump(artifact, self.rows[artifact.id].version)
        self.rows[artifact.id] = updated
        return updated

    async def list_for_result_set(
        self, result_set_id: str
    ) -> tuple[ResultArtifactRecord, ...]:
        items = [a for a in self.rows.values() if a.result_set_id == result_set_id]
        return tuple(sorted(items, key=lambda a: a.artifact_key))


@dataclass
class MemoryResultIngestions:
    rows: dict[str, ResultIngestionRequest] = field(default_factory=dict)

    async def add(self, request: ResultIngestionRequest) -> ResultIngestionRequest:
        self.rows[request.id] = request
        return request

    async def get(self, request_id: str) -> ResultIngestionRequest | None:
        return self.rows.get(request_id)

    async def save(self, request: ResultIngestionRequest) -> ResultIngestionRequest:
        updated = _bump(request, self.rows[request.id].version)
        self.rows[request.id] = updated
        return updated

    async def get_by_idempotency_key(self, key: str) -> ResultIngestionRequest | None:
        for row in self.rows.values():
            if row.idempotency_key == key:
                return row
        return None

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[ResultIngestionState, ...] = (),
    ) -> Paged[ResultIngestionRequest]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        items = [r for r in self.rows.values() if r.workspace_id in workspace_ids]
        if project_id is not None:
            items = [r for r in items if r.project_id == project_id]
        if states:
            items = [r for r in items if r.state in states]
        return _paged(sorted(items, key=lambda r: r.id, reverse=True), page)


__all__ = [
    "MemoryDatasetVersionVariants",
    "MemoryGenesTranscripts",
    "MemoryResultArtifacts",
    "MemoryResultIngestions",
    "MemoryResultSets",
    "MemorySamples",
    "MemoryVariantContexts",
    "MemoryVariantIdentifiers",
    "MemoryVariantRepresentations",
    "MemoryVariantSourceRepresentations",
    "MemoryVariants",
]
