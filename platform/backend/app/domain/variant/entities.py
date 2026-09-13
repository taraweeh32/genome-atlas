"""Immutable records of the variant data layer.

Every record here is *append-only in spirit*: a record states that some source or
some engine asserted something at some time, and that statement is never edited
afterwards. When a newer engine version disagrees, a new record is written next
to the old one and both remain readable — reconciling them is a scientific
judgement, and the application does not make it.

Three separations are load-bearing and must not collapse:

1. **Identity vs representation.** ``VariantRecord`` holds identity;
   ``VariantSourceRepresentation`` holds what a file actually said;
   ``VariantRepresentation`` holds one engine's normalization attempt, including
   the attempts that failed or were never possible.
2. **Record vs observation.** A variant existing is not a variant being seen in a
   sample. ``SampleObservation`` carries genotype and quality; the variant record
   carries neither.
3. **Fact vs attribution.** Nothing carries a value without carrying where the
   value came from: ``origin``, the resource identity and, where relevant, the
   scientific execution that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    NormalizationState,
    ValueSemantics,
    VariantClass,
    Zygosity,
)
from app.domain.variant.identity import CanonicalVariantIdentity, ContigLabel


@dataclass(frozen=True, slots=True)
class VariantRecord:
    """A canonical variant. Identity only — no annotation, no genotype, no score.

    There is no ``save``-style mutator on this entity, and that is intentional:
    once written, a canonical variant is a fixed point that observations,
    annotations, evidence and results all reference. Correcting a variant means
    writing a different canonical variant, not editing this one.
    """

    id: str
    identity: CanonicalVariantIdentity
    #: Where the canonical form came from: an import, a knowledge resource, or a
    #: scientific execution. Never defaulted to "generated" for imported rows.
    origin: DataOrigin
    #: The engine execution that produced this canonical form, when one did.
    scientific_execution_id: str | None = None
    normalization_engine_resource_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def canonical_key(self) -> str:
        return self.identity.key

    @property
    def variant_class(self) -> VariantClass:
        return self.identity.variant_class

    @property
    def normalization_state(self) -> NormalizationState:
        return self.identity.normalization_state


@dataclass(frozen=True, slots=True)
class VariantSourceRepresentation:
    """A variant exactly as one dataset version spelled it.

    Preserved verbatim, forever, including the records that could not be
    canonicalized: ``variant_id`` is nullable precisely so that a source row whose
    normalization failed is still queryable instead of being dropped on import.
    Losing those rows silently would make an import look cleaner than it was.
    """

    id: str
    dataset_version_id: str
    source_record_key: str
    source_contig: str
    source_position: int
    normalization_state: NormalizationState
    variant_id: str | None = None
    source_genome_resource_id: str | None = None
    source_reference_allele: str | None = None
    source_alternate_allele: str | None = None
    #: e.g. the VCF ID column. An identifier, never identity.
    source_identifier: str | None = None
    #: Verbatim source fields. Retained for reproducibility, not for querying.
    source_payload: dict[str, Any] = field(default_factory=dict)
    normalization_failure_reason: str | None = None
    transformation_metadata: dict[str, Any] = field(default_factory=dict)
    #: Present only when the *source* declared a build conversion. The platform
    #: performs no liftover of its own, so it never writes this itself.
    build_conversion_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def linked_to(self, *, variant_id: str) -> VariantSourceRepresentation:
        """Attach the canonical variant this source row resolved to.

        Allowed exactly once, and only from an unlinked row: re-pointing a source
        representation at a different canonical variant would rewrite history.
        """
        if self.variant_id is not None and self.variant_id != variant_id:
            raise ValidationError(
                "a source representation is never re-pointed at another variant",
                field="variant_id",
            )
        return replace(self, variant_id=variant_id)

    @property
    def is_unresolved(self) -> bool:
        return self.variant_id is None


@dataclass(frozen=True, slots=True)
class VariantRepresentation:
    """One normalization/representation attempt, successful or not.

    This is the representation *history*. A failed or unavailable attempt is a
    first-class row: ``NORMALIZATION_FAILED`` means the engine tried and could
    not, ``NORMALIZATION_UNAVAILABLE`` means the capability was not there to try.
    Collapsing either into ``NOT_NORMALIZED`` would present an operational gap as
    a scientific statement about the variant.
    """

    id: str
    #: The canonical variant this attempt produced, when it produced one.
    variant_id: str | None
    source_representation_id: str | None
    reference_genome_resource_id: str
    contig: ContigLabel
    position: int | None
    reference_allele: str | None
    alternate_allele: str | None
    normalization_state: NormalizationState
    normalization_version: str
    origin: DataOrigin
    end_position: int | None = None
    normalization_engine_resource_id: str | None = None
    scientific_execution_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        succeeded = self.normalization_state is NormalizationState.NORMALIZED
        if succeeded and self.variant_id is None:
            raise ValidationError(
                "a successful normalization must reference the canonical variant",
                field="variant_id",
            )
        if succeeded and (self.position is None or self.reference_allele is None):
            raise ValidationError(
                "a successful normalization must carry normalized coordinates",
                field="position",
            )
        if self.normalization_state is NormalizationState.NORMALIZATION_FAILED and not (
            self.failure_code or self.failure_message
        ):
            raise ValidationError(
                "a normalization failure must say why it failed", field="failure_code"
            )

    @property
    def succeeded(self) -> bool:
        return self.normalization_state is NormalizationState.NORMALIZED


@dataclass(frozen=True, slots=True)
class VariantExternalIdentifier:
    """An external reference to a variant. Explicitly *not* identity."""

    id: str
    variant_id: str
    #: ``dbsnp`` | ``clinvar`` | ``hgvs_g`` | ``cosmic`` | internal namespaces.
    namespace: str
    external_identifier: str
    origin: DataOrigin
    source_resource_id: str | None = None
    #: A hint for display only. Several identifiers in one namespace may exist
    #: for one variant, and none of them is authoritative.
    is_primary: bool = False
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GeneReference:
    """A gene as named by an annotation resource."""

    id: str
    namespace: str
    gene_identifier: str
    symbol: str | None = None
    source_resource_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TranscriptReference:
    """A transcript as named by an annotation resource.

    ``is_canonical`` is tri-state on purpose: ``None`` means the resource did not
    say. The application never picks a canonical transcript, and a UI that needs
    one must ask the user or the ruleset, not this field.
    """

    id: str
    namespace: str
    transcript_identifier: str
    transcript_version: str | None = None
    gene_id: str | None = None
    is_canonical: bool | None = None
    source_resource_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TranscriptContext:
    """One variant's consequence in one transcript context, as reported.

    A variant routinely has many of these, from many resources and engine
    versions, and they may disagree. All of them are stored. There is no
    "the consequence" field anywhere in this layer.
    """

    id: str
    variant_id: str
    consequence_term: str
    origin: DataOrigin
    transcript_id: str | None = None
    gene_id: str | None = None
    impact: str | None = None
    hgvs_genomic: str | None = None
    hgvs_coding: str | None = None
    hgvs_protein: str | None = None
    exon: str | None = None
    intron: str | None = None
    source_resource_id: str | None = None
    engine_resource_id: str | None = None
    scientific_execution_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """A sample declared by a dataset version manifest.

    Tenant-scoped, because a sample is subject data: the workspace and dataset
    are part of the row so that every read of an observation can be authorized
    without joining back through the variant, which is *not* tenant-scoped.
    """

    id: str
    workspace_id: str
    dataset_id: str
    dataset_version_id: str
    sample_key: str
    display_label: str | None = None
    #: As declared by the manifest. Never derived from genotypes on sex contigs.
    sex_karyotype: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SampleObservation:
    """One sample's observation of one canonical variant.

    Zygosity is stored as reported and is ``UNKNOWN`` when nothing was reported —
    never derived from the genotype string, because mapping ``0/1`` to
    heterozygous depends on ploidy, phasing and contig conventions that the
    scientific layer owns. ``genotype_semantics`` keeps an absent genotype, an
    explicit ``./.`` and a real call distinguishable.
    """

    id: str
    sample_id: str
    variant_id: str
    dataset_version_id: str
    zygosity: Zygosity
    genotype_semantics: ValueSemantics
    variant_source_representation_id: str | None = None
    genotype: str | None = None
    allele_balance: float | None = None
    read_depth: int | None = None
    alternate_allele_depth: int | None = None
    genotype_quality: int | None = None
    variant_quality: float | None = None
    #: The source's own filter column (``PASS``, ``LowQual``, …), verbatim.
    filter_status: str | None = None
    observation_metadata: dict[str, Any] = field(default_factory=dict)
    source_provenance: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.genotype is None and self.genotype_semantics is ValueSemantics.PRESENT:
            raise ValidationError(
                "an absent genotype cannot be recorded as present",
                field="genotype_semantics",
            )


@dataclass(frozen=True, slots=True)
class AnnotationValue:
    """A typed annotation value plus its semantics.

    The typed slots exist so that a numeric annotation stays numeric and
    filterable, and the semantics field exists so that ``0`` and ``missing`` never
    become the same thing. Exactly one slot is populated for a present value;
    for a non-present value all slots stay empty and the semantics carry the
    meaning.
    """

    value_type: AnnotationValueType
    semantics: ValueSemantics = ValueSemantics.PRESENT
    value_string: str | None = None
    value_number: float | None = None
    value_integer: int | None = None
    value_boolean: bool | None = None
    value_json: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        populated = [
            slot
            for slot in (
                self.value_string,
                self.value_number,
                self.value_integer,
                self.value_boolean,
                self.value_json,
            )
            if slot is not None
        ]
        if self.semantics is ValueSemantics.PRESENT and not populated:
            raise ValidationError(
                "a present annotation value must carry a value", field="value"
            )
        if self.semantics is not ValueSemantics.PRESENT and populated:
            # Otherwise a "missing" annotation could smuggle a value that some
            # consumer would eventually treat as real.
            raise ValidationError(
                "a non-present annotation value must not carry a value", field="value"
            )
        if len(populated) > 1:
            raise ValidationError(
                "an annotation value populates exactly one typed slot", field="value"
            )


@dataclass(frozen=True, slots=True)
class VariantAnnotationRecord:
    """One annotation field for one variant, from one resource version.

    Extensible without migration: a new field is a new ``field_key``, not a new
    column. Two resources — or two versions of one resource — that disagree
    produce two rows, and the reader sees both.
    """

    id: str
    variant_id: str
    annotation_resource_id: str
    resource_version: str
    field_key: str
    value: AnnotationValue
    origin: DataOrigin
    transcript_id: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    scientific_execution_id: str | None = None
    #: When the value was read out of the resource, which is not the same as when
    #: the resource itself was published.
    retrieved_at: datetime | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PopulationRecord:
    """A cohort as defined by a population resource."""

    id: str
    population_resource_id: str
    population_key: str
    display_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PopulationFrequencyRecord:
    """A frequency *observation*, not a computed frequency.

    The application stores the numbers a population resource reported. It never
    computes an allele frequency from counts, never picks a "best" population and
    never aggregates across resources: those are scientific decisions.
    ``value_semantics`` distinguishes a genuine 0.0 from an absent value, which
    matters enormously for rare-variant reasoning downstream.
    """

    id: str
    variant_id: str
    population_id: str
    population_resource_id: str
    resource_version: str
    origin: DataOrigin
    allele_frequency: float | None = None
    allele_count: int | None = None
    allele_number: int | None = None
    homozygote_count: int | None = None
    hemizygote_count: int | None = None
    value_semantics: ValueSemantics = ValueSemantics.PRESENT
    #: Cohort subset the numbers apply to (e.g. a sex or ancestry stratum), as
    #: labelled by the resource. Never derived by combining other subsets.
    subset_key: str | None = None
    genome_resource_id: str | None = None
    #: Denominator/coverage/filter context exactly as published, so a frequency
    #: is never read without the conditions under which it holds.
    denominator_context: dict[str, Any] = field(default_factory=dict)
    scientific_execution_id: str | None = None
    retrieved_at: datetime | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.value_semantics is ValueSemantics.PRESENT
            and self.allele_frequency is None
            and self.allele_count is None
        ):
            raise ValidationError(
                "a present frequency observation must report a frequency or a count",
                field="allele_frequency",
            )


@dataclass(frozen=True, slots=True)
class ClinicalAssertionRecord:
    """An assertion made by an external clinical source, stored verbatim.

    This is not an interpretation and it is not this platform's opinion. The
    classification is kept as the source's own text alongside the source's own
    review-status wording, so conflicting submissions stay visible as conflicts
    instead of being averaged into a consensus nobody asserted. Package 7
    evaluates evidence; this layer only remembers what was asserted.
    """

    id: str
    variant_id: str
    #: Versioned external source row (``external_assertion_sources``).
    source_id: str
    external_record_identifier: str
    #: The source's own vocabulary, never remapped to an internal scale.
    reported_classification: str | None = None
    review_status_text: str | None = None
    assertion_statement: str | None = None
    condition_term: str | None = None
    condition_namespace: str | None = None
    condition_identifier: str | None = None
    assertion_method: str | None = None
    submitter: str | None = None
    asserted_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    #: Conflicts as reported by the source. Retained, never resolved here.
    conflict_information: dict[str, Any] = field(default_factory=dict)
    assertion_payload: dict[str, Any] = field(default_factory=dict)
    record_count: int | None = None
    origin: DataOrigin = DataOrigin.RETRIEVED
    value_semantics: ValueSemantics = ValueSemantics.PRESENT
    scientific_execution_id: str | None = None
    retrieved_at: datetime | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetVersionVariant:
    """Membership of a canonical variant in a dataset version.

    The dataset version is immutable, so membership is too. It exists so that
    "which variants does this input contain" is answerable without scanning
    observations, and so that a variant can belong to many dataset versions
    without any of them owning it.
    """

    id: str
    dataset_version_id: str
    variant_id: str
    workspace_id: str
    source_representation_id: str | None = None
    created_at: datetime | None = None


__all__ = [
    "AnnotationValue",
    "ClinicalAssertionRecord",
    "DatasetVersionVariant",
    "GeneReference",
    "PopulationFrequencyRecord",
    "PopulationRecord",
    "SampleObservation",
    "SampleRecord",
    "TranscriptContext",
    "TranscriptReference",
    "VariantAnnotationRecord",
    "VariantExternalIdentifier",
    "VariantRecord",
    "VariantRepresentation",
    "VariantSourceRepresentation",
]
