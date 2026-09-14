"""Annotation registry, profile, run and annotation result persistence.

Deliberately *not* here:

* the annotation resources themselves — a registered annotation resource version
  is a row in ``scientific_resources`` (kind ``annotation_resource``), so it is
  governed by the same lifecycle as genomes, engines and rulesets;
* annotation values — those are ``variant_annotations`` rows from Package 6, and
  no second annotation-row table is introduced.

What is added is the bookkeeping the annotation layer needs: the fields a resource
version declares, immutable execution profiles, the run record, the versioned
annotation result and its validation findings.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    AnnotationResourceCategory,
    AnnotationResultState,
    AnnotationRunState,
    AnnotationValueType,
    ChecksumAlgorithm,
    QueryDefinitionState,
    ValidationSeverity,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class AnnotationResourceProfileField(Base, TimestampMixin):
    """One field a registered annotation resource version declares it produces.

    This is the schema ingestion validates against and the source of the
    filterable annotation fields Package 7 consumes. A new annotation field is a
    new row — never a migration and never a frontend change.
    """

    __tablename__ = "annotation_resource_fields"
    __table_args__ = (
        UniqueConstraint(
            "scientific_resource_id", "field_key",
            name="uq_annotation_resource_fields_resource_field_key",
        ),
        state_check("value_type", AnnotationValueType, "value_type_valid"),
        Index("ix_annotation_resource_fields_field_key", "field_key"),
    )

    id: Mapped[str] = id_column()
    scientific_resource_id: Mapped[str] = fk_column(
        "app.scientific_resources.id", ondelete="CASCADE"
    )
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Column on the produced analytical surface, when the resource names one.
    column_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scientific_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Absence markers the field may legitimately carry, so "not reported" stays
    #: distinguishable from zero and from false.
    missing_semantics: Mapped[dict | None] = json_column()
    allowed_values: Mapped[dict | None] = json_column()
    high_cardinality: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    filterable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sortable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    metadata_json: Mapped[dict | None] = json_column()


class AnnotationProfile(Base, TimestampMixin, ConcurrencyMixin):
    """A named annotation execution profile (platform-governed)."""

    __tablename__ = "annotation_profiles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_annotation_profiles_name"),
        state_check("state", QueryDefinitionState, "state_valid"),
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=QueryDefinitionState.DRAFT.value
    )
    latest_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    #: Set once a run used any version. From then on versions are append-only.
    is_referenced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    metadata_json: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class AnnotationProfileVersion(Base, TimestampMixin):
    """One immutable annotation profile version.

    Append-only by construction: a change adds a version. A run points at a
    version, so editing the profile afterwards can never alter a past run.
    """

    __tablename__ = "annotation_profile_versions"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "version_number",
            name="uq_annotation_profile_versions_profile_id_version_number",
        ),
        Index("ix_annotation_profile_versions_profile_id", "profile_id"),
    )

    id: Mapped[str] = id_column()
    profile_id: Mapped[str] = fk_column("app.annotation_profiles.id", ondelete="CASCADE")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Capability requested from the scientific subsystem. Never a command line.
    capability_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    genome_assembly: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    #: Pinned resource versions, required inputs, expected output fields and the
    #: provenance the producer must supply — the reproducibility statement.
    resources: Mapped[dict | None] = json_column()
    required_inputs: Mapped[dict | None] = json_column()
    output_field_keys: Mapped[dict | None] = json_column()
    parameters: Mapped[dict | None] = json_column()
    provenance_requirements: Mapped[dict | None] = json_column()
    configuration_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_referenced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    metadata_json: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class AnnotationRun(Base, TimestampMixin, ConcurrencyMixin):
    """One requested annotation run, with its frozen configuration."""

    __tablename__ = "annotation_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key",
            name="uq_annotation_runs_workspace_id_idempotency_key",
        ),
        state_check("state", AnnotationRunState, "state_valid"),
        Index("ix_annotation_runs_workspace_id_state", "workspace_id", "state"),
        Index("ix_annotation_runs_result_set_id", "result_set_id"),
        Index("ix_annotation_runs_correlation_id", "correlation_id"),
    )

    id: Mapped[str] = id_column()
    #: Tenancy is taken from the annotated surface, never from the request.
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    profile_id: Mapped[str] = fk_column("app.annotation_profiles.id")
    profile_version_id: Mapped[str] = fk_column("app.annotation_profile_versions.id")
    profile_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_set_id: Mapped[str | None] = fk_column("app.result_sets.id", nullable=True)
    dataset_version_id: Mapped[str | None] = fk_column(
        "app.dataset_versions.id", nullable=True
    )
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=AnnotationRunState.REQUESTED.value
    )
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    external_execution_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capability_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capability_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_image_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    genome_assembly: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Immutable copy of the configuration as it stood when the run was
    #: requested; a later profile edit cannot reach it.
    configuration_snapshot: Mapped[dict | None] = json_column()
    configuration_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class AnnotationResultVersion(Base, TimestampMixin, ConcurrencyMixin):
    """One versioned annotation result for one annotated surface.

    ``version_number`` is unique per surface and resource key, so an updated
    resource version adds a version instead of overwriting one. A superseded
    version stays readable, which is what keeps a historical analysis
    reproducible.
    """

    __tablename__ = "annotation_result_versions"
    __table_args__ = (
        UniqueConstraint(
            "annotation_run_id", "resource_key", "version_number",
            name="uq_annotation_result_versions_run_resource_version",
        ),
        UniqueConstraint(
            "annotation_run_id", "payload_digest",
            name="uq_annotation_result_versions_run_payload_digest",
        ),
        state_check("state", AnnotationResultState, "state_valid"),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
        Index(
            "ix_annotation_result_versions_result_set_id_resource_key",
            "result_set_id",
            "resource_key",
        ),
        Index("ix_annotation_result_versions_workspace_id", "workspace_id"),
    )

    id: Mapped[str] = id_column()
    annotation_run_id: Mapped[str] = fk_column("app.annotation_runs.id")
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    resource_key: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_version: Mapped[str] = mapped_column(String(128), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=AnnotationResultState.REGISTERED.value
    )
    result_set_id: Mapped[str | None] = fk_column("app.result_sets.id", nullable=True)
    dataset_version_id: Mapped[str | None] = fk_column(
        "app.dataset_versions.id", nullable=True
    )
    profile_version_id: Mapped[str | None] = fk_column(
        "app.annotation_profile_versions.id", nullable=True
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_image_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    genome_assembly: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Large annotation output stays in the analytical/object layer; PostgreSQL
    #: keeps the address, the checksum and the counts.
    analytical_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stored_record_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    declared_record_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rejected_record_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    field_keys: Mapped[dict | None] = json_column()
    contract_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parameters_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completeness: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: True when a development/mock adapter produced the payload, so a stand-in
    #: annotation can never be presented as a scientific one.
    is_development_payload: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    supersedes_id: Mapped[str | None] = fk_column(
        "app.annotation_result_versions.id", nullable=True
    )
    superseded_by_id: Mapped[str | None] = fk_column(
        "app.annotation_result_versions.id", nullable=True
    )
    provenance: Mapped[dict | None] = json_column()
    metadata_json: Mapped[dict | None] = json_column()
    ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AnnotationValidationFindingRow(Base, TimestampMixin):
    """One recorded validation observation about an annotation payload.

    Stored rather than only raised: a rejected record must stay explainable long
    after the request that carried it is gone.
    """

    __tablename__ = "annotation_validation_findings"
    __table_args__ = (
        state_check("severity", ValidationSeverity, "severity_valid"),
        Index("ix_annotation_validation_findings_run_id", "annotation_run_id"),
        Index("ix_annotation_validation_findings_code", "code"),
    )

    id: Mapped[str] = id_column()
    annotation_run_id: Mapped[str] = fk_column("app.annotation_runs.id", ondelete="CASCADE")
    annotation_result_version_id: Mapped[str | None] = fk_column(
        "app.annotation_result_versions.id", nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValidationSeverity.ERROR.value
    )
    field_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = json_column()


#: Categories are validated in the domain rather than by a table constraint,
#: because a resource's category lives in the scientific resource registry's
#: metadata; this keeps the vocabulary importable from one place.
ANNOTATION_RESOURCE_CATEGORIES = tuple(member.value for member in AnnotationResourceCategory)


__all__ = [
    "ANNOTATION_RESOURCE_CATEGORIES",
    "AnnotationProfile",
    "AnnotationProfileVersion",
    "AnnotationResourceProfileField",
    "AnnotationResultVersion",
    "AnnotationRun",
    "AnnotationValidationFindingRow",
]
