"""Annotation, population frequency and clinical assertion persistence.

All three are kept strictly separate from canonical variant identity, and each
carries the resource identity + version it came from, so conflicting values from
different resources or versions coexist instead of overwriting one another.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    ValueSemantics,
)
from app.infrastructure.persistence.base import (
    Base,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class VariantAnnotation(Base, TimestampMixin):
    """One annotation field/value for a variant, from one resource version.

    Extensible by design: a new annotation field needs no migration, while the
    typed value columns keep the data queryable and prevent silent coercion of
    ``missing``/``unknown``/``na``/``zero``/``false``.
    """

    __tablename__ = "variant_annotations"
    __table_args__ = (
        UniqueConstraint(
            "variant_id", "annotation_resource_id", "field_key", "transcript_id",
            name="uq_variant_annotations_variant_resource_field_transcript",
        ),
        state_check("value_type", AnnotationValueType, "value_type_valid"),
        state_check("value_semantics", ValueSemantics, "value_semantics_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_variant_annotations_field_key", "field_key"),
        Index("ix_variant_annotations_variant_id_field_key", "variant_id", "field_key"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    transcript_id: Mapped[str | None] = fk_column("app.transcripts.id", nullable=True)
    annotation_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    resource_version: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_integer: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(nullable=True)
    value_json: Mapped[dict | None] = json_column()
    value_semantics: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValueSemantics.PRESENT.value
    )
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.GENERATED.value
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[dict | None] = json_column()


class Population(Base, TimestampMixin):
    """A population cohort defined by a population resource."""

    __tablename__ = "populations"
    __table_args__ = (
        UniqueConstraint("population_resource_id", "population_key",
                         name="uq_populations_population_resource_id_population_key"),
    )

    id: Mapped[str] = id_column()
    population_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    population_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class PopulationFrequencyObservation(Base, TimestampMixin):
    """A frequency observation. Conflicting observations coexist by design."""

    __tablename__ = "population_frequency_observations"
    __table_args__ = (
        UniqueConstraint(
            "variant_id", "population_id", "population_resource_id", "resource_version",
            name="uq_population_frequency_observations_variant_population_version",
        ),
        state_check("value_semantics", ValueSemantics, "value_semantics_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_population_frequency_observations_variant_id", "variant_id"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    population_id: Mapped[str] = fk_column("app.populations.id")
    population_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    resource_version: Mapped[str] = mapped_column(String(128), nullable=False)
    genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    allele_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    allele_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    homozygote_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hemizygote_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    allele_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Denominator/filtering context (e.g. subset, coverage, filter state).
    denominator_context: Mapped[dict | None] = json_column()
    value_semantics: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValueSemantics.PRESENT.value
    )
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.RETRIEVED.value
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[dict | None] = json_column()

    # --- Package 6 ---------------------------------------------------------
    #: The stratum the numbers apply to, as labelled by the resource. Subsets are
    #: never combined by the application to synthesise another subset.
    subset_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )


class ExternalAssertionSource(Base, TimestampMixin):
    """A versioned external clinical/evidence source."""

    __tablename__ = "external_assertion_sources"
    __table_args__ = (
        UniqueConstraint("source_key", "source_version",
                         name="uq_external_assertion_sources_source_key_source_version"),
    )

    id: Mapped[str] = id_column()
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = fk_column("app.scientific_resources.id", nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class ClinicalAssertion(Base, TimestampMixin):
    """One external assertion. Multiple assertions are never collapsed."""

    __tablename__ = "clinical_assertions"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_record_identifier", "variant_id",
            name="uq_clinical_assertions_identity",
        ),
        state_check("origin", DataOrigin, "origin_valid"),
        state_check("value_semantics", ValueSemantics, "value_semantics_valid"),
        Index("ix_clinical_assertions_variant_id", "variant_id"),
        Index("ix_clinical_assertions_external_record_identifier",
              "external_record_identifier"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    source_id: Mapped[str] = fk_column("app.external_assertion_sources.id")
    external_record_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Reported classification text, kept verbatim; never mapped in place.
    reported_classification: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_term: Mapped[str | None] = mapped_column(String(512), nullable=True)
    condition_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assertion_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Conflict information as reported by the source, retained explicitly.
    conflict_information: Mapped[dict | None] = json_column()
    assertion_payload: Mapped[dict | None] = json_column()
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.RETRIEVED.value
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[dict | None] = json_column()
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Package 6 ---------------------------------------------------------
    condition_namespace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assertion_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asserted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: An assertion that a source published as "not provided" is recorded as such
    #: rather than as an absent assertion.
    value_semantics: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValueSemantics.PRESENT.value
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
