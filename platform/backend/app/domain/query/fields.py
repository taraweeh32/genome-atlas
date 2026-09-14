"""The filter field dictionary.

One registry, one version, one place. Filterable fields are declared here so that
neither the frontend nor the analytical layer invents its own list: the UI renders
what the registry reports, validation checks against the registry, and the query
compiler resolves a field identifier to a physical column only through it.

Three properties are worth stating plainly.

* **Availability is contextual.** A dictionary entry says the platform *knows* a
  field; it never claims the selected surface contains it. A field is available
  only when the described columns of the result surface include its column, so a
  dataset without population frequencies simply offers no frequency filter.
* **Absence is declared.** Each entry names the missing-value semantics that may
  legitimately appear for it (Package 6 ``ValueSemantics``), which is what lets
  filtering distinguish unreported from zero and from false.
* **No entry interprets anything.** ``consequence_term`` is a stored term, not a
  severity; ``clinical_significance`` is a submitter's reported classification,
  not a platform conclusion. Nothing here ranks, scores or grades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.query.operators import (
    FilterDataType,
    FilterOperator,
    operators_for,
)
from app.domain.value_objects.enums import StrEnum, ValueSemantics

#: Version of the dictionary as a whole. Every execution records it, so an
#: expression can always be re-read against the definitions it was written for.
FIELD_DICTIONARY_VERSION = "1.0.0"


class FilterFieldCategory(StrEnum):
    """Which part of the recorded scientific data a field comes from."""

    VARIANT_IDENTITY = "variant_identity"
    VARIANT_CONTEXT = "variant_context"
    OBSERVATION = "observation"
    POPULATION = "population"
    ANNOTATION = "annotation"
    CLINICAL_ASSERTION = "clinical_assertion"
    PROVENANCE = "provenance"


class FilterFieldOrigin(StrEnum):
    """Where the stored value came from, mirroring Package 6 attribution."""

    IMPORTED = "imported"
    COMPUTED = "computed"
    PLATFORM_RECORDED = "platform_recorded"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class FilterFieldDefinition:
    """One filterable field, fully declared."""

    id: str
    label: str
    description: str
    data_type: FilterDataType
    category: FilterFieldCategory
    #: Physical column on the materialized analytical surface. The only place a
    #: field identifier is ever turned into a column name.
    column: str
    origin: FilterFieldOrigin
    #: Narrowing of the type's operator set, when a field admits fewer.
    operators: tuple[FilterOperator, ...] = ()
    nullable: bool = True
    #: Absence markers that may legitimately appear for this field.
    missing_semantics: tuple[ValueSemantics, ...] = (
        ValueSemantics.MISSING,
        ValueSemantics.NULL,
        ValueSemantics.UNKNOWN,
    )
    #: Closed value set, when the platform knows it. ``None`` means open.
    allowed_values: tuple[str, ...] | None = None
    #: Too many distinct values to enumerate in a browser: values are searched
    #: server-side, page by page.
    high_cardinality: bool = False
    searchable: bool = False
    sortable: bool = True
    filterable: bool = True
    #: Scientific vocabulary this field belongs to, for display and governance.
    scientific_category: str | None = None
    #: Contexts that must be present for the field to be filterable at all.
    requires_context: tuple[str, ...] = ("result_set",)
    #: Companion column carrying ``ValueSemantics`` for this field, when the
    #: surface reports semantics separately from the value.
    semantics_column: str | None = None
    version: str = FIELD_DICTIONARY_VERSION
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def supported_operators(self) -> tuple[FilterOperator, ...]:
        allowed = set(self.operators) & operators_for(self.data_type) if self.operators else set(
            operators_for(self.data_type)
        )
        return tuple(sorted(allowed, key=lambda operator: operator.value))

    def supports(self, operator: FilterOperator) -> bool:
        return operator in self.supported_operators


def _categorical(
    field_id: str,
    label: str,
    description: str,
    column: str,
    category: FilterFieldCategory,
    origin: FilterFieldOrigin,
    *,
    allowed_values: tuple[str, ...] | None = None,
    high_cardinality: bool = False,
    scientific_category: str | None = None,
) -> FilterFieldDefinition:
    return FilterFieldDefinition(
        id=field_id,
        label=label,
        description=description,
        data_type=FilterDataType.CATEGORICAL,
        category=category,
        column=column,
        origin=origin,
        allowed_values=allowed_values,
        high_cardinality=high_cardinality,
        searchable=high_cardinality,
        scientific_category=scientific_category,
    )


#: The shipped dictionary. Every entry corresponds to something the scientific
#: data layer already stores; none of them is derived here.
_DEFINITIONS: tuple[FilterFieldDefinition, ...] = (
    # --- variant identity ------------------------------------------------- #
    _categorical(
        "genome_build",
        "Genome build",
        "Reference build the coordinates are stated against, as declared by the "
        "producing execution.",
        "genome_build",
        FilterFieldCategory.VARIANT_IDENTITY,
        FilterFieldOrigin.PLATFORM_RECORDED,
        scientific_category="reference_genome",
    ),
    _categorical(
        "contig",
        "Contig",
        "Contig or chromosome of the canonical representation.",
        "contig",
        FilterFieldCategory.VARIANT_IDENTITY,
        FilterFieldOrigin.IMPORTED,
        scientific_category="coordinates",
    ),
    FilterFieldDefinition(
        id="position",
        label="Position",
        description="Coordinate on the contig. Always filtered together with a contig "
        "condition; a position range alone has no biological meaning.",
        data_type=FilterDataType.GENOMIC_POSITION,
        category=FilterFieldCategory.VARIANT_IDENTITY,
        column="position",
        origin=FilterFieldOrigin.IMPORTED,
        nullable=False,
        scientific_category="coordinates",
    ),
    FilterFieldDefinition(
        id="reference_allele",
        label="Reference allele",
        description="Reference allele of the canonical representation, as stored.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.VARIANT_IDENTITY,
        column="reference_allele",
        origin=FilterFieldOrigin.IMPORTED,
        scientific_category="alleles",
    ),
    FilterFieldDefinition(
        id="alternate_allele",
        label="Alternate allele",
        description="Alternate allele of the canonical representation, as stored.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.VARIANT_IDENTITY,
        column="alternate_allele",
        origin=FilterFieldOrigin.IMPORTED,
        scientific_category="alleles",
    ),
    _categorical(
        "variant_class",
        "Variant class",
        "Variant type as declared by the source or the scientific engine. Never "
        "derived from the allele strings by the platform.",
        "variant_class",
        FilterFieldCategory.VARIANT_IDENTITY,
        FilterFieldOrigin.MIXED,
        scientific_category="variant_class",
    ),
    _categorical(
        "normalization_state",
        "Normalization state",
        "Whether the record carries a normalized representation, and under which "
        "stated normalization. Recorded, never inferred.",
        "normalization_state",
        FilterFieldCategory.VARIANT_IDENTITY,
        FilterFieldOrigin.COMPUTED,
        scientific_category="normalization",
    ),
    FilterFieldDefinition(
        id="canonical_key",
        label="Canonical variant key",
        description="Platform canonical key for the variant record.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.VARIANT_IDENTITY,
        column="canonical_key",
        origin=FilterFieldOrigin.PLATFORM_RECORDED,
        high_cardinality=True,
        searchable=True,
    ),
    FilterFieldDefinition(
        id="source_variant_id",
        label="Source variant identifier",
        description="Identifier the submitting source used for the variant row.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.VARIANT_IDENTITY,
        column="source_variant_id",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
    ),
    # --- variant context -------------------------------------------------- #
    FilterFieldDefinition(
        id="gene_symbol",
        label="Gene",
        description="Gene symbol recorded on a transcript context of the variant.",
        data_type=FilterDataType.CATEGORICAL,
        category=FilterFieldCategory.VARIANT_CONTEXT,
        column="gene_symbol",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="gene",
    ),
    FilterFieldDefinition(
        id="gene_id",
        label="Gene identifier",
        description="Stable gene identifier recorded on a transcript context.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.VARIANT_CONTEXT,
        column="gene_id",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="gene",
    ),
    FilterFieldDefinition(
        id="transcript_id",
        label="Transcript",
        description="Transcript the consequence was recorded against.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.VARIANT_CONTEXT,
        column="transcript_id",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="transcript",
    ),
    _categorical(
        "consequence_term",
        "Consequence",
        "Consequence term as recorded by the scientific layer. The platform does "
        "not grade, rank or interpret it.",
        "consequence_term",
        FilterFieldCategory.VARIANT_CONTEXT,
        FilterFieldOrigin.COMPUTED,
        high_cardinality=True,
        scientific_category="consequence",
    ),
    _categorical(
        "impact",
        "Impact",
        "Impact label recorded alongside the consequence, as reported by the "
        "annotation source.",
        "impact",
        FilterFieldCategory.VARIANT_CONTEXT,
        FilterFieldOrigin.COMPUTED,
        scientific_category="consequence",
    ),
    FilterFieldDefinition(
        id="hgvs_coding",
        label="HGVS (coding)",
        description="Coding HGVS description as already stored. Never generated here.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.VARIANT_CONTEXT,
        column="hgvs_coding",
        origin=FilterFieldOrigin.COMPUTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="hgvs",
    ),
    FilterFieldDefinition(
        id="hgvs_protein",
        label="HGVS (protein)",
        description="Protein HGVS description as already stored. Never generated here.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.VARIANT_CONTEXT,
        column="hgvs_protein",
        origin=FilterFieldOrigin.COMPUTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="hgvs",
    ),
    FilterFieldDefinition(
        id="external_identifier",
        label="External identifier",
        description="External accession recorded for the variant (e.g. a database "
        "record key), as supplied by its source.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.VARIANT_CONTEXT,
        column="external_identifier",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
    ),
    # --- observation / sample --------------------------------------------- #
    FilterFieldDefinition(
        id="sample_id",
        label="Sample",
        description="Sample the observation belongs to.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.OBSERVATION,
        column="sample_id",
        origin=FilterFieldOrigin.PLATFORM_RECORDED,
        high_cardinality=True,
        searchable=True,
    ),
    _categorical(
        "zygosity",
        "Zygosity",
        "Zygosity as recorded for the observation.",
        "zygosity",
        FilterFieldCategory.OBSERVATION,
        FilterFieldOrigin.IMPORTED,
        scientific_category="genotype",
    ),
    FilterFieldDefinition(
        id="genotype",
        label="Genotype",
        description="Genotype string exactly as recorded. Absence is reported through "
        "its genotype semantics, never as a value.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.OBSERVATION,
        column="genotype",
        origin=FilterFieldOrigin.IMPORTED,
        semantics_column="genotype_semantics",
        scientific_category="genotype",
    ),
    FilterFieldDefinition(
        id="read_depth",
        label="Read depth",
        description="Read depth recorded for the observation.",
        data_type=FilterDataType.INTEGER,
        category=FilterFieldCategory.OBSERVATION,
        column="read_depth",
        origin=FilterFieldOrigin.IMPORTED,
        semantics_column="genotype_semantics",
        scientific_category="quality",
    ),
    FilterFieldDefinition(
        id="alternate_allele_depth",
        label="Alternate allele depth",
        description="Depth supporting the alternate allele, as recorded.",
        data_type=FilterDataType.INTEGER,
        category=FilterFieldCategory.OBSERVATION,
        column="alternate_allele_depth",
        origin=FilterFieldOrigin.IMPORTED,
        semantics_column="genotype_semantics",
        scientific_category="quality",
    ),
    _categorical(
        "filter_status",
        "Caller filter status",
        "Filter status as reported by the producing caller (e.g. PASS).",
        "filter_status",
        FilterFieldCategory.OBSERVATION,
        FilterFieldOrigin.IMPORTED,
        scientific_category="quality",
    ),
    # --- population data -------------------------------------------------- #
    FilterFieldDefinition(
        id="population_id",
        label="Population",
        description="Population the frequency record refers to.",
        data_type=FilterDataType.CATEGORICAL,
        category=FilterFieldCategory.POPULATION,
        column="population_id",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="population",
    ),
    FilterFieldDefinition(
        id="allele_frequency",
        label="Allele frequency",
        description="Allele frequency as reported by the population resource. An "
        "unreported frequency stays unreported and is never read as zero.",
        data_type=FilterDataType.DECIMAL,
        category=FilterFieldCategory.POPULATION,
        column="allele_frequency",
        origin=FilterFieldOrigin.IMPORTED,
        semantics_column="frequency_semantics",
        missing_semantics=(
            ValueSemantics.MISSING,
            ValueSemantics.NULL,
            ValueSemantics.NA,
            ValueSemantics.UNKNOWN,
            ValueSemantics.NOT_APPLICABLE,
        ),
        scientific_category="population_frequency",
    ),
    FilterFieldDefinition(
        id="allele_count",
        label="Allele count",
        description="Allele count as reported by the population resource.",
        data_type=FilterDataType.INTEGER,
        category=FilterFieldCategory.POPULATION,
        column="allele_count",
        origin=FilterFieldOrigin.IMPORTED,
        semantics_column="frequency_semantics",
        scientific_category="population_frequency",
    ),
    FilterFieldDefinition(
        id="allele_number",
        label="Allele number",
        description="Allele number (called alleles) as reported by the population "
        "resource.",
        data_type=FilterDataType.INTEGER,
        category=FilterFieldCategory.POPULATION,
        column="allele_number",
        origin=FilterFieldOrigin.IMPORTED,
        semantics_column="frequency_semantics",
        scientific_category="population_frequency",
    ),
    # --- annotation ------------------------------------------------------- #
    FilterFieldDefinition(
        id="annotation_field_key",
        label="Annotation field",
        description="Key of an annotation recorded by the scientific data layer.",
        data_type=FilterDataType.CATEGORICAL,
        category=FilterFieldCategory.ANNOTATION,
        column="annotation_field_key",
        origin=FilterFieldOrigin.COMPUTED,
        high_cardinality=True,
        searchable=True,
    ),
    FilterFieldDefinition(
        id="annotation_value_string",
        label="Annotation value (text)",
        description="Text value of an annotation, exactly as recorded.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.ANNOTATION,
        column="annotation_value_string",
        origin=FilterFieldOrigin.COMPUTED,
        semantics_column="annotation_value_semantics",
        high_cardinality=True,
        searchable=True,
    ),
    FilterFieldDefinition(
        id="annotation_value_number",
        label="Annotation value (numeric)",
        description="Numeric value of an annotation, exactly as recorded.",
        data_type=FilterDataType.DECIMAL,
        category=FilterFieldCategory.ANNOTATION,
        column="annotation_value_number",
        origin=FilterFieldOrigin.COMPUTED,
        semantics_column="annotation_value_semantics",
    ),
    _categorical(
        "annotation_resource_id",
        "Annotation source",
        "Annotation resource the value came from.",
        "annotation_resource_id",
        FilterFieldCategory.ANNOTATION,
        FilterFieldOrigin.PLATFORM_RECORDED,
        high_cardinality=True,
    ),
    FilterFieldDefinition(
        id="annotation_resource_version",
        label="Annotation source version",
        description="Version of the annotation resource that reported the value.",
        data_type=FilterDataType.STRING,
        category=FilterFieldCategory.ANNOTATION,
        column="annotation_resource_version",
        origin=FilterFieldOrigin.PLATFORM_RECORDED,
    ),
    # --- clinical assertions ---------------------------------------------- #
    _categorical(
        "clinical_significance",
        "Reported classification",
        "Classification exactly as reported by the submitting clinical record. "
        "It is the submitter's statement, not a platform conclusion.",
        "reported_classification",
        FilterFieldCategory.CLINICAL_ASSERTION,
        FilterFieldOrigin.IMPORTED,
        scientific_category="clinical_assertion",
    ),
    FilterFieldDefinition(
        id="clinical_condition_term",
        label="Condition",
        description="Condition term recorded on the clinical assertion.",
        data_type=FilterDataType.CATEGORICAL,
        category=FilterFieldCategory.CLINICAL_ASSERTION,
        column="condition_term",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="clinical_assertion",
    ),
    FilterFieldDefinition(
        id="clinical_submitter",
        label="Assertion submitter",
        description="Submitter of the clinical assertion, as reported.",
        data_type=FilterDataType.CATEGORICAL,
        category=FilterFieldCategory.CLINICAL_ASSERTION,
        column="submitter",
        origin=FilterFieldOrigin.IMPORTED,
        high_cardinality=True,
        searchable=True,
        scientific_category="clinical_assertion",
    ),
    _categorical(
        "clinical_review_status",
        "Assertion review status",
        "Review status as reported by the clinical record.",
        "review_status",
        FilterFieldCategory.CLINICAL_ASSERTION,
        FilterFieldOrigin.IMPORTED,
        scientific_category="clinical_assertion",
    ),
    FilterFieldDefinition(
        id="clinical_assertion_date",
        label="Assertion date",
        description="Date the clinical assertion was reported, where the source "
        "supplied one.",
        data_type=FilterDataType.DATETIME,
        category=FilterFieldCategory.CLINICAL_ASSERTION,
        column="assertion_date",
        origin=FilterFieldOrigin.IMPORTED,
        scientific_category="clinical_assertion",
    ),
    # --- provenance ------------------------------------------------------- #
    _categorical(
        "record_origin",
        "Record origin",
        "Whether the recorded value was imported, computed by the scientific "
        "layer, or entered by a human. Always distinguishable.",
        "origin",
        FilterFieldCategory.PROVENANCE,
        FilterFieldOrigin.PLATFORM_RECORDED,
    ),
    FilterFieldDefinition(
        id="scientific_execution_id",
        label="Scientific execution",
        description="Execution that produced the record, where one is recorded.",
        data_type=FilterDataType.IDENTIFIER,
        category=FilterFieldCategory.PROVENANCE,
        column="scientific_execution_id",
        origin=FilterFieldOrigin.PLATFORM_RECORDED,
        high_cardinality=True,
        searchable=True,
    ),
)


@dataclass(frozen=True, slots=True)
class FilterFieldRegistry:
    """An immutable, versioned set of field definitions."""

    version: str
    definitions: tuple[FilterFieldDefinition, ...]

    def get(self, field_id: str) -> FilterFieldDefinition | None:
        wanted = field_id.strip().lower()
        for definition in self.definitions:
            if definition.id == wanted:
                return definition
        return None

    @property
    def field_ids(self) -> tuple[str, ...]:
        return tuple(definition.id for definition in self.definitions)

    def filterable(self) -> tuple[FilterFieldDefinition, ...]:
        return tuple(
            definition
            for definition in self.definitions
            if definition.filterable and definition.available
        )

    def available_for_columns(
        self, columns: frozenset[str]
    ) -> tuple[FilterFieldDefinition, ...]:
        """Definitions whose physical column exists on the given surface.

        This is what keeps the dictionary honest: the platform advertises a field
        only where the selected surface actually carries it.
        """
        return tuple(
            definition
            for definition in self.filterable()
            if definition.column in columns
        )

    def in_category(
        self, category: FilterFieldCategory
    ) -> tuple[FilterFieldDefinition, ...]:
        return tuple(
            definition
            for definition in self.definitions
            if definition.category is category
        )

    def with_overrides(
        self, *, unavailable_field_ids: frozenset[str] = frozenset()
    ) -> FilterFieldRegistry:
        """Registry with administratively deactivated fields marked unavailable."""
        from dataclasses import replace as _replace

        return FilterFieldRegistry(
            version=self.version,
            definitions=tuple(
                _replace(definition, available=False)
                if definition.id in unavailable_field_ids
                else definition
                for definition in self.definitions
            ),
        )


DEFAULT_FIELD_REGISTRY = FilterFieldRegistry(
    version=FIELD_DICTIONARY_VERSION, definitions=_DEFINITIONS
)


__all__ = [
    "DEFAULT_FIELD_REGISTRY",
    "FIELD_DICTIONARY_VERSION",
    "FilterFieldCategory",
    "FilterFieldDefinition",
    "FilterFieldOrigin",
    "FilterFieldRegistry",
]
