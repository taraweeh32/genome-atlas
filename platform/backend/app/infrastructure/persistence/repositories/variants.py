"""Persistence for canonical variants and their scientific contexts.

Two properties shape every statement here:

* **Canonical variants are shared, not tenant-owned.** ``get_by_canonical_key``
  and ``get_or_add`` therefore have no workspace filter — and every *listing*
  path takes a dataset version or a variant id whose tenant the caller has
  already resolved. No method on this module can be used to enumerate variants
  across tenants.
* **Nothing is updated.** These tables are append-only. The only mutation is
  attaching a canonical variant to a source representation that had none, which
  the domain entity permits exactly once.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.application.repositories import Page, Paged
from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    NormalizationState,
    ValueSemantics,
    VariantClass,
    Zygosity,
)
from app.domain.variant.entities import (
    AnnotationValue,
    PopulationRecord,
    ClinicalAssertionRecord,
    DatasetVersionVariant,
    GeneReference,
    PopulationFrequencyRecord,
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
from app.domain.variant.identity import CanonicalVariantIdentity, ContigLabel
from app.infrastructure.persistence.models.annotation import (
    ClinicalAssertion,
    Population,
    PopulationFrequencyObservation,
    VariantAnnotation,
)
from app.infrastructure.persistence.models.variant import (
    Gene,
    Sample,
    Transcript,
    Variant,
    VariantExternalIdentifier as IdentifierModel,
    VariantObservation,
    VariantSourceRepresentation as SourceModel,
    VariantTranscriptConsequence,
)
from app.infrastructure.persistence.models.variant_results import (
    DatasetVersionVariant as MembershipModel,
    VariantRepresentation as RepresentationModel,
)
from app.infrastructure.persistence.repositories.base import SqlRepository

_VARIANTS = Variant.__table__
_SOURCES = SourceModel.__table__
_REPRESENTATIONS = RepresentationModel.__table__
_MEMBERSHIPS = MembershipModel.__table__
_IDENTIFIERS = IdentifierModel.__table__
_CONSEQUENCES = VariantTranscriptConsequence.__table__
_OBSERVATIONS = VariantObservation.__table__
_ANNOTATIONS = VariantAnnotation.__table__
_FREQUENCIES = PopulationFrequencyObservation.__table__
_ASSERTIONS = ClinicalAssertion.__table__
_POPULATIONS = Population.__table__
_SAMPLES = Sample.__table__
_GENES = Gene.__table__
_TRANSCRIPTS = Transcript.__table__


# --------------------------------------------------------------------------- #
# Row → entity translation
# --------------------------------------------------------------------------- #


def to_variant(row: Mapping[str, Any]) -> VariantRecord:
    identity = CanonicalVariantIdentity(
        reference_genome_resource_id=row["reference_genome_resource_id"],
        contig=ContigLabel(canonical=row["contig"]),
        position=row["position"],
        reference_allele=row["reference_allele"],
        alternate_allele=row["alternate_allele"],
        variant_class=VariantClass(row["variant_class"]),
        normalization_state=NormalizationState(row["normalization_state"]),
        normalization_version=row["normalization_version"],
        end_position=row["end_position"],
        symbolic_allele=row["symbolic_allele"],
        structural_variant_type=row["structural_variant_type"],
    )
    return VariantRecord(
        id=row["id"],
        identity=identity,
        origin=DataOrigin(row["origin"]),
        scientific_execution_id=row["scientific_execution_id"],
        normalization_engine_resource_id=row["normalization_engine_resource_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_source_representation(row: Mapping[str, Any]) -> VariantSourceRepresentation:
    return VariantSourceRepresentation(
        id=row["id"],
        dataset_version_id=row["dataset_version_id"],
        source_record_key=row["source_record_key"],
        source_contig=row["source_contig"],
        source_position=row["source_position"],
        normalization_state=NormalizationState(row["normalization_state"]),
        variant_id=row["variant_id"],
        source_genome_resource_id=row["source_genome_resource_id"],
        source_reference_allele=row["source_reference_allele"],
        source_alternate_allele=row["source_alternate_allele"],
        source_identifier=row["source_identifier"],
        source_payload=row["source_payload"] or {},
        normalization_failure_reason=row["normalization_failure_reason"],
        transformation_metadata=row["transformation_metadata"] or {},
        build_conversion_metadata=row["build_conversion_metadata"] or {},
        created_at=row["created_at"],
    )


def to_representation(row: Mapping[str, Any]) -> VariantRepresentation:
    return VariantRepresentation(
        id=row["id"],
        variant_id=row["variant_id"],
        source_representation_id=row["source_representation_id"],
        reference_genome_resource_id=row["reference_genome_resource_id"],
        contig=ContigLabel(canonical=row["contig"], source=row["source_contig"]),
        position=row["position"],
        reference_allele=row["reference_allele"],
        alternate_allele=row["alternate_allele"],
        normalization_state=NormalizationState(row["normalization_state"]),
        normalization_version=row["normalization_version"],
        origin=DataOrigin(row["origin"]),
        end_position=row["end_position"],
        normalization_engine_resource_id=row["normalization_engine_resource_id"],
        scientific_execution_id=row["scientific_execution_id"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        details=row["details"] or {},
        recorded_at=row["recorded_at"],
    )


def to_identifier(row: Mapping[str, Any]) -> VariantExternalIdentifier:
    return VariantExternalIdentifier(
        id=row["id"],
        variant_id=row["variant_id"],
        namespace=row["namespace"],
        external_identifier=row["external_identifier"],
        origin=DataOrigin(row["origin"]),
        source_resource_id=row["source_resource_id"],
        is_primary=bool(row["is_primary"]),
        created_at=row["created_at"],
    )


def to_transcript_context(row: Mapping[str, Any]) -> TranscriptContext:
    return TranscriptContext(
        id=row["id"],
        variant_id=row["variant_id"],
        consequence_term=row["consequence_term"],
        origin=DataOrigin(row["origin"]),
        transcript_id=row["transcript_id"],
        gene_id=row["gene_id"],
        impact=row["impact"],
        hgvs_genomic=row["hgvs_genomic"],
        hgvs_coding=row["hgvs_coding"],
        hgvs_protein=row["hgvs_protein"],
        exon=row["exon"],
        intron=row["intron"],
        source_resource_id=row["source_resource_id"],
        engine_resource_id=row["engine_resource_id"],
        scientific_execution_id=row["scientific_execution_id"],
        details=row["details"] or {},
        created_at=row["created_at"],
    )


def to_observation(row: Mapping[str, Any]) -> SampleObservation:
    return SampleObservation(
        id=row["id"],
        sample_id=row["sample_id"],
        variant_id=row["variant_id"],
        dataset_version_id=row["dataset_version_id"],
        zygosity=Zygosity(row["zygosity"]),
        genotype_semantics=ValueSemantics(row["genotype_semantics"]),
        variant_source_representation_id=row["variant_source_representation_id"],
        genotype=row["genotype"],
        allele_balance=row["allele_balance"],
        read_depth=row["read_depth"],
        alternate_allele_depth=row["alternate_allele_depth"],
        genotype_quality=row["genotype_quality"],
        variant_quality=row["variant_quality"],
        filter_status=row["filter_status"],
        observation_metadata=row["observation_metadata"] or {},
        source_provenance=row["source_provenance"] or {},
        created_at=row["created_at"],
    )


def to_annotation(row: Mapping[str, Any]) -> VariantAnnotationRecord:
    value = AnnotationValue(
        value_type=AnnotationValueType(row["value_type"]),
        semantics=ValueSemantics(row["value_semantics"]),
        value_string=row["value_string"],
        value_number=row["value_number"],
        value_integer=row["value_integer"],
        value_boolean=row["value_boolean"],
        value_json=row["value_json"],
    )
    return VariantAnnotationRecord(
        id=row["id"],
        variant_id=row["variant_id"],
        annotation_resource_id=row["annotation_resource_id"],
        resource_version=row["resource_version"],
        field_key=row["field_key"],
        value=value,
        origin=DataOrigin(row["origin"]),
        transcript_id=row["transcript_id"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        scientific_execution_id=row["scientific_execution_id"],
        retrieved_at=row["retrieved_at"],
        provenance=row["provenance"] or {},
        created_at=row["created_at"],
    )


def to_frequency(row: Mapping[str, Any]) -> PopulationFrequencyRecord:
    return PopulationFrequencyRecord(
        id=row["id"],
        variant_id=row["variant_id"],
        population_id=row["population_id"],
        population_resource_id=row["population_resource_id"],
        resource_version=row["resource_version"],
        origin=DataOrigin(row["origin"]),
        allele_frequency=row["allele_frequency"],
        allele_count=row["allele_count"],
        allele_number=row["allele_number"],
        homozygote_count=row["homozygote_count"],
        hemizygote_count=row["hemizygote_count"],
        value_semantics=ValueSemantics(row["value_semantics"]),
        subset_key=row["subset_key"],
        genome_resource_id=row["genome_resource_id"],
        denominator_context=row["denominator_context"] or {},
        scientific_execution_id=row["scientific_execution_id"],
        retrieved_at=row["retrieved_at"],
        provenance=row["provenance"] or {},
    )


def to_clinical_assertion(row: Mapping[str, Any]) -> ClinicalAssertionRecord:
    return ClinicalAssertionRecord(
        id=row["id"],
        variant_id=row["variant_id"],
        source_id=row["source_id"],
        external_record_identifier=row["external_record_identifier"],
        reported_classification=row["reported_classification"],
        review_status_text=row["review_status_text"],
        assertion_statement=row["assertion_statement"],
        condition_term=row["condition_term"],
        condition_namespace=row["condition_namespace"],
        condition_identifier=row["condition_identifier"],
        assertion_method=row["assertion_method"],
        submitter=row["submitter"],
        asserted_at=row["asserted_at"],
        last_evaluated_at=row["last_evaluated_at"],
        conflict_information=row["conflict_information"] or {},
        assertion_payload=row["assertion_payload"] or {},
        record_count=row["record_count"],
        origin=DataOrigin(row["origin"]),
        value_semantics=ValueSemantics(row["value_semantics"]),
        scientific_execution_id=row["scientific_execution_id"],
        retrieved_at=row["retrieved_at"],
        provenance=row["provenance"] or {},
    )


def to_population(row: Mapping[str, Any]) -> PopulationRecord:
    return PopulationRecord(
        id=row["id"],
        population_resource_id=row["population_resource_id"],
        population_key=row["population_key"],
        display_name=row["display_name"],
        metadata=row["metadata_json"] or {},
    )


def to_sample(row: Mapping[str, Any]) -> SampleRecord:
    return SampleRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        dataset_id=row["dataset_id"],
        dataset_version_id=row["dataset_version_id"],
        sample_key=row["sample_key"],
        display_label=row["display_label"],
        sex_karyotype=row["sex_karyotype"],
        source_metadata=row["source_metadata"] or {},
        created_at=row["created_at"],
    )


def to_gene(row: Mapping[str, Any]) -> GeneReference:
    return GeneReference(
        id=row["id"],
        namespace=row["namespace"],
        gene_identifier=row["gene_identifier"],
        symbol=row["symbol"],
        source_resource_id=row["source_resource_id"],
        metadata=row["metadata_json"] or {},
    )


def to_transcript(row: Mapping[str, Any]) -> TranscriptReference:
    return TranscriptReference(
        id=row["id"],
        namespace=row["namespace"],
        transcript_identifier=row["transcript_identifier"],
        transcript_version=row["transcript_version"],
        gene_id=row["gene_id"],
        is_canonical=row["is_canonical"],
        source_resource_id=row["source_resource_id"],
        metadata=row["metadata_json"] or {},
    )


class _PagingRepository(SqlRepository):
    async def _page(
        self, statement: Select, *, page: Page, translate: Any
    ) -> Paged[Any]:
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.limit).offset(page.offset))
        return Paged(items=tuple(translate(row) for row in rows), total=total, page=page)


class SqlVariantRepository(_PagingRepository):
    async def get(self, variant_id: str) -> VariantRecord | None:
        row = await self._fetch_one(select(_VARIANTS).where(_VARIANTS.c.id == variant_id))
        return to_variant(row) if row else None

    async def get_by_canonical_key(self, canonical_key: str) -> VariantRecord | None:
        row = await self._fetch_one(
            select(_VARIANTS).where(_VARIANTS.c.canonical_key == canonical_key)
        )
        return to_variant(row) if row else None

    async def add(self, variant: VariantRecord) -> VariantRecord:
        await self._session.execute(insert(_VARIANTS).values(**_variant_values(variant)))
        return variant

    async def get_or_add(self, variant: VariantRecord) -> tuple[VariantRecord, bool]:
        """Converge on one row for one canonical key.

        Two ingestions of the same variant are not an error; they are the normal
        case. ``ON CONFLICT DO NOTHING`` plus a re-read keeps the winner and
        returns it, so no caller ever holds a variant id that does not exist.
        """
        result = await self._session.execute(
            pg_insert(_VARIANTS)
            .values(**_variant_values(variant))
            .on_conflict_do_nothing(index_elements=[_VARIANTS.c.canonical_key])
            .returning(_VARIANTS.c.id)
        )
        if result.scalar_one_or_none() is not None:
            return variant, True
        existing = await self.get_by_canonical_key(variant.canonical_key)
        assert existing is not None  # noqa: S101 - the conflicting row must exist
        return existing, False

    async def list_for_dataset_version(
        self,
        dataset_version_id: str,
        *,
        page: Page,
        contig: str | None = None,
        position_from: int | None = None,
        position_to: int | None = None,
        query: str | None = None,
    ) -> Paged[VariantRecord]:
        statement = (
            select(_VARIANTS)
            .join(_MEMBERSHIPS, _MEMBERSHIPS.c.variant_id == _VARIANTS.c.id)
            .where(_MEMBERSHIPS.c.dataset_version_id == dataset_version_id)
            .order_by(_VARIANTS.c.contig, _VARIANTS.c.position, _VARIANTS.c.id)
        )
        if contig is not None:
            statement = statement.where(_VARIANTS.c.contig == contig)
        if position_from is not None:
            statement = statement.where(_VARIANTS.c.position >= position_from)
        if position_to is not None:
            statement = statement.where(_VARIANTS.c.position <= position_to)
        if query:
            # Canonical-key prefix search. Never a scientific lookup: it matches
            # the stored key text, nothing is parsed or interpreted.
            statement = statement.where(_VARIANTS.c.canonical_key.ilike(f"%{query}%"))
        return await self._page(statement, page=page, translate=to_variant)

    async def count_for_dataset_version(self, dataset_version_id: str) -> int:
        return await self._count(
            select(_MEMBERSHIPS.c.id).where(
                _MEMBERSHIPS.c.dataset_version_id == dataset_version_id
            )
        )


def _variant_values(variant: VariantRecord) -> dict[str, Any]:
    identity = variant.identity
    return {
        "id": variant.id,
        "reference_genome_resource_id": identity.reference_genome_resource_id,
        "contig": identity.contig.canonical,
        "position": identity.position,
        "end_position": identity.end_position,
        "reference_allele": identity.reference_allele,
        "alternate_allele": identity.alternate_allele,
        "variant_class": identity.variant_class.value,
        "symbolic_allele": identity.symbolic_allele,
        "structural_variant_type": identity.structural_variant_type,
        "normalization_state": identity.normalization_state.value,
        "normalization_version": identity.normalization_version,
        "normalization_engine_resource_id": variant.normalization_engine_resource_id,
        "canonical_key": identity.key,
        "origin": variant.origin.value,
        "scientific_execution_id": variant.scientific_execution_id,
    }


class SqlVariantRepresentationRepository(SqlRepository):
    async def add_many(
        self, representations: tuple[VariantRepresentation, ...]
    ) -> tuple[VariantRepresentation, ...]:
        for item in representations:
            await self._session.execute(
                pg_insert(_REPRESENTATIONS)
                .values(
                    id=item.id,
                    variant_id=item.variant_id,
                    source_representation_id=item.source_representation_id,
                    reference_genome_resource_id=item.reference_genome_resource_id,
                    contig=item.contig.canonical,
                    source_contig=item.contig.source,
                    position=item.position,
                    end_position=item.end_position,
                    reference_allele=item.reference_allele,
                    alternate_allele=item.alternate_allele,
                    normalization_state=item.normalization_state.value,
                    normalization_version=item.normalization_version,
                    normalization_engine_resource_id=item.normalization_engine_resource_id,
                    scientific_execution_id=item.scientific_execution_id,
                    origin=item.origin.value,
                    failure_code=item.failure_code,
                    failure_message=item.failure_message,
                    details=item.details,
                    recorded_at=item.recorded_at,
                )
                # Re-running the same engine version over the same source row is
                # idempotent; a different version writes a new row instead.
                .on_conflict_do_nothing(
                    index_elements=[
                        _REPRESENTATIONS.c.source_representation_id,
                        _REPRESENTATIONS.c.normalization_version,
                    ]
                )
            )
        return representations

    async def list_for_variant(self, variant_id: str) -> tuple[VariantRepresentation, ...]:
        rows = await self._fetch_all(
            select(_REPRESENTATIONS)
            .where(_REPRESENTATIONS.c.variant_id == variant_id)
            .order_by(_REPRESENTATIONS.c.recorded_at, _REPRESENTATIONS.c.id)
        )
        return tuple(to_representation(row) for row in rows)

    async def list_for_source_representation(
        self, source_representation_id: str
    ) -> tuple[VariantRepresentation, ...]:
        rows = await self._fetch_all(
            select(_REPRESENTATIONS)
            .where(_REPRESENTATIONS.c.source_representation_id == source_representation_id)
            .order_by(_REPRESENTATIONS.c.recorded_at, _REPRESENTATIONS.c.id)
        )
        return tuple(to_representation(row) for row in rows)


class SqlVariantSourceRepresentationRepository(SqlRepository):
    async def add_many(
        self, representations: tuple[VariantSourceRepresentation, ...]
    ) -> tuple[VariantSourceRepresentation, ...]:
        for item in representations:
            await self._session.execute(
                pg_insert(_SOURCES)
                .values(
                    id=item.id,
                    variant_id=item.variant_id,
                    dataset_version_id=item.dataset_version_id,
                    source_record_key=item.source_record_key,
                    source_genome_resource_id=item.source_genome_resource_id,
                    source_contig=item.source_contig,
                    source_position=item.source_position,
                    source_reference_allele=item.source_reference_allele,
                    source_alternate_allele=item.source_alternate_allele,
                    source_identifier=item.source_identifier,
                    source_payload=item.source_payload,
                    normalization_state=item.normalization_state.value,
                    normalization_failure_reason=item.normalization_failure_reason,
                    transformation_metadata=item.transformation_metadata,
                    build_conversion_metadata=item.build_conversion_metadata,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _SOURCES.c.dataset_version_id,
                        _SOURCES.c.source_record_key,
                    ]
                )
            )
        return representations

    async def get(self, representation_id: str) -> VariantSourceRepresentation | None:
        row = await self._fetch_one(select(_SOURCES).where(_SOURCES.c.id == representation_id))
        return to_source_representation(row) if row else None

    async def link_variant(
        self, *, representation_id: str, variant_id: str
    ) -> VariantSourceRepresentation | None:
        """Attach a canonical variant to a previously unresolved source row.

        The ``variant_id IS NULL`` predicate is the guard: an already-linked row
        is never re-pointed, so history cannot be rewritten by a later import.
        """
        await self._session.execute(
            update(_SOURCES)
            .where(_SOURCES.c.id == representation_id, _SOURCES.c.variant_id.is_(None))
            .values(variant_id=variant_id)
        )
        return await self.get(representation_id)

    async def list_for_variant(
        self, variant_id: str, *, dataset_version_id: str | None = None
    ) -> tuple[VariantSourceRepresentation, ...]:
        statement = select(_SOURCES).where(_SOURCES.c.variant_id == variant_id)
        if dataset_version_id is not None:
            statement = statement.where(_SOURCES.c.dataset_version_id == dataset_version_id)
        rows = await self._fetch_all(statement.order_by(_SOURCES.c.created_at, _SOURCES.c.id))
        return tuple(to_source_representation(row) for row in rows)

    async def find_by_source_key(
        self, *, dataset_version_id: str, source_record_key: str
    ) -> VariantSourceRepresentation | None:
        row = await self._fetch_one(
            select(_SOURCES).where(
                _SOURCES.c.dataset_version_id == dataset_version_id,
                _SOURCES.c.source_record_key == source_record_key,
            )
        )
        return to_source_representation(row) if row else None


class SqlDatasetVersionVariantRepository(SqlRepository):
    async def add_many(
        self, memberships: tuple[DatasetVersionVariant, ...]
    ) -> tuple[DatasetVersionVariant, ...]:
        for item in memberships:
            await self._session.execute(
                pg_insert(_MEMBERSHIPS)
                .values(
                    id=item.id,
                    dataset_version_id=item.dataset_version_id,
                    variant_id=item.variant_id,
                    workspace_id=item.workspace_id,
                    source_representation_id=item.source_representation_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _MEMBERSHIPS.c.dataset_version_id,
                        _MEMBERSHIPS.c.variant_id,
                    ]
                )
            )
        return memberships

    async def workspace_ids_for_variant(self, variant_id: str) -> tuple[str, ...]:
        rows = await self._fetch_all(
            select(_MEMBERSHIPS.c.workspace_id)
            .where(_MEMBERSHIPS.c.variant_id == variant_id)
            .distinct()
        )
        return tuple(row["workspace_id"] for row in rows)

    async def list_dataset_versions(self, variant_id: str) -> tuple[str, ...]:
        rows = await self._fetch_all(
            select(_MEMBERSHIPS.c.dataset_version_id)
            .where(_MEMBERSHIPS.c.variant_id == variant_id)
            .distinct()
        )
        return tuple(row["dataset_version_id"] for row in rows)


class SqlVariantIdentifierRepository(SqlRepository):
    async def add_many(
        self, identifiers: tuple[VariantExternalIdentifier, ...]
    ) -> tuple[VariantExternalIdentifier, ...]:
        for item in identifiers:
            await self._session.execute(
                pg_insert(_IDENTIFIERS)
                .values(
                    id=item.id,
                    variant_id=item.variant_id,
                    namespace=item.namespace,
                    external_identifier=item.external_identifier,
                    source_resource_id=item.source_resource_id,
                    origin=item.origin.value,
                    is_primary=item.is_primary,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _IDENTIFIERS.c.variant_id,
                        _IDENTIFIERS.c.namespace,
                        _IDENTIFIERS.c.external_identifier,
                    ]
                )
            )
        return identifiers

    async def list_for_variant(
        self, variant_id: str
    ) -> tuple[VariantExternalIdentifier, ...]:
        rows = await self._fetch_all(
            select(_IDENTIFIERS)
            .where(_IDENTIFIERS.c.variant_id == variant_id)
            .order_by(_IDENTIFIERS.c.namespace, _IDENTIFIERS.c.external_identifier)
        )
        return tuple(to_identifier(row) for row in rows)


class SqlVariantContextRepository(_PagingRepository):
    """Transcript contexts, observations, annotations, frequencies, assertions."""

    async def get_or_add_population(
        self, population: PopulationRecord
    ) -> tuple[PopulationRecord, bool]:
        """Resolve a cohort by its resource + key, creating it once if unseen.

        A cohort is defined by the population resource, never by the platform, so
        this only ever records the identity the resource published.
        """
        result = await self._session.execute(
            pg_insert(_POPULATIONS)
            .values(
                id=population.id,
                population_resource_id=population.population_resource_id,
                population_key=population.population_key,
                display_name=population.display_name,
                metadata_json=population.metadata,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    _POPULATIONS.c.population_resource_id,
                    _POPULATIONS.c.population_key,
                ]
            )
            .returning(_POPULATIONS.c.id)
        )
        if result.scalar_one_or_none() is not None:
            return population, True
        row = await self._fetch_one(
            select(_POPULATIONS).where(
                _POPULATIONS.c.population_resource_id == population.population_resource_id,
                _POPULATIONS.c.population_key == population.population_key,
            )
        )
        assert row is not None  # noqa: S101 - the conflicting row must exist
        return to_population(row), False

    async def add_transcript_contexts(
        self, contexts: tuple[TranscriptContext, ...]
    ) -> tuple[TranscriptContext, ...]:
        for item in contexts:
            await self._session.execute(
                insert(_CONSEQUENCES).values(
                    id=item.id,
                    variant_id=item.variant_id,
                    transcript_id=item.transcript_id,
                    gene_id=item.gene_id,
                    consequence_term=item.consequence_term,
                    impact=item.impact,
                    hgvs_genomic=item.hgvs_genomic,
                    hgvs_coding=item.hgvs_coding,
                    hgvs_protein=item.hgvs_protein,
                    exon=item.exon,
                    intron=item.intron,
                    source_resource_id=item.source_resource_id,
                    engine_resource_id=item.engine_resource_id,
                    scientific_execution_id=item.scientific_execution_id,
                    origin=item.origin.value,
                    details=item.details,
                )
            )
        return contexts

    async def list_transcript_contexts(
        self, variant_id: str, *, page: Page
    ) -> Paged[TranscriptContext]:
        statement = (
            select(_CONSEQUENCES)
            .where(_CONSEQUENCES.c.variant_id == variant_id)
            .order_by(_CONSEQUENCES.c.transcript_id, _CONSEQUENCES.c.id)
        )
        return await self._page(statement, page=page, translate=to_transcript_context)

    async def add_observations(
        self, observations: tuple[SampleObservation, ...]
    ) -> tuple[SampleObservation, ...]:
        for item in observations:
            await self._session.execute(
                pg_insert(_OBSERVATIONS)
                .values(
                    id=item.id,
                    sample_id=item.sample_id,
                    variant_id=item.variant_id,
                    dataset_version_id=item.dataset_version_id,
                    variant_source_representation_id=item.variant_source_representation_id,
                    genotype=item.genotype,
                    genotype_semantics=item.genotype_semantics.value,
                    zygosity=item.zygosity.value,
                    allele_balance=item.allele_balance,
                    read_depth=item.read_depth,
                    alternate_allele_depth=item.alternate_allele_depth,
                    genotype_quality=item.genotype_quality,
                    variant_quality=item.variant_quality,
                    filter_status=item.filter_status,
                    observation_metadata=item.observation_metadata,
                    source_provenance=item.source_provenance,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _OBSERVATIONS.c.sample_id,
                        _OBSERVATIONS.c.variant_id,
                        _OBSERVATIONS.c.dataset_version_id,
                    ]
                )
            )
        return observations

    async def list_observations(
        self,
        variant_id: str,
        *,
        page: Page,
        dataset_version_id: str | None = None,
    ) -> Paged[SampleObservation]:
        statement = select(_OBSERVATIONS).where(_OBSERVATIONS.c.variant_id == variant_id)
        if dataset_version_id is not None:
            statement = statement.where(
                _OBSERVATIONS.c.dataset_version_id == dataset_version_id
            )
        statement = statement.order_by(_OBSERVATIONS.c.sample_id, _OBSERVATIONS.c.id)
        return await self._page(statement, page=page, translate=to_observation)

    async def add_annotations(
        self, annotations: tuple[VariantAnnotationRecord, ...]
    ) -> tuple[VariantAnnotationRecord, ...]:
        for item in annotations:
            value = item.value
            await self._session.execute(
                insert(_ANNOTATIONS).values(
                    id=item.id,
                    variant_id=item.variant_id,
                    transcript_id=item.transcript_id,
                    annotation_resource_id=item.annotation_resource_id,
                    resource_version=item.resource_version,
                    engine_resource_id=item.engine_resource_id,
                    engine_version=item.engine_version,
                    scientific_execution_id=item.scientific_execution_id,
                    field_key=item.field_key,
                    value_type=value.value_type.value,
                    value_string=value.value_string,
                    value_number=value.value_number,
                    value_integer=value.value_integer,
                    value_boolean=value.value_boolean,
                    value_json=value.value_json,
                    value_semantics=value.semantics.value,
                    origin=item.origin.value,
                    retrieved_at=item.retrieved_at,
                    provenance=item.provenance,
                )
            )
        return annotations

    async def list_annotations(
        self, variant_id: str, *, page: Page, source_key: str | None = None
    ) -> Paged[VariantAnnotationRecord]:
        statement = select(_ANNOTATIONS).where(_ANNOTATIONS.c.variant_id == variant_id)
        if source_key is not None:
            statement = statement.where(_ANNOTATIONS.c.annotation_resource_id == source_key)
        statement = statement.order_by(
            _ANNOTATIONS.c.field_key, _ANNOTATIONS.c.resource_version, _ANNOTATIONS.c.id
        )
        return await self._page(statement, page=page, translate=to_annotation)

    async def add_frequencies(
        self, frequencies: tuple[PopulationFrequencyRecord, ...]
    ) -> tuple[PopulationFrequencyRecord, ...]:
        for item in frequencies:
            await self._session.execute(
                pg_insert(_FREQUENCIES)
                .values(
                    id=item.id,
                    variant_id=item.variant_id,
                    population_id=item.population_id,
                    population_resource_id=item.population_resource_id,
                    resource_version=item.resource_version,
                    genome_resource_id=item.genome_resource_id,
                    allele_count=item.allele_count,
                    allele_number=item.allele_number,
                    homozygote_count=item.homozygote_count,
                    hemizygote_count=item.hemizygote_count,
                    allele_frequency=item.allele_frequency,
                    denominator_context=item.denominator_context,
                    value_semantics=item.value_semantics.value,
                    origin=item.origin.value,
                    retrieved_at=item.retrieved_at,
                    provenance=item.provenance,
                    subset_key=item.subset_key,
                    scientific_execution_id=item.scientific_execution_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _FREQUENCIES.c.variant_id,
                        _FREQUENCIES.c.population_id,
                        _FREQUENCIES.c.population_resource_id,
                        _FREQUENCIES.c.resource_version,
                    ]
                )
            )
        return frequencies

    async def list_frequencies(
        self, variant_id: str, *, page: Page
    ) -> Paged[PopulationFrequencyRecord]:
        statement = (
            select(_FREQUENCIES)
            .where(_FREQUENCIES.c.variant_id == variant_id)
            .order_by(
                _FREQUENCIES.c.population_resource_id,
                _FREQUENCIES.c.resource_version,
                _FREQUENCIES.c.population_id,
            )
        )
        return await self._page(statement, page=page, translate=to_frequency)

    async def add_clinical_assertions(
        self, assertions: tuple[ClinicalAssertionRecord, ...]
    ) -> tuple[ClinicalAssertionRecord, ...]:
        for item in assertions:
            await self._session.execute(
                pg_insert(_ASSERTIONS)
                .values(
                    id=item.id,
                    variant_id=item.variant_id,
                    source_id=item.source_id,
                    external_record_identifier=item.external_record_identifier,
                    reported_classification=item.reported_classification,
                    condition_term=item.condition_term,
                    condition_identifier=item.condition_identifier,
                    condition_namespace=item.condition_namespace,
                    assertion_statement=item.assertion_statement,
                    review_status_text=item.review_status_text,
                    submitter=item.submitter,
                    assertion_method=item.assertion_method,
                    asserted_at=item.asserted_at,
                    last_evaluated_at=item.last_evaluated_at,
                    conflict_information=item.conflict_information,
                    assertion_payload=item.assertion_payload,
                    record_count=item.record_count,
                    origin=item.origin.value,
                    value_semantics=item.value_semantics.value,
                    scientific_execution_id=item.scientific_execution_id,
                    retrieved_at=item.retrieved_at,
                    provenance=item.provenance,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        _ASSERTIONS.c.source_id,
                        _ASSERTIONS.c.external_record_identifier,
                        _ASSERTIONS.c.variant_id,
                    ]
                )
            )
        return assertions

    async def list_clinical_assertions(
        self, variant_id: str, *, page: Page
    ) -> Paged[ClinicalAssertionRecord]:
        statement = (
            select(_ASSERTIONS)
            .where(_ASSERTIONS.c.variant_id == variant_id)
            .order_by(_ASSERTIONS.c.source_id, _ASSERTIONS.c.external_record_identifier)
        )
        return await self._page(statement, page=page, translate=to_clinical_assertion)


class SqlSampleRepository(_PagingRepository):
    async def get(self, sample_id: str) -> SampleRecord | None:
        row = await self._fetch_one(select(_SAMPLES).where(_SAMPLES.c.id == sample_id))
        return to_sample(row) if row else None

    async def get_or_add(self, sample: SampleRecord) -> tuple[SampleRecord, bool]:
        result = await self._session.execute(
            pg_insert(_SAMPLES)
            .values(
                id=sample.id,
                workspace_id=sample.workspace_id,
                dataset_id=sample.dataset_id,
                dataset_version_id=sample.dataset_version_id,
                sample_key=sample.sample_key,
                display_label=sample.display_label,
                sex_karyotype=sample.sex_karyotype,
                source_metadata=sample.source_metadata,
            )
            .on_conflict_do_nothing(
                index_elements=[_SAMPLES.c.dataset_version_id, _SAMPLES.c.sample_key]
            )
            .returning(_SAMPLES.c.id)
        )
        if result.scalar_one_or_none() is not None:
            return sample, True
        row = await self._fetch_one(
            select(_SAMPLES).where(
                _SAMPLES.c.dataset_version_id == sample.dataset_version_id,
                _SAMPLES.c.sample_key == sample.sample_key,
            )
        )
        assert row is not None  # noqa: S101 - the conflicting row must exist
        return to_sample(row), False

    async def find_by_key(
        self, *, workspace_id: str, sample_key: str
    ) -> SampleRecord | None:
        row = await self._fetch_one(
            select(_SAMPLES).where(
                _SAMPLES.c.workspace_id == workspace_id,
                _SAMPLES.c.sample_key == sample_key,
            )
        )
        return to_sample(row) if row else None

    async def list_for_workspace(
        self, workspace_id: str, *, page: Page
    ) -> Paged[SampleRecord]:
        statement = (
            select(_SAMPLES)
            .where(_SAMPLES.c.workspace_id == workspace_id)
            .order_by(_SAMPLES.c.sample_key)
        )
        return await self._page(statement, page=page, translate=to_sample)


class SqlGeneTranscriptRepository(SqlRepository):
    async def get_or_add_gene(self, gene: GeneReference) -> tuple[GeneReference, bool]:
        result = await self._session.execute(
            pg_insert(_GENES)
            .values(
                id=gene.id,
                namespace=gene.namespace,
                gene_identifier=gene.gene_identifier,
                symbol=gene.symbol,
                source_resource_id=gene.source_resource_id,
                metadata_json=gene.metadata,
            )
            .on_conflict_do_nothing(
                index_elements=[_GENES.c.namespace, _GENES.c.gene_identifier]
            )
            .returning(_GENES.c.id)
        )
        if result.scalar_one_or_none() is not None:
            return gene, True
        existing = await self.find_gene(
            source_key=gene.namespace, gene_identifier=gene.gene_identifier
        )
        assert existing is not None  # noqa: S101
        return existing, False

    async def get_or_add_transcript(
        self, transcript: TranscriptReference
    ) -> tuple[TranscriptReference, bool]:
        result = await self._session.execute(
            pg_insert(_TRANSCRIPTS)
            .values(
                id=transcript.id,
                namespace=transcript.namespace,
                transcript_identifier=transcript.transcript_identifier,
                transcript_version=transcript.transcript_version,
                gene_id=transcript.gene_id,
                is_canonical=transcript.is_canonical,
                source_resource_id=transcript.source_resource_id,
                metadata_json=transcript.metadata,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    _TRANSCRIPTS.c.namespace,
                    _TRANSCRIPTS.c.transcript_identifier,
                    _TRANSCRIPTS.c.transcript_version,
                ]
            )
            .returning(_TRANSCRIPTS.c.id)
        )
        if result.scalar_one_or_none() is not None:
            return transcript, True
        existing = await self.find_transcript(
            source_key=transcript.namespace,
            transcript_identifier=transcript.transcript_identifier,
        )
        assert existing is not None  # noqa: S101
        return existing, False

    async def find_gene(
        self, *, source_key: str, gene_identifier: str
    ) -> GeneReference | None:
        row = await self._fetch_one(
            select(_GENES).where(
                _GENES.c.namespace == source_key,
                _GENES.c.gene_identifier == gene_identifier,
            )
        )
        return to_gene(row) if row else None

    async def find_transcript(
        self, *, source_key: str, transcript_identifier: str
    ) -> TranscriptReference | None:
        row = await self._fetch_one(
            select(_TRANSCRIPTS)
            .where(
                _TRANSCRIPTS.c.namespace == source_key,
                _TRANSCRIPTS.c.transcript_identifier == transcript_identifier,
            )
            .order_by(_TRANSCRIPTS.c.transcript_version.desc().nullslast())
        )
        return to_transcript(row) if row else None


__all__ = [
    "SqlDatasetVersionVariantRepository",
    "SqlGeneTranscriptRepository",
    "SqlSampleRepository",
    "SqlVariantContextRepository",
    "SqlVariantIdentifierRepository",
    "SqlVariantRepository",
    "SqlVariantRepresentationRepository",
    "SqlVariantSourceRepresentationRepository",
    "to_annotation",
    "to_clinical_assertion",
    "to_frequency",
    "to_gene",
    "to_identifier",
    "to_observation",
    "to_population",
    "to_representation",
    "to_sample",
    "to_source_representation",
    "to_transcript",
    "to_transcript_context",
    "to_variant",
]
