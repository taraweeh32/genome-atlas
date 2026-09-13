"""Variant record behaviour: identity, unresolved records, and value semantics.

The platform records what an engine declared and nothing more. The properties
under test are therefore about *faithfulness*, not about science:

* canonical identity is the engine's canonical claim, shared across tenants,
  while the tenant-scoped path to it is what authorizes a read;
* a record the engine could not canonicalize is preserved as an unresolved
  record, not dropped and not silently "fixed";
* absent, zero, false and unknown values stay distinguishable;
* re-delivering the same claims does not duplicate anything.
"""

from __future__ import annotations

import pytest

from app.application.repositories import Page
from app.application.use_cases.results.variants import (
    GetVariant,
    GetVariantQuery,
    ListDatasetVersionVariants,
    ListDatasetVersionVariantsQuery,
)
from app.domain.errors import AuthorizationError, NotFoundError
from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    NormalizationState,
    ValueSemantics,
    VariantClass,
    Zygosity,
)
from app.scientific.results import (
    AnnotationClaim,
    FrequencyClaim,
    ObservationClaim,
    TranscriptContextClaim,
)
from tests.results.support import (
    ENGINE,
    GENOME,
    PAGE,
    attribution,
    declare_sample,
    execution_for,
    ingest_variants,
    normalized_claim,
    unresolved_claim,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness

pytestmark = pytest.mark.anyio


@pytest.fixture
def harness():
    return build_harness()


async def _owner(harness) -> str:
    return await create_account(harness, "owner@example.test", "Owner")


async def test_a_normalized_claim_is_recorded_with_its_source_representation(harness):
    owner = await _owner(harness)
    _, execution, dataset_version_id = await execution_for(harness, owner)

    summary = await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )

    assert summary.claims_received == 1
    assert summary.variants_created == 1
    assert summary.variants_matched == 0
    assert summary.unresolved == 0
    # The source row is kept alongside the canonical one: the platform never
    # overwrites how the record arrived.
    assert summary.source_representations == 1

    page = await ListDatasetVersionVariants(harness.results).execute(
        ListDatasetVersionVariantsQuery(
            actor=await actor_for(harness, owner),
            dataset_version_id=dataset_version_id,
            request=harness.request,
            page=PAGE,
        )
    )
    assert page.total == 1
    variant = page.items[0]
    identity = variant.identity
    assert identity.reference_genome_resource_id == GENOME
    assert identity.contig.canonical == "chr1"
    assert identity.position == 1000
    assert identity.reference_allele == "A"
    assert identity.alternate_allele == "T"
    assert variant.variant_class is VariantClass.SNV
    assert variant.normalization_state is NormalizationState.NORMALIZED

    detail = await GetVariant(harness.results).execute(
        GetVariantQuery(
            actor=await actor_for(harness, owner),
            variant_id=variant.id,
            dataset_version_id=dataset_version_id,
            request=harness.request,
        )
    )
    assert len(detail.source_representations) == 1
    assert detail.source_representations[0].source_record_key == "rec-1"
    assert detail.source_representations[0].dataset_version_id == dataset_version_id


async def test_redelivering_the_same_claims_matches_instead_of_duplicating(harness):
    owner = await _owner(harness)
    _, execution, dataset_version_id = await execution_for(harness, owner)
    claims = (normalized_claim(),)

    first = await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=claims,
    )
    second = await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=claims,
    )

    assert first.variants_created == 1
    assert second.variants_created == 0
    assert second.variants_matched == 1
    page = await ListDatasetVersionVariants(harness.results).execute(
        ListDatasetVersionVariantsQuery(
            actor=await actor_for(harness, owner),
            dataset_version_id=dataset_version_id,
            request=harness.request,
            page=PAGE,
        )
    )
    assert page.total == 1


async def test_a_record_the_engine_could_not_canonicalize_is_preserved_as_unresolved(
    harness,
):
    owner = await _owner(harness)
    _, execution, dataset_version_id = await execution_for(harness, owner)

    summary = await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(), unresolved_claim()),
    )

    # Reported separately: a partly unresolved run must not read as a clean one.
    assert summary.claims_received == 2
    assert summary.recorded == 1
    assert summary.unresolved == 1
    assert summary.source_representations == 2

    # The unresolved record exists as a source row, with the failure it carried,
    # and is not attached to a canonical variant it never had.
    rows = [
        row
        for row in harness.repositories.variant_source_representations.rows.values()
        if row.source_record_key == "rec-bad"
    ]
    assert len(rows) == 1
    assert rows[0].variant_id is None
    assert rows[0].normalization_state is NormalizationState.NORMALIZATION_FAILED
    assert rows[0].normalization_failure_reason is not None


async def test_absent_zero_false_and_unknown_values_stay_distinguishable(harness):
    owner = await _owner(harness)
    _, execution, dataset_version_id = await execution_for(harness, owner)
    await declare_sample(harness, dataset_version_id, "S1")

    claim = normalized_claim(
        observations=(
            ObservationClaim(
                sample_key="S1",
                # Nothing was reported about zygosity. It is not inferred from the
                # genotype string.
                zygosity=Zygosity.UNKNOWN.value,
                genotype_semantics=ValueSemantics.UNKNOWN.value,
                read_depth=0,
            ),
        ),
        annotations=(
            AnnotationClaim(
                field_key="absent_field",
                value_type=AnnotationValueType.NUMBER.value,
                value_semantics=ValueSemantics.MISSING.value,
                attribution=attribution(),
            ),
            AnnotationClaim(
                field_key="false_field",
                value_type=AnnotationValueType.BOOLEAN.value,
                value_boolean=False,
                attribution=attribution(),
            ),
            AnnotationClaim(
                field_key="zero_field",
                value_type=AnnotationValueType.NUMBER.value,
                value_number=0.0,
                attribution=attribution(),
            ),
        ),
        frequencies=(
            FrequencyClaim(
                population_key="dev_population",
                # Not observed in this population: that is not a frequency of 0.
                value_semantics=ValueSemantics.NA.value,
                attribution=attribution(origin=DataOrigin.IMPORTED.value),
            ),
        ),
    )

    summary = await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(claim,),
    )
    assert (summary.observations, summary.annotations, summary.frequencies) == (1, 3, 1)

    page = await ListDatasetVersionVariants(harness.results).execute(
        ListDatasetVersionVariantsQuery(
            actor=await actor_for(harness, owner),
            dataset_version_id=dataset_version_id,
            request=harness.request,
            page=PAGE,
        )
    )
    detail = await GetVariant(harness.results).execute(
        GetVariantQuery(
            actor=await actor_for(harness, owner),
            variant_id=page.items[0].id,
            dataset_version_id=dataset_version_id,
            request=harness.request,
        )
    )

    observation = detail.observations.items[0]
    assert observation.zygosity is Zygosity.UNKNOWN
    assert observation.genotype_semantics is ValueSemantics.UNKNOWN
    assert observation.genotype is None
    # A reported depth of zero is a measurement, not a missing value.
    assert observation.read_depth == 0

    annotations = {item.field_key: item for item in detail.annotations.items}
    assert annotations["absent_field"].value_semantics is ValueSemantics.MISSING
    assert annotations["absent_field"].value_number is None
    assert annotations["false_field"].value_boolean is False
    assert annotations["false_field"].value_semantics is ValueSemantics.PRESENT
    assert annotations["zero_field"].value_number == 0.0
    assert annotations["zero_field"].value_semantics is ValueSemantics.PRESENT

    frequency = detail.frequencies.items[0]
    assert frequency.value_semantics is ValueSemantics.NA
    assert frequency.allele_frequency is None
    assert frequency.allele_count is None
    assert frequency.origin is DataOrigin.IMPORTED


async def test_every_recorded_context_carries_the_attribution_that_produced_it(harness):
    owner = await _owner(harness)
    _, execution, dataset_version_id = await execution_for(harness, owner)

    claim = normalized_claim(
        transcript_contexts=(
            TranscriptContextClaim(
                consequence_term="dev_consequence_term",
                transcript_namespace="dev_namespace",
                transcript_identifier="DEVT.1",
                gene_symbol="DEVGENE",
                hgvs_coding="c.1A>T",
                attribution=attribution(),
            ),
        ),
    )
    await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(claim,),
    )

    page = await ListDatasetVersionVariants(harness.results).execute(
        ListDatasetVersionVariantsQuery(
            actor=await actor_for(harness, owner),
            dataset_version_id=dataset_version_id,
            request=harness.request,
            page=PAGE,
        )
    )
    detail = await GetVariant(harness.results).execute(
        GetVariantQuery(
            actor=await actor_for(harness, owner),
            variant_id=page.items[0].id,
            dataset_version_id=dataset_version_id,
            request=harness.request,
        )
    )

    context = detail.transcript_contexts.items[0]
    # The claim is traceable to the engine and execution that produced it, so a
    # later engine version can never be mistaken for the source of this row.
    assert context.engine_resource_id == ENGINE
    assert context.scientific_execution_id == "sci-exec-1"
    assert context.consequence_term == "dev_consequence_term"
    assert detail.variant.normalization_engine_resource_id == ENGINE
    assert detail.representations[0].reference_genome_resource_id == GENOME


async def test_knowing_a_variant_id_grants_nothing_without_a_readable_path(harness):
    owner = await _owner(harness)
    outsider = await create_account(harness, "outsider@example.test", "Outsider")
    _, execution, dataset_version_id = await execution_for(harness, owner)
    await ingest_variants(
        harness,
        owner,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )
    page = await ListDatasetVersionVariants(harness.results).execute(
        ListDatasetVersionVariantsQuery(
            actor=await actor_for(harness, owner),
            dataset_version_id=dataset_version_id,
            request=harness.request,
            page=PAGE,
        )
    )
    variant_id = page.items[0].id

    # Canonical variants are shared; the tenant-scoped dataset version is the
    # only path to one, and this caller has none.
    with pytest.raises((AuthorizationError, NotFoundError)):
        await GetVariant(harness.results).execute(
            GetVariantQuery(
                actor=await actor_for(harness, outsider),
                variant_id=variant_id,
                dataset_version_id=dataset_version_id,
                request=harness.request,
            )
        )
    with pytest.raises((AuthorizationError, NotFoundError)):
        await ListDatasetVersionVariants(harness.results).execute(
            ListDatasetVersionVariantsQuery(
                actor=await actor_for(harness, outsider),
                dataset_version_id=dataset_version_id,
                request=harness.request,
                page=Page(number=1, size=10),
            )
        )
