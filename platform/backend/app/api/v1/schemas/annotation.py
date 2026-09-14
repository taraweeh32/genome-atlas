"""Transport schemas for annotation resources, profiles, runs and results.

Conventions carried over from the other schema modules: request payloads forbid
unknown fields, responses expose enum *values*, and nothing internal is serialized
to a tenant client.

Three things specific to this surface:

* **Identity always travels with its version.** A resource, a profile version, an
  engine and a reference context are each named with their version, because an
  annotation value without them is not reproducible.
* **Absence is preserved.** A value that a resource reported as missing, unknown or
  not-applicable is declared as such rather than sent as ``0`` or ``""``.
* **Bulk annotation values are never inlined.** A result version carries counts,
  provenance and its analytical location; the values themselves are read through
  the variant and filtering surfaces, which are paginated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel, Collection
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Fields                                                                      #
# --------------------------------------------------------------------------- #


class AnnotationFieldSpecPayload(ApiModel):
    """One field an annotation resource version declares it produces."""

    field_key: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    value_type: str = Field(description="string | number | integer | boolean | json")
    description: str | None = Field(default=None, max_length=2000)
    missing_semantics: list[str] | None = Field(
        default=None,
        description="Which absence markers this field can legitimately carry.",
    )
    allowed_values: list[str] | None = None
    unit: str | None = Field(default=None, max_length=64)
    high_cardinality: bool = False
    filterable: bool = True
    sortable: bool = False
    scientific_category: str | None = Field(default=None, max_length=128)
    column: str | None = Field(
        default=None,
        max_length=255,
        description="Analytical column name, when it differs from the field key.",
    )
    metadata: dict[str, object] | None = None


class AnnotationFieldSpecResponse(ApiModel):
    field_key: str
    label: str
    value_type: str
    description: str | None
    missing_semantics: list[str]
    allowed_values: list[str]
    unit: str | None
    high_cardinality: bool
    filterable: bool
    sortable: bool
    scientific_category: str | None
    analytical_column: str


class FilterFieldSummaryResponse(ApiModel):
    """An annotation field as the filtering layer offers it.

    Returned in the same shape as any other filterable field, so a client renders
    annotation fields with the code it already has and hardcodes nothing.
    """

    id: str
    label: str
    description: str | None
    data_type: str
    category: str
    operators: list[str]
    nullable: bool
    missing_semantics: list[str]
    high_cardinality: bool
    sortable: bool
    filterable: bool
    scientific_category: str | None
    source_resource_key: str | None
    source_resource_version: str | None
    available: bool
    version: str | None


class AnnotationFieldCollection(ApiModel):
    items: list[FilterFieldSummaryResponse]
    registry_version: str


# --------------------------------------------------------------------------- #
# Resources                                                                   #
# --------------------------------------------------------------------------- #


class RegisterResourcePayload(ApiModel):
    resource_key: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    category: str = Field(
        description="consequence | transcript | gene | functional | external_database | other"
    )
    provider: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    genome_assembly: str | None = Field(default=None, max_length=64)
    reference_genome_resource_id: str | None = None
    release_label: str | None = Field(default=None, max_length=128)
    released_at: datetime | None = None
    schema_version: str | None = Field(default=None, max_length=128)
    checksum_algorithm: str | None = Field(default=None, max_length=64)
    checksum_value: str | None = Field(default=None, max_length=256)
    size_bytes: int | None = Field(default=None, ge=0)
    fields: list[AnnotationFieldSpecPayload] = Field(default_factory=list)
    provenance: dict[str, object] | None = None
    licensing: dict[str, object] | None = None
    metadata: dict[str, object] | None = None


class TransitionResourcePayload(ApiModel):
    state: str = Field(
        description="registered | active | deprecated | retired | invalidated"
    )
    reason: str | None = Field(default=None, max_length=2000)


class AnnotationResourceResponse(ApiModel):
    id: str
    resource_key: str
    version: str
    display_name: str
    category: str
    state: str
    provider: str | None
    description: str | None
    genome_assembly: str | None
    reference_genome_resource_id: str | None
    release_label: str | None
    released_at: datetime | None
    schema_version: str | None
    checksum_algorithm: str | None
    checksum_value: str | None
    size_bytes: int | None
    is_usable: bool
    fields: list[AnnotationFieldSpecResponse]
    provenance: dict[str, object]
    licensing: dict[str, object]
    metadata: dict[str, object]
    activated_at: datetime | None
    deprecated_at: datetime | None
    retired_at: datetime | None
    invalidated_at: datetime | None
    invalidation_reason: str | None
    created_at: datetime


class AnnotationResourceCollection(Collection[AnnotationResourceResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Profiles                                                                    #
# --------------------------------------------------------------------------- #


class ProfileVersionPayload(ApiModel):
    capability_id: str = Field(min_length=1, max_length=128)
    resource_ids: list[str] = Field(min_length=1)
    capability_version: str | None = Field(default=None, max_length=128)
    engine_resource_id: str | None = None
    engine_version: str | None = Field(default=None, max_length=128)
    genome_assembly: str | None = Field(default=None, max_length=64)
    reference_genome_resource_id: str | None = None
    required_inputs: list[str] | None = None
    parameters: dict[str, object] | None = None
    provenance_requirements: list[str] | None = None
    schema_version: str | None = Field(default=None, max_length=128)
    change_note: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, object] | None = None


class CreateProfilePayload(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    version: ProfileVersionPayload
    description: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, object] | None = None


class ProfileResourceBindingResponse(ApiModel):
    resource_id: str
    resource_key: str
    resource_version: str
    category: str
    role: str


class AnnotationProfileVersionResponse(ApiModel):
    id: str
    profile_id: str
    version_number: int
    capability_id: str
    capability_version: str | None
    configuration_digest: str
    engine_resource_id: str | None
    engine_version: str | None
    genome_assembly: str | None
    reference_genome_resource_id: str | None
    required_inputs: list[str]
    output_field_keys: list[str]
    parameters: dict[str, object]
    provenance_requirements: list[str]
    schema_version: str | None
    change_note: str | None
    is_referenced: bool
    resources: list[ProfileResourceBindingResponse]
    created_at: datetime


class AnnotationProfileResponse(ApiModel):
    id: str
    name: str
    state: str
    description: str | None
    latest_version_number: int
    is_referenced: bool
    is_offered: bool
    metadata: dict[str, object]
    created_at: datetime
    versions: list[AnnotationProfileVersionResponse] = Field(default_factory=list)


class AnnotationProfileCollection(Collection[AnnotationProfileResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Runs, results and validation                                                #
# --------------------------------------------------------------------------- #


class RequestRunPayload(ApiModel):
    annotation_profile_id: str
    result_set_id: str | None = None
    dataset_version_id: str | None = None
    profile_version_number: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=128)
    metadata: dict[str, object] | None = None


class AnnotationValidationFindingResponse(ApiModel):
    id: str
    code: str
    message: str
    severity: str
    field_key: str | None
    variant_id: str | None
    record_index: int | None
    detail: dict[str, object]


class AnnotationRunResponse(ApiModel):
    id: str
    workspace_id: str
    project_id: str | None
    profile_id: str
    profile_version_id: str
    profile_version_number: int
    state: str
    result_set_id: str | None
    dataset_version_id: str | None
    requested_by: str | None
    requested_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None
    job_id: str | None
    scientific_execution_id: str | None
    external_execution_id: str | None
    capability_id: str
    capability_version: str | None
    engine_resource_id: str | None
    engine_version: str | None
    environment_version: str | None
    container_image_digest: str | None
    node_identity: str | None
    genome_assembly: str | None
    configuration_digest: str
    configuration_snapshot: dict[str, object]
    correlation_id: str
    failure_code: str | None
    failure_message: str | None
    record_count: int | None
    is_terminal: bool
    findings: list[AnnotationValidationFindingResponse] = Field(default_factory=list)


class AnnotationRunCollection(Collection[AnnotationRunResponse]):
    page: PageMeta


class AnnotationResultResponse(ApiModel):
    id: str
    annotation_run_id: str
    workspace_id: str
    project_id: str | None
    resource_id: str
    resource_key: str
    resource_version: str
    version_number: int
    state: str
    result_set_id: str | None
    dataset_version_id: str | None
    profile_version_id: str | None
    scientific_execution_id: str | None
    engine_version: str | None
    environment_version: str | None
    container_image_digest: str | None
    node_identity: str | None
    genome_assembly: str | None
    analytical_location: str | None
    checksum_algorithm: str | None
    checksum_value: str | None
    row_count: int | None
    stored_record_count: int
    declared_record_count: int | None
    rejected_record_count: int
    field_keys: list[str]
    contract_version: str
    payload_digest: str | None
    parameters_digest: str | None
    completeness: str
    is_development_payload: bool
    supersedes_id: str | None
    superseded_by_id: str | None
    is_readable: bool
    provenance: dict[str, object]
    ingested_at: datetime | None
    created_at: datetime


class AnnotationResultCollection(Collection[AnnotationResultResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Ingestion delivery                                                          #
# --------------------------------------------------------------------------- #


class AnnotationResourceIdentityPayload(ApiModel):
    resource_key: str
    resource_version: str
    resource_id: str | None = None
    schema_version: str | None = None
    genome_assembly: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None


class AnnotationValuePayload(ApiModel):
    field_key: str
    value_type: str
    value_semantics: str | None = None
    value_string: str | None = None
    value_number: float | None = None
    value_integer: int | None = None
    value_boolean: bool | None = None
    value_json: dict[str, object] | None = None
    transcript_identifier: str | None = None


class AnnotationRecordPayload(ApiModel):
    variant_id: str
    values: list[AnnotationValuePayload] = Field(min_length=1)
    source_variant_key: str | None = None
    origin: str | None = Field(
        default=None, description="imported | retrieved | generated"
    )
    retrieved_at: datetime | None = None


class AnnotationArtifactPayload(ApiModel):
    artifact_key: str
    kind: str
    storage_uri: str | None = None
    analytical_location: str | None = None
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    row_count: int | None = Field(default=None, ge=0)
    column_schema: dict[str, object] | None = None


class IngestAnnotationPayloadBody(ApiModel):
    """One annotation delivery from the scientific subsystem.

    Structured only: there is no field through which a caller can ask the platform
    to run a command, and the scope is taken from the run, never from this body.
    """

    contract_version: str
    resource: AnnotationResourceIdentityPayload
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    scientific_execution_id: str | None = None
    genome_assembly: str | None = None
    parameters_digest: str | None = None
    records: list[AnnotationRecordPayload] = Field(default_factory=list)
    artifacts: list[AnnotationArtifactPayload] = Field(default_factory=list)
    declared_record_count: int | None = Field(default=None, ge=0)
    completeness: str | None = None
    metadata: dict[str, object] | None = None
    is_development_payload: bool = False


class AnnotationIngestionResponse(ApiModel):
    result: AnnotationResultResponse
    stored_record_count: int
    rejected_record_count: int
    findings: list[dict[str, object]] = Field(default_factory=list)


__all__ = [
    "AnnotationArtifactPayload",
    "AnnotationFieldCollection",
    "AnnotationFieldSpecPayload",
    "AnnotationFieldSpecResponse",
    "AnnotationIngestionResponse",
    "AnnotationProfileCollection",
    "AnnotationProfileResponse",
    "AnnotationProfileVersionResponse",
    "AnnotationRecordPayload",
    "AnnotationResourceCollection",
    "AnnotationResourceIdentityPayload",
    "AnnotationResourceResponse",
    "AnnotationResultCollection",
    "AnnotationResultResponse",
    "AnnotationRunCollection",
    "AnnotationRunResponse",
    "AnnotationValidationFindingResponse",
    "AnnotationValuePayload",
    "CreateProfilePayload",
    "FilterFieldSummaryResponse",
    "IngestAnnotationPayloadBody",
    "ProfileResourceBindingResponse",
    "ProfileVersionPayload",
    "RegisterResourcePayload",
    "RequestRunPayload",
    "TransitionResourcePayload",
]
