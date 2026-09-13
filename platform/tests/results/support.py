"""Shared arrangement for the Package 6 tests.

The payload builders here stand in for the independently deployed scientific
subsystem. They perform no scientific work: every value is a *fixture-declared
claim*, exactly as an engine would have declared it, and every payload is marked
``is_development_payload=True`` so nothing produced here can be mistaken for a
scientific result.
"""

from __future__ import annotations

from app.application.repositories import Page
from app.application.use_cases.results.ingestion import (
    MaterializeResultSet,
    MaterializeResultSetCommand,
    SubmitResultPayload,
    SubmitResultPayloadCommand,
)
from app.application.use_cases.results.variants import (
    IngestVariantPayload,
    IngestVariantPayloadCommand,
)
from app.scientific.results import (
    RESULT_CONTRACT_VERSION,
    AnnotationClaim,
    CanonicalRepresentationClaim,
    ClaimAttribution,
    FrequencyClaim,
    ObservationClaim,
    ResultArtifactClaim,
    ResultPayload,
    SourceRepresentationClaim,
    TranscriptContextClaim,
    VariantClaim,
    VariantIngestionPayload,
)
from tests.analysis.support import queued_execution
from tests.support.actors import actor_for
from tests.support.data_storage import checksum_of

PAGE = Page(number=1, size=25)

#: DEVELOPMENT ONLY identifiers. They name a fixture, not a scientific resource.
ENGINE = "res_dev_engine"
ENGINE_VERSION = "0.0.0-development-only"
GENOME = "res_dev_reference"
TABLE = b"variant_id,score\nv1,1\n"


def attribution(**overrides) -> ClaimAttribution:
    values = {
        "origin": "generated",
        "engine_resource_id": ENGINE,
        "engine_version": ENGINE_VERSION,
        "scientific_execution_id": "sci-exec-1",
    }
    values.update(overrides)
    return ClaimAttribution(**values)


def normalized_claim(
    *,
    contig: str = "chr1",
    position: int = 1000,
    reference_allele: str = "A",
    alternate_allele: str = "T",
    source_record_key: str = "rec-1",
    observations: tuple[ObservationClaim, ...] = (),
    annotations: tuple[AnnotationClaim, ...] = (),
    frequencies: tuple[FrequencyClaim, ...] = (),
    transcript_contexts: tuple[TranscriptContextClaim, ...] = (),
) -> VariantClaim:
    return VariantClaim(
        canonical=CanonicalRepresentationClaim(
            reference_genome_resource_id=GENOME,
            contig=contig,
            normalization_state="normalized",
            normalization_version="0.0.0-development-only",
            variant_class="snv",
            position=position,
            reference_allele=reference_allele,
            alternate_allele=alternate_allele,
            normalization_engine_resource_id=ENGINE,
        ),
        source=SourceRepresentationClaim(
            source_record_key=source_record_key,
            contig=contig,
            position=position,
            reference_allele=reference_allele,
            alternate_allele=alternate_allele,
        ),
        observations=observations,
        annotations=annotations,
        frequencies=frequencies,
        transcript_contexts=transcript_contexts,
    )


def unresolved_claim(*, source_record_key: str = "rec-bad") -> VariantClaim:
    """A record the engine could not canonicalize. The failure is the claim."""
    return VariantClaim(
        canonical=CanonicalRepresentationClaim(
            reference_genome_resource_id=GENOME,
            contig="chrUn_KI270742v1",
            normalization_state="normalization_failed",
            normalization_version="0.0.0-development-only",
            variant_class="unknown",
            failure_code="reference_mismatch",
            failure_message="the reference allele does not match the genome",
        ),
        source=SourceRepresentationClaim(
            source_record_key=source_record_key,
            contig="chrUn_KI270742v1",
            position=55,
            reference_allele="G",
            alternate_allele="C",
        ),
    )


def variant_payload(
    *,
    analysis_execution_id: str,
    dataset_version_id: str,
    variants: tuple[VariantClaim, ...],
    completeness: str = "complete",
) -> VariantIngestionPayload:
    return VariantIngestionPayload(
        contract_version=RESULT_CONTRACT_VERSION,
        analysis_execution_id=analysis_execution_id,
        dataset_version_id=dataset_version_id,
        attribution=attribution(),
        variants=variants,
        completeness=completeness,
        declared_variant_count=len(variants),
        is_development_payload=True,
    )


def result_payload(
    *,
    analysis_execution_id: str,
    result_key: str = "primary",
    analytical_location: str = "s3://test-bucket/results/primary.parquet",
    artifacts: tuple[ResultArtifactClaim, ...] | None = None,
    row_count: int | None = 1,
    completeness: str = "complete",
) -> ResultPayload:
    if artifacts is None:
        artifacts = (
            ResultArtifactClaim(
                artifact_key="variants.csv",
                kind="variant_table",
                artifact_format="csv",
                storage_uri="results/primary/variants.csv",
                media_type="text/csv",
                size_bytes=len(TABLE),
                checksum_algorithm="sha256",
                checksum_value=checksum_of(TABLE),
                row_count=1,
            ),
        )
    return ResultPayload(
        contract_version=RESULT_CONTRACT_VERSION,
        analysis_execution_id=analysis_execution_id,
        result_key=result_key,
        attribution=attribution(),
        completeness=completeness,
        artifacts=artifacts,
        analytical_location=analytical_location,
        row_count=row_count,
        column_schema={"variant_id": "VARCHAR", "score": "BIGINT"},
        is_development_payload=True,
    )


async def execution_for(harness, user_id: str, *, name: str = "Trio Screen"):
    """A queued execution plus the dataset version its configuration declared."""
    analysis, configuration, execution = await queued_execution(
        harness, user_id, name=name
    )
    dataset_version_id = configuration.inputs[0].dataset_version_id
    return analysis, execution.execution, dataset_version_id


async def submitted_result(
    harness,
    user_id: str,
    execution_id: str,
    *,
    payload: ResultPayload | None = None,
    idempotency_key: str = "delivery-1",
    stored_table: bytes | None = TABLE,
    register_surface: bool = True,
):
    """Registers a result surface, having first placed its bytes in storage."""
    payload = payload or result_payload(analysis_execution_id=execution_id)
    for artifact in payload.artifacts:
        if artifact.storage_uri and stored_table is not None:
            harness.storage.put(artifact.storage_uri, stored_table)
    if register_surface and payload.analytical_location:
        harness.analytics.register(
            payload.analytical_location,
            columns=("variant_id", "score"),
            rows=(("v1", 1),),
        )
    return await SubmitResultPayload(harness.results).execute(
        SubmitResultPayloadCommand(
            payload=payload,
            request=harness.request,
            idempotency_key=idempotency_key,
            payload_digest=f"digest:{idempotency_key}",
            actor=await actor_for(harness, user_id),
        )
    )


async def available_result(harness, user_id: str, execution_id: str, **kwargs):
    """A surface that has passed verification: the only readable kind."""
    view = await submitted_result(harness, user_id, execution_id, **kwargs)
    return await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=view.ingestion.id, request=harness.request
        )
    )


async def ingest_variants(
    harness,
    user_id: str,
    *,
    analysis_execution_id: str,
    dataset_version_id: str,
    variants: tuple[VariantClaim, ...],
):
    return await IngestVariantPayload(harness.results).execute(
        IngestVariantPayloadCommand(
            payload=variant_payload(
                analysis_execution_id=analysis_execution_id,
                dataset_version_id=dataset_version_id,
                variants=variants,
            ),
            request=harness.request,
        )
    )


__all__ = [
    "ENGINE",
    "ENGINE_VERSION",
    "GENOME",
    "PAGE",
    "TABLE",
    "attribution",
    "available_result",
    "execution_for",
    "ingest_variants",
    "normalized_claim",
    "result_payload",
    "submitted_result",
    "unresolved_claim",
    "variant_payload",
]
