"""Recording and reading the variant layer.

What this module does is deliberately mechanical: it takes claims that arrived
across the scientific contract and writes them down, with their attribution
intact. What it must never do is decide anything scientific. Concretely, and each
of these is a rule someone will eventually be tempted to break:

* A canonical variant is created **only** when the engine says the record was
  normalized. A claim that failed normalization produces a source representation
  and a failed representation row — never a canonical variant assembled from the
  source coordinates and quietly labelled canonical.
* ``variant_class`` and ``zygosity`` are copied from the claim. Neither is ever
  inferred from allele strings or genotype text.
* Absent values stay absent. ``value_semantics`` carries "missing"; no default,
  no zero, no empty string standing in for a number nobody reported.
* Conflicting claims are all stored. Two engine versions that disagree produce two
  rows, and the reader sees both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.results.dependencies import (
    ResultServices,
    require_variant_access,
)
from app.domain.errors import NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AnnotationValueType,
    AuditOutcome,
    DataOrigin,
    NormalizationState,
    ValueSemantics,
    VariantClass,
    Zygosity,
)
from app.domain.variant.entities import (
    AnnotationValue,
    ClinicalAssertionRecord,
    DatasetVersionVariant,
    GeneReference,
    PopulationFrequencyRecord,
    PopulationRecord,
    SampleObservation,
    TranscriptContext,
    TranscriptReference,
    VariantAnnotationRecord,
    VariantExternalIdentifier,
    VariantRecord,
    VariantRepresentation,
    VariantSourceRepresentation,
)
from app.domain.variant.identity import CanonicalVariantIdentity, ContigLabel
from app.domain.variant.ingestion import validate_variant_payload
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.results import (
    RESULT_CONTRACT_VERSION,
    ClaimAttribution,
    VariantClaim,
    VariantIngestionPayload,
)


@dataclass(frozen=True, slots=True)
class VariantIngestionSummary:
    """What was written, stated plainly enough to be reconciled against.

    ``unresolved`` is reported separately from ``recorded`` because a run where
    30% of records failed normalization is a materially different outcome from a
    clean one, and a single "imported N variants" number would hide it.
    """

    dataset_version_id: str
    claims_received: int
    variants_created: int
    variants_matched: int
    source_representations: int
    unresolved: int
    observations: int
    annotations: int
    frequencies: int
    clinical_assertions: int
    warnings: tuple[dict[str, Any], ...] = ()

    @property
    def recorded(self) -> int:
        return self.variants_created + self.variants_matched


@dataclass(frozen=True, slots=True)
class IngestVariantPayloadCommand:
    payload: VariantIngestionPayload
    request: RequestContext


def _origin(attribution: ClaimAttribution, fallback: DataOrigin) -> DataOrigin:
    try:
        return DataOrigin(attribution.origin)
    except ValueError:
        # An unrecognised origin is not silently coerced to "generated": that
        # would misattribute a retrieved value as a produced one.
        raise ValidationError(
            "the claim declares an unknown origin",
            details={"field": "origin", "value": attribution.origin},
        ) from None


def _identity(claim: VariantClaim) -> CanonicalVariantIdentity:
    canonical = claim.canonical
    return CanonicalVariantIdentity(
        reference_genome_resource_id=canonical.reference_genome_resource_id,
        contig=ContigLabel(
            canonical=canonical.contig,
            source=claim.source.contig if claim.source else None,
        ),
        position=canonical.position or 0,
        reference_allele=canonical.reference_allele or "",
        alternate_allele=canonical.alternate_allele or "",
        variant_class=VariantClass(canonical.variant_class),
        normalization_state=NormalizationState(canonical.normalization_state),
        normalization_version=canonical.normalization_version,
        end_position=canonical.end_position,
        symbolic_allele=canonical.symbolic_allele,
        structural_variant_type=canonical.structural_variant_type,
    )


class IngestVariantPayload:
    """Writes one batch of variant claims into the scientific data layer."""

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(
        self, command: IngestVariantPayloadCommand
    ) -> VariantIngestionSummary:
        now = self._services.clock.now()
        payload = command.payload
        if payload.contract_version != RESULT_CONTRACT_VERSION:
            raise ValidationError(
                "unsupported variant contract version",
                details={
                    "field": "contract_version",
                    "accepted": [RESULT_CONTRACT_VERSION],
                },
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            version = await repositories.dataset_versions.get(payload.dataset_version_id)
            if version is None:
                raise NotFoundError("dataset_version", payload.dataset_version_id)
            # The owning workspace is read from the stored dataset row, never
            # taken from the caller or the payload: tenancy is a fact of the data,
            # not an assertion of whoever delivered it.
            dataset = await repositories.datasets.get(version.dataset_id)
            if dataset is None:
                raise NotFoundError("dataset", version.dataset_id)
            workspace_id = dataset.workspace_id

            samples = await repositories.samples.list_for_workspace(
                workspace_id, page=Page(number=1, size=1000)
            )
            known_sample_keys = frozenset(item.sample_key for item in samples.items)
            outcome = validate_variant_payload(
                payload, known_sample_keys=known_sample_keys or None
            )
            if not outcome.accepted:
                raise ValidationError(
                    "the variant payload failed structural validation",
                    details={"findings": list(outcome.as_dicts())},
                )

            counters = dict.fromkeys(
                (
                    "created",
                    "matched",
                    "sources",
                    "unresolved",
                    "observations",
                    "annotations",
                    "frequencies",
                    "assertions",
                ),
                0,
            )
            sample_ids = {item.sample_key: item.id for item in samples.items}

            for index, claim in enumerate(payload.variants):
                await self._ingest_claim(
                    repositories,
                    claim,
                    payload=payload,
                    workspace_id=workspace_id,
                    sample_ids=sample_ids,
                    counters=counters,
                    location=f"variants[{index}]",
                    now=now,
                )

            summary = VariantIngestionSummary(
                dataset_version_id=payload.dataset_version_id,
                claims_received=len(payload.variants),
                variants_created=counters["created"],
                variants_matched=counters["matched"],
                source_representations=counters["sources"],
                unresolved=counters["unresolved"],
                observations=counters["observations"],
                annotations=counters["annotations"],
                frequencies=counters["frequencies"],
                clinical_assertions=counters["assertions"],
                warnings=outcome.as_dicts(),
            )
            await recorder.audit(
                action="dataset_version.variants_recorded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                resource_type="dataset_version",
                resource_id=payload.dataset_version_id,
                workspace_id=workspace_id,
                detail={
                    "claims_received": summary.claims_received,
                    "variants_created": summary.variants_created,
                    "variants_matched": summary.variants_matched,
                    "unresolved": summary.unresolved,
                    "is_development_payload": payload.is_development_payload,
                },
            )
            await recorder.event(
                event_type=EventType.VARIANT_OBSERVATIONS_RECORDED,
                aggregate_type="dataset_version",
                aggregate_id=payload.dataset_version_id,
                occurred_at=now,
                workspace_id=workspace_id,
                payload={
                    "observations": summary.observations,
                    "variants": summary.recorded,
                },
            )
        return summary

    async def _ingest_claim(
        self,
        repositories: Any,
        claim: VariantClaim,
        *,
        payload: VariantIngestionPayload,
        workspace_id: str,
        sample_ids: dict[str, str],
        counters: dict[str, int],
        location: str,
        now: Any,
    ) -> None:
        canonical = claim.canonical
        state = NormalizationState(canonical.normalization_state)
        normalized = state is NormalizationState.NORMALIZED
        batch_origin = _origin(payload.attribution, DataOrigin.GENERATED)

        source_row: VariantSourceRepresentation | None = None
        if claim.source is not None:
            source_row = VariantSourceRepresentation(
                id=new_id("vsr"),
                dataset_version_id=payload.dataset_version_id,
                source_record_key=claim.source.source_record_key,
                source_contig=claim.source.contig,
                source_position=claim.source.position,
                normalization_state=state,
                source_genome_resource_id=claim.source.source_genome_resource_id,
                source_reference_allele=claim.source.reference_allele,
                source_alternate_allele=claim.source.alternate_allele,
                source_identifier=claim.source.source_identifier,
                source_payload=dict(claim.source.payload),
                normalization_failure_reason=canonical.failure_message,
            )
            await repositories.variant_source_representations.add_many((source_row,))
            # The insert is idempotent on (dataset version, source key), so the
            # stored row may be an earlier one; that row is the one to link.
            stored_source = (
                await repositories.variant_source_representations.find_by_source_key(
                    dataset_version_id=payload.dataset_version_id,
                    source_record_key=claim.source.source_record_key,
                )
            )
            source_row = stored_source or source_row
            counters["sources"] += 1

        variant_id: str | None = None
        if normalized:
            candidate = VariantRecord(
                id=new_id("var"),
                identity=_identity(claim),
                origin=batch_origin,
                scientific_execution_id=payload.attribution.scientific_execution_id,
                normalization_engine_resource_id=(
                    canonical.normalization_engine_resource_id
                    or payload.attribution.engine_resource_id
                ),
            )
            variant, created = await repositories.variants.get_or_add(candidate)
            variant_id = variant.id
            counters["created" if created else "matched"] += 1
            await repositories.dataset_version_variants.add_many(
                (
                    DatasetVersionVariant(
                        id=new_id("dvv"),
                        dataset_version_id=payload.dataset_version_id,
                        variant_id=variant.id,
                        workspace_id=workspace_id,
                        source_representation_id=source_row.id if source_row else None,
                    ),
                )
            )
            if source_row is not None and source_row.is_unresolved:
                await repositories.variant_source_representations.link_variant(
                    representation_id=source_row.id, variant_id=variant.id
                )
        else:
            counters["unresolved"] += 1

        # The representation attempt is recorded either way — success, failure, or
        # a capability that was never available.
        await repositories.variant_representations.add_many(
            (
                VariantRepresentation(
                    id=new_id("vrp"),
                    variant_id=variant_id,
                    source_representation_id=source_row.id if source_row else None,
                    reference_genome_resource_id=canonical.reference_genome_resource_id,
                    contig=ContigLabel(
                        canonical=canonical.contig,
                        source=claim.source.contig if claim.source else None,
                    ),
                    position=canonical.position,
                    reference_allele=canonical.reference_allele,
                    alternate_allele=canonical.alternate_allele,
                    normalization_state=state,
                    normalization_version=canonical.normalization_version,
                    origin=batch_origin,
                    end_position=canonical.end_position,
                    normalization_engine_resource_id=(
                        canonical.normalization_engine_resource_id
                    ),
                    scientific_execution_id=payload.attribution.scientific_execution_id,
                    failure_code=canonical.failure_code,
                    failure_message=canonical.failure_message,
                    details=dict(canonical.details),
                    recorded_at=now,
                ),
            )
        )

        if variant_id is None:
            # Everything below hangs off a canonical variant. Without one, the
            # source row and the failed attempt are the whole truth, and that is
            # what gets stored.
            return

        if claim.external_identifiers:
            await repositories.variant_identifiers.add_many(
                tuple(
                    VariantExternalIdentifier(
                        id=new_id("vid"),
                        variant_id=variant_id,
                        namespace=item.namespace,
                        external_identifier=item.external_identifier,
                        origin=batch_origin,
                        source_resource_id=item.source_resource_id,
                        is_primary=item.is_primary,
                    )
                    for item in claim.external_identifiers
                )
            )

        for context in claim.transcript_contexts:
            gene_id = None
            transcript_id = None
            if context.gene_namespace and context.gene_identifier:
                gene, _ = await repositories.genes_transcripts.get_or_add_gene(
                    GeneReference(
                        id=new_id("gen"),
                        namespace=context.gene_namespace,
                        gene_identifier=context.gene_identifier,
                        symbol=context.gene_symbol,
                        source_resource_id=context.attribution.source_resource_id,
                    )
                )
                gene_id = gene.id
            if context.transcript_namespace and context.transcript_identifier:
                transcript, _ = await repositories.genes_transcripts.get_or_add_transcript(
                    TranscriptReference(
                        id=new_id("trx"),
                        namespace=context.transcript_namespace,
                        transcript_identifier=context.transcript_identifier,
                        transcript_version=context.transcript_version,
                        gene_id=gene_id,
                        is_canonical=context.transcript_is_canonical,
                        source_resource_id=context.attribution.source_resource_id,
                    )
                )
                transcript_id = transcript.id
            await repositories.variant_contexts.add_transcript_contexts(
                (
                    TranscriptContext(
                        id=new_id("vtc"),
                        variant_id=variant_id,
                        consequence_term=context.consequence_term,
                        origin=_origin(context.attribution, batch_origin),
                        transcript_id=transcript_id,
                        gene_id=gene_id,
                        impact=context.impact,
                        hgvs_genomic=context.hgvs_genomic,
                        hgvs_coding=context.hgvs_coding,
                        hgvs_protein=context.hgvs_protein,
                        exon=context.exon,
                        intron=context.intron,
                        source_resource_id=context.attribution.source_resource_id,
                        engine_resource_id=context.attribution.engine_resource_id,
                        scientific_execution_id=(
                            context.attribution.scientific_execution_id
                        ),
                        details=dict(context.details),
                    ),
                )
            )

        observations = tuple(
            SampleObservation(
                id=new_id("obs"),
                sample_id=sample_ids[item.sample_key],
                variant_id=variant_id,
                dataset_version_id=payload.dataset_version_id,
                zygosity=Zygosity(item.zygosity),
                genotype_semantics=ValueSemantics(item.genotype_semantics),
                variant_source_representation_id=source_row.id if source_row else None,
                genotype=item.genotype,
                allele_balance=item.allele_balance,
                read_depth=item.read_depth,
                alternate_allele_depth=item.alternate_allele_depth,
                genotype_quality=item.genotype_quality,
                variant_quality=item.variant_quality,
                filter_status=item.filter_status,
                observation_metadata=dict(item.metadata),
                source_provenance={"source_record_key": claim.source.source_record_key}
                if claim.source
                else {},
            )
            for item in claim.observations
            if item.sample_key in sample_ids
        )
        if observations:
            await repositories.variant_contexts.add_observations(observations)
            counters["observations"] += len(observations)

        annotations: list[VariantAnnotationRecord] = []
        for item in claim.annotations:
            resource_id = (
                item.attribution.source_resource_id or item.attribution.engine_resource_id
            )
            resource_version = (
                item.attribution.source_version or item.attribution.engine_version
            )
            if resource_id is None or resource_version is None:
                # Unreachable for a validated payload; refusing here keeps the
                # invariant local rather than trusting a caller.
                raise ValidationError(
                    "an annotation must name its resource and version",
                    details={"field": "attribution", "location": location},
                )
            annotations.append(
                VariantAnnotationRecord(
                    id=new_id("van"),
                    variant_id=variant_id,
                    annotation_resource_id=resource_id,
                    resource_version=resource_version,
                    field_key=item.field_key,
                    value=AnnotationValue(
                        value_type=AnnotationValueType(item.value_type),
                        semantics=ValueSemantics(item.value_semantics),
                        value_string=item.value_string,
                        value_number=item.value_number,
                        value_integer=item.value_integer,
                        value_boolean=item.value_boolean,
                        value_json=item.value_json,
                    ),
                    origin=_origin(item.attribution, batch_origin),
                    engine_resource_id=item.attribution.engine_resource_id,
                    engine_version=item.attribution.engine_version,
                    scientific_execution_id=item.attribution.scientific_execution_id,
                    retrieved_at=item.attribution.retrieved_at,
                    provenance={"origin": item.attribution.origin},
                )
            )
        if annotations:
            await repositories.variant_contexts.add_annotations(tuple(annotations))
            counters["annotations"] += len(annotations)

        frequencies: list[PopulationFrequencyRecord] = []
        for item in claim.frequencies:
            resource_id = item.attribution.source_resource_id
            resource_version = item.attribution.source_version
            if resource_id is None or resource_version is None:
                raise ValidationError(
                    "a frequency observation must name its resource and version",
                    details={"field": "attribution", "location": location},
                )
            population, _ = await repositories.variant_contexts.get_or_add_population(
                PopulationRecord(
                    id=new_id("pop"),
                    population_resource_id=resource_id,
                    population_key=item.population_key,
                )
            )
            frequencies.append(
                PopulationFrequencyRecord(
                    id=new_id("pfq"),
                    variant_id=variant_id,
                    population_id=population.id,
                    population_resource_id=resource_id,
                    resource_version=resource_version,
                    origin=_origin(item.attribution, DataOrigin.RETRIEVED),
                    allele_frequency=item.allele_frequency,
                    allele_count=item.allele_count,
                    allele_number=item.allele_number,
                    homozygote_count=item.homozygote_count,
                    hemizygote_count=item.hemizygote_count,
                    value_semantics=ValueSemantics(item.value_semantics),
                    subset_key=item.subset_key,
                    denominator_context=dict(item.filter_flags),
                    scientific_execution_id=item.attribution.scientific_execution_id,
                    retrieved_at=item.attribution.retrieved_at,
                )
            )
        if frequencies:
            await repositories.variant_contexts.add_frequencies(tuple(frequencies))
            counters["frequencies"] += len(frequencies)

        assertions: list[ClinicalAssertionRecord] = []
        for item in claim.clinical_assertions:
            source_id = item.attribution.source_resource_id
            if source_id is None or item.external_accession is None:
                raise ValidationError(
                    "a clinical assertion must name its source and accession",
                    details={"field": "attribution", "location": location},
                )
            assertions.append(
                ClinicalAssertionRecord(
                    id=new_id("cas"),
                    variant_id=variant_id,
                    source_id=source_id,
                    external_record_identifier=item.external_accession,
                    reported_classification=item.clinical_significance,
                    review_status_text=item.review_status,
                    condition_term=item.condition_term,
                    condition_namespace=item.condition_namespace,
                    condition_identifier=item.condition_identifier,
                    assertion_method=item.assertion_method,
                    submitter=item.submitter,
                    asserted_at=item.asserted_at,
                    last_evaluated_at=item.last_evaluated_at,
                    assertion_payload=dict(item.details),
                    origin=_origin(item.attribution, DataOrigin.RETRIEVED),
                    value_semantics=ValueSemantics(item.value_semantics),
                    scientific_execution_id=item.attribution.scientific_execution_id,
                    retrieved_at=item.attribution.retrieved_at,
                )
            )
        if assertions:
            await repositories.variant_contexts.add_clinical_assertions(tuple(assertions))
            counters["assertions"] += len(assertions)


# --------------------------------------------------------------------------- #
# Reads                                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ListDatasetVersionVariantsQuery:
    actor: Any
    dataset_version_id: str
    request: RequestContext
    page: Page
    contig: str | None = None
    position_from: int | None = None
    position_to: int | None = None
    query: str | None = None


class ListDatasetVersionVariants:
    """Lists the canonical variants a dataset version contains.

    Authorized through the dataset version, because that is the tenant-scoped
    thing. The filters here are coordinate and key filters only — scientific
    filtering is a separate, versioned, saveable concern.
    """

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, query: ListDatasetVersionVariantsQuery) -> Paged:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await require_variant_access(
                self._services,
                repositories,
                query.actor,
                dataset_version_id=query.dataset_version_id,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.variants.list_for_dataset_version(
                query.dataset_version_id,
                page=query.page,
                contig=query.contig,
                position_from=query.position_from,
                position_to=query.position_to,
                query=query.query,
            )


@dataclass(frozen=True, slots=True)
class VariantDetailView:
    """A variant plus the contexts recorded for it, each with its provenance."""

    variant: VariantRecord
    representations: tuple[VariantRepresentation, ...]
    source_representations: tuple[VariantSourceRepresentation, ...]
    identifiers: tuple[VariantExternalIdentifier, ...]
    transcript_contexts: Paged
    observations: Paged
    annotations: Paged
    frequencies: Paged
    clinical_assertions: Paged


@dataclass(frozen=True, slots=True)
class GetVariantQuery:
    actor: Any
    variant_id: str
    #: The dataset version through which the caller reached this variant. Required:
    #: a canonical variant has no owner of its own, so there is no other way to
    #: authorize the read.
    dataset_version_id: str
    request: RequestContext


class GetVariant:
    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, query: GetVariantQuery) -> VariantDetailView:
        now = self._services.clock.now()
        page = Page(number=1, size=100)
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await require_variant_access(
                self._services,
                repositories,
                query.actor,
                dataset_version_id=query.dataset_version_id,
                recorder=recorder,
                occurred_at=now,
            )
            variant = await repositories.variants.get(query.variant_id)
            if variant is None:
                raise NotFoundError("variant", query.variant_id)
            versions = await repositories.dataset_version_variants.list_dataset_versions(
                variant.id
            )
            if query.dataset_version_id not in versions:
                # The caller may read that dataset version, but this variant is
                # not in it. Reporting "not found" is correct and non-leaking.
                raise NotFoundError("variant", query.variant_id)
            contexts = repositories.variant_contexts
            return VariantDetailView(
                variant=variant,
                representations=await repositories.variant_representations.list_for_variant(
                    variant.id
                ),
                source_representations=(
                    await repositories.variant_source_representations.list_for_variant(
                        variant.id, dataset_version_id=query.dataset_version_id
                    )
                ),
                identifiers=await repositories.variant_identifiers.list_for_variant(
                    variant.id
                ),
                transcript_contexts=await contexts.list_transcript_contexts(
                    variant.id, page=page
                ),
                observations=await contexts.list_observations(
                    variant.id, page=page, dataset_version_id=query.dataset_version_id
                ),
                annotations=await contexts.list_annotations(variant.id, page=page),
                frequencies=await contexts.list_frequencies(variant.id, page=page),
                clinical_assertions=await contexts.list_clinical_assertions(
                    variant.id, page=page
                ),
            )


__all__ = [
    "GetVariant",
    "GetVariantQuery",
    "IngestVariantPayload",
    "IngestVariantPayloadCommand",
    "ListDatasetVersionVariants",
    "ListDatasetVersionVariantsQuery",
    "VariantDetailView",
    "VariantIngestionSummary",
]
