"""SCIENTIFIC RESULT CONTRACT (application side only).

The versioned shape in which the scientific subsystem hands variant and result
data to the application. Like ``app.scientific.contracts``, this module contains
no scientific algorithm: no normalization, no consequence prediction, no
frequency computation, no evidence evaluation, no classification. It defines the
*vocabulary of claims* the engine may make, and every claim carries the identity
of whoever made it.

Two payload shapes, because they answer different questions:

``VariantIngestionPayload``
    "Here are variants, and here is what I know about them." Used when an engine
    has canonicalized a dataset version's records and produced the contexts,
    observations, annotations and evidence that hang off them.
``ResultPayload``
    "Here is the output surface of my run." Used to register the Parquet/object
    artifacts of an execution, their column contracts and their checksums. The
    rows themselves stay in the analytical layer.

Contract rules that the application enforces structurally and never works around:

* Every derived claim names its producer (engine and/or resource) and version.
  An unattributed claim is rejected; it is not stored with a guessed origin.
* Positions, alleles and normalization state arrive *decided*. The application
  has no code path that computes any of them.
* A missing value is expressed as semantics, never as ``0``, ``""`` or ``false``.
* The payload declares its own completeness. The application never infers
  completeness from how many rows it happened to receive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Bumped whenever the shapes below change incompatibly. Persisted alongside
#: ingested data so an old payload stays interpretable in the way it was meant.
RESULT_CONTRACT_VERSION = "1"


# --------------------------------------------------------------------------- #
# Attribution                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ClaimAttribution:
    """Who produced a claim, and out of which versioned resource.

    At least one of ``engine_resource_id`` / ``source_resource_id`` must be
    present, with its version. That is the whole point of the type: it makes an
    anonymous scientific claim unrepresentable.
    """

    origin: str
    engine_resource_id: str | None = None
    engine_version: str | None = None
    source_resource_id: str | None = None
    source_version: str | None = None
    scientific_execution_id: str | None = None
    retrieved_at: datetime | None = None

    @property
    def names_a_producer(self) -> bool:
        return bool(
            (self.engine_resource_id and self.engine_version)
            or (self.source_resource_id and self.source_version)
        )


# --------------------------------------------------------------------------- #
# Variant claims                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SourceRepresentationClaim:
    """A source record exactly as the engine read it."""

    source_record_key: str
    contig: str
    position: int
    reference_allele: str | None = None
    alternate_allele: str | None = None
    source_identifier: str | None = None
    source_genome_resource_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalRepresentationClaim:
    """The canonical form the engine produced, or its explicit absence.

    ``normalization_state`` is authoritative. When it is not ``normalized``, the
    coordinate fields may be absent and the application stores the failure rather
    than falling back to the source coordinates and calling them canonical.
    """

    reference_genome_resource_id: str
    contig: str
    normalization_state: str
    normalization_version: str
    variant_class: str
    position: int | None = None
    end_position: int | None = None
    reference_allele: str | None = None
    alternate_allele: str | None = None
    symbolic_allele: str | None = None
    structural_variant_type: str | None = None
    normalization_engine_resource_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExternalIdentifierClaim:
    namespace: str
    external_identifier: str
    source_resource_id: str | None = None
    is_primary: bool = False


@dataclass(frozen=True, slots=True)
class TranscriptContextClaim:
    """A consequence in a transcript context, as reported by an annotator."""

    consequence_term: str
    attribution: ClaimAttribution
    transcript_namespace: str | None = None
    transcript_identifier: str | None = None
    transcript_version: str | None = None
    transcript_is_canonical: bool | None = None
    gene_namespace: str | None = None
    gene_identifier: str | None = None
    gene_symbol: str | None = None
    impact: str | None = None
    hgvs_genomic: str | None = None
    hgvs_coding: str | None = None
    hgvs_protein: str | None = None
    exon: str | None = None
    intron: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObservationClaim:
    """A per-sample observation. Zygosity arrives reported, never derived."""

    sample_key: str
    zygosity: str
    genotype: str | None = None
    genotype_semantics: str = "present"
    allele_balance: float | None = None
    read_depth: int | None = None
    alternate_allele_depth: int | None = None
    genotype_quality: int | None = None
    variant_quality: float | None = None
    filter_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnnotationClaim:
    """One annotation field/value, typed, with explicit value semantics."""

    field_key: str
    value_type: str
    attribution: ClaimAttribution
    value_semantics: str = "present"
    value_string: str | None = None
    value_number: float | None = None
    value_integer: int | None = None
    value_boolean: bool | None = None
    value_json: dict[str, Any] | None = None
    transcript_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class FrequencyClaim:
    """A population-frequency observation as published by a population resource."""

    population_key: str
    attribution: ClaimAttribution
    allele_frequency: float | None = None
    allele_count: int | None = None
    allele_number: int | None = None
    homozygote_count: int | None = None
    hemizygote_count: int | None = None
    value_semantics: str = "present"
    subset_key: str | None = None
    filter_flags: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClinicalAssertionClaim:
    """An external clinical assertion, in the submitter's own vocabulary."""

    attribution: ClaimAttribution
    external_accession: str | None = None
    clinical_significance: str | None = None
    review_status: str | None = None
    condition_term: str | None = None
    condition_namespace: str | None = None
    condition_identifier: str | None = None
    assertion_method: str | None = None
    submitter: str | None = None
    asserted_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    value_semantics: str = "present"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VariantClaim:
    """Everything one engine asserted about one source record."""

    canonical: CanonicalRepresentationClaim
    source: SourceRepresentationClaim | None = None
    external_identifiers: tuple[ExternalIdentifierClaim, ...] = ()
    transcript_contexts: tuple[TranscriptContextClaim, ...] = ()
    observations: tuple[ObservationClaim, ...] = ()
    annotations: tuple[AnnotationClaim, ...] = ()
    frequencies: tuple[FrequencyClaim, ...] = ()
    clinical_assertions: tuple[ClinicalAssertionClaim, ...] = ()


@dataclass(frozen=True, slots=True)
class VariantIngestionPayload:
    """A batch of variant claims tied to one execution and one dataset version."""

    contract_version: str
    analysis_execution_id: str
    dataset_version_id: str
    attribution: ClaimAttribution
    variants: tuple[VariantClaim, ...] = ()
    #: The engine's own statement about this batch. Not derived from ``variants``.
    completeness: str = "unknown"
    declared_variant_count: int | None = None
    is_development_payload: bool = False


# --------------------------------------------------------------------------- #
# Result surface                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ResultArtifactClaim:
    """A produced artifact the platform should register and verify."""

    artifact_key: str
    kind: str
    artifact_format: str
    storage_uri: str | None = None
    analytical_location: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    row_count: int | None = None
    column_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResultPayload:
    """The output surface of one scientific execution."""

    contract_version: str
    analysis_execution_id: str
    result_key: str
    attribution: ClaimAttribution
    completeness: str = "unknown"
    artifacts: tuple[ResultArtifactClaim, ...] = ()
    analytical_location: str | None = None
    row_count: int | None = None
    column_schema: dict[str, Any] = field(default_factory=dict)
    parameters_digest: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    reference_genome_resource_id: str | None = None
    resource_identities: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set by development/mock adapters. Surfaced everywhere the data is shown,
    #: so a stub result can never be mistaken for a scientific one.
    is_development_payload: bool = False


__all__ = [
    "RESULT_CONTRACT_VERSION",
    "AnnotationClaim",
    "CanonicalRepresentationClaim",
    "ClaimAttribution",
    "ClinicalAssertionClaim",
    "ExternalIdentifierClaim",
    "FrequencyClaim",
    "ObservationClaim",
    "ResultArtifactClaim",
    "ResultPayload",
    "SourceRepresentationClaim",
    "TranscriptContextClaim",
    "VariantClaim",
    "VariantIngestionPayload",
]
