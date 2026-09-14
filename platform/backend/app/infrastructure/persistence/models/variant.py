"""Canonical variant identity, source representation and observation.

Canonical identity is *exactly* reference context + contig + position + reference
allele + alternate allele + normalization identity. rsID, ClinVar accessions and
HGVS are external *references*, stored separately in
``variant_external_identifiers`` — never treated as identity.

Sample observations are separate rows so one canonical variant can occur across
many samples and datasets without touching its identity. Bulk per-sample genomic
matrices remain in the Parquet/DuckDB analytical layer; this table holds the
transactional observations the application itself reasons about.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DataOrigin,
    NormalizationState,
    ValueSemantics,
    VariantClass,
    Zygosity,
)
from app.infrastructure.persistence.base import (
    Base,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Variant(Base, TimestampMixin):
    """Canonical variant identity. Immutable once written."""

    __tablename__ = "variants"
    __table_args__ = (
        # Canonical identity is unique within its reference context.
        UniqueConstraint(
            "reference_genome_resource_id",
            "contig",
            "position",
            "reference_allele",
            "alternate_allele",
            "normalization_version",
            name="uq_variants_canonical_identity",
        ),
        state_check("variant_class", VariantClass, "variant_class_valid"),
        state_check("normalization_state", NormalizationState, "normalization_state_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_variants_contig_position", "contig", "position"),
        Index("ix_variants_canonical_key", "canonical_key"),
    )

    id: Mapped[str] = id_column()
    #: Reference context is part of identity, not metadata.
    reference_genome_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    contig: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: End position for symbolic/structural variants.
    end_position: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reference_allele: Mapped[str] = mapped_column(Text, nullable=False)
    alternate_allele: Mapped[str] = mapped_column(Text, nullable=False)
    variant_class: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Symbolic allele (``<DEL>``, ``<DUP>``) / SV type when applicable.
    symbolic_allele: Mapped[str | None] = mapped_column(String(64), nullable=True)
    structural_variant_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalization_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=NormalizationState.NOT_NORMALIZED.value
    )
    #: Identity of the normalization procedure that produced this record.
    normalization_version: Mapped[str] = mapped_column(String(128), nullable=False)
    normalization_engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    #: Deterministic textual rendering of the canonical identity, for lookups.
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Package 6 ---------------------------------------------------------
    #: How this canonical form came to exist. Not defaulted per row type: an
    #: imported record and an engine-generated one must stay distinguishable.
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.GENERATED.value
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )


class VariantSourceRepresentation(Base, TimestampMixin):
    """The variant exactly as it appeared in a source dataset version.

    Never mutated and never overwritten by normalization: the canonical link plus
    the transformation metadata form the normalization lineage.
    """

    __tablename__ = "variant_source_representations"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "source_record_key",
            name="uq_variant_source_representations_dataset_version_id_record_key",
        ),
        state_check("normalization_state", NormalizationState, "normalization_state_valid"),
    )

    id: Mapped[str] = id_column()
    #: Nullable: a source record that failed normalization is still preserved.
    variant_id: Mapped[str | None] = fk_column("app.variants.id", nullable=True)
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    #: Stable locator within the source file (e.g. line/record identity).
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    source_contig: Mapped[str] = mapped_column(String(64), nullable=False)
    source_position: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_reference_allele: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_alternate_allele: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Verbatim source fields, retained for reproducibility.
    source_payload: Mapped[dict | None] = json_column()
    normalization_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=NormalizationState.NOT_NORMALIZED.value
    )
    normalization_failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    transformation_metadata: Mapped[dict | None] = json_column()
    #: Liftover/build conversion lineage, when the build was converted.
    build_conversion_metadata: Mapped[dict | None] = json_column()


class VariantExternalIdentifier(Base, TimestampMixin):
    """External reference (rsID, ClinVar accession, HGVS string, ...)."""

    __tablename__ = "variant_external_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "variant_id", "namespace", "external_identifier", "source_resource_id",
            name="uq_variant_external_identifiers_identity",
        ),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_variant_external_identifiers_namespace_external_identifier",
              "namespace", "external_identifier"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    #: ``dbsnp`` | ``clinvar`` | ``hgvs_g`` | ``cosmic`` | ...
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    source_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.IMPORTED.value
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Gene(Base, TimestampMixin):
    """Gene reference identity, sourced from an annotation resource."""

    __tablename__ = "genes"
    __table_args__ = (
        UniqueConstraint("namespace", "gene_identifier",
                         name="uq_genes_namespace_gene_identifier"),
        Index("ix_genes_symbol", "symbol"),
    )

    id: Mapped[str] = id_column()
    #: ``hgnc`` | ``ensembl`` | ``ncbi``.
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    gene_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    metadata_json: Mapped[dict | None] = json_column()


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint(
            "namespace", "transcript_identifier", "transcript_version",
            name="uq_transcripts_namespace_transcript_identifier_version",
        ),
    )

    id: Mapped[str] = id_column()
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    transcript_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    transcript_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gene_id: Mapped[str | None] = fk_column("app.genes.id", nullable=True)
    is_canonical: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    metadata_json: Mapped[dict | None] = json_column()


class VariantTranscriptConsequence(Base, TimestampMixin):
    """Consequence context. One variant may have many transcript contexts."""

    __tablename__ = "variant_transcript_consequences"
    __table_args__ = (
        UniqueConstraint(
            "variant_id", "transcript_id", "source_resource_id", "consequence_term",
            name="uq_variant_transcript_consequences_identity",
        ),
        state_check("origin", DataOrigin, "origin_valid"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    transcript_id: Mapped[str | None] = fk_column("app.transcripts.id", nullable=True)
    gene_id: Mapped[str | None] = fk_column("app.genes.id", nullable=True)
    consequence_term: Mapped[str] = mapped_column(String(128), nullable=False)
    impact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hgvs_genomic: Mapped[str | None] = mapped_column(Text, nullable=True)
    hgvs_coding: Mapped[str | None] = mapped_column(Text, nullable=True)
    hgvs_protein: Mapped[str | None] = mapped_column(Text, nullable=True)
    exon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intron: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Which annotation resource/engine produced this consequence.
    source_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.GENERATED.value
    )
    details: Mapped[dict | None] = json_column()


class Sample(Base, TimestampMixin):
    """A sample declared by a dataset version manifest."""

    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "sample_key",
                         name="uq_samples_dataset_version_id_sample_key"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    dataset_id: Mapped[str] = fk_column("app.datasets.id")
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    #: Identifier as provided by the source manifest.
    sample_key: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Pseudonymised label used in the UI; source identity stays in metadata.
    display_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sex_karyotype: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_metadata: Mapped[dict | None] = json_column()


class VariantObservation(Base, TimestampMixin):
    """Per-sample observation of a canonical variant. Never part of identity."""

    __tablename__ = "variant_observations"
    __table_args__ = (
        UniqueConstraint(
            "sample_id", "variant_id", "dataset_version_id",
            name="uq_variant_observations_sample_id_variant_id_dataset_version_id",
        ),
        state_check("zygosity", Zygosity, "zygosity_valid"),
        state_check("genotype_semantics", ValueSemantics, "genotype_semantics_valid"),
    )

    id: Mapped[str] = id_column()
    sample_id: Mapped[str] = fk_column("app.samples.id")
    variant_id: Mapped[str] = fk_column("app.variants.id")
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    variant_source_representation_id: Mapped[str | None] = fk_column(
        "app.variant_source_representations.id", nullable=True
    )
    genotype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Distinguishes an absent genotype from ``./.`` and from a real value.
    genotype_semantics: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValueSemantics.PRESENT.value
    )
    zygosity: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=Zygosity.UNKNOWN.value
    )
    allele_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    read_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alternate_allele_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genotype_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variant_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    filter_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observation_metadata: Mapped[dict | None] = json_column()
    source_provenance: Mapped[dict | None] = json_column()
