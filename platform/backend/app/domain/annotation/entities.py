"""Domain records for the annotation layer.

Four things are modelled, and they are deliberately four things:

* **A resource version** — one registered, versioned annotation resource. It is
  stored in the existing scientific resource registry (kind
  ``annotation_resource``), so annotation resources are governed by exactly the
  same lifecycle as reference genomes, engines and rulesets.
* **A profile version** — the immutable statement of which resource versions, in
  which reference context, with which parameters, an annotation run used.
* **A run** — the application's workflow record for one annotation execution,
  distinct from the job that carried it and from the scientific execution the
  compute subsystem reported.
* **A result version** — what came back, versioned. Nothing is ever overwritten:
  a new resource version produces a new result version and the old one stays
  readable, which is what keeps a historical analysis reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ConflictError, ValidationError
from app.domain.value_objects.enums import (
    AnnotationResourceCategory,
    AnnotationResultState,
    AnnotationRunState,
    AnnotationValueType,
    QueryDefinitionState,
    ScientificResourceState,
    ValidationSeverity,
    ValueSemantics,
)

#: Resource-state transitions the platform allows. Activation is explicit, and a
#: retired or invalidated version is never silently reactivated: the run that used
#: it must keep pointing at the same immutable identity.
_RESOURCE_TRANSITIONS: dict[ScientificResourceState, frozenset[ScientificResourceState]] = {
    ScientificResourceState.REGISTERED: frozenset(
        {
            ScientificResourceState.VALIDATING,
            ScientificResourceState.ACTIVE,
            ScientificResourceState.INVALIDATED,
            ScientificResourceState.RETIRED,
        }
    ),
    ScientificResourceState.VALIDATING: frozenset(
        {
            ScientificResourceState.ACTIVE,
            ScientificResourceState.INVALIDATED,
            ScientificResourceState.RETIRED,
        }
    ),
    ScientificResourceState.ACTIVE: frozenset(
        {
            ScientificResourceState.DEPRECATED,
            ScientificResourceState.RETIRED,
            ScientificResourceState.INVALIDATED,
        }
    ),
    ScientificResourceState.DEPRECATED: frozenset(
        {
            ScientificResourceState.ACTIVE,
            ScientificResourceState.RETIRED,
            ScientificResourceState.INVALIDATED,
        }
    ),
    ScientificResourceState.RETIRED: frozenset(),
    ScientificResourceState.INVALIDATED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class AnnotationFieldSpec:
    """One field a resource version declares it produces.

    This is the schema the platform validates payloads against and the source of
    the filterable annotation fields exposed to Package 7. It describes shape and
    provenance only; it never states what a value means scientifically.
    """

    field_key: str
    label: str
    value_type: AnnotationValueType
    description: str | None = None
    #: Absence markers this field may legitimately carry. Declared, so a reader
    #: can tell "not reported" from zero or false.
    missing_semantics: tuple[ValueSemantics, ...] = (
        ValueSemantics.MISSING,
        ValueSemantics.UNKNOWN,
        ValueSemantics.NA,
    )
    allowed_values: tuple[str, ...] | None = None
    unit: str | None = None
    high_cardinality: bool = False
    filterable: bool = True
    sortable: bool = True
    #: Vocabulary the field belongs to, for display and governance only.
    scientific_category: str | None = None
    #: Column on the produced analytical surface, when the resource declares one.
    column: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.field_key.strip():
            raise ValidationError(
                "an annotation field requires a key", details={"field": "field_key"}
            )

    @property
    def analytical_column(self) -> str:
        return self.column or self.field_key


@dataclass(frozen=True, slots=True)
class AnnotationResourceRecord:
    """One registered version of one annotation resource.

    Identity is ``(resource_key, version)``. Registering a new version never
    mutates an existing one, so a run that named version ``110`` keeps naming it
    after ``111`` is published.
    """

    id: str
    resource_key: str
    version: str
    display_name: str
    category: AnnotationResourceCategory
    state: ScientificResourceState = ScientificResourceState.REGISTERED
    provider: str | None = None
    description: str | None = None
    #: Reference context the resource's values are stated against, when
    #: applicable. A resource with no genome context (e.g. gene-level) leaves it
    #: unset rather than claiming one.
    genome_assembly: str | None = None
    reference_genome_resource_id: str | None = None
    release_label: str | None = None
    released_at: datetime | None = None
    schema_version: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    size_bytes: int | None = None
    fields: tuple[AnnotationFieldSpec, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    licensing: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_by: str | None = None
    activated_at: datetime | None = None
    deprecated_at: datetime | None = None
    retired_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    created_at: datetime | None = None
    record_version: int = 1

    @property
    def is_usable(self) -> bool:
        """Whether a new run may name this version.

        ``deprecated`` stays usable on purpose: deprecation is a recommendation
        against new use, and refusing it outright would strand in-flight work.
        Retired and invalidated versions are refused.
        """
        return self.state in {
            ScientificResourceState.ACTIVE,
            ScientificResourceState.DEPRECATED,
        }

    def field(self, field_key: str) -> AnnotationFieldSpec | None:
        wanted = field_key.strip()
        for specification in self.fields:
            if specification.field_key == wanted:
                return specification
        return None

    def transition_to(
        self, state: ScientificResourceState, *, at: datetime, reason: str | None = None
    ) -> AnnotationResourceRecord:
        if state is self.state:
            return self
        allowed = _RESOURCE_TRANSITIONS.get(self.state, frozenset())
        if state not in allowed:
            raise ConflictError(
                "this annotation resource state transition is not allowed",
                details={"from": self.state.value, "to": state.value},
            )
        stamps: dict[str, Any] = {}
        if state is ScientificResourceState.ACTIVE:
            stamps["activated_at"] = at
        elif state is ScientificResourceState.DEPRECATED:
            stamps["deprecated_at"] = at
        elif state is ScientificResourceState.RETIRED:
            stamps["retired_at"] = at
        elif state is ScientificResourceState.INVALIDATED:
            stamps["invalidated_at"] = at
            stamps["invalidation_reason"] = reason
        return replace(self, state=state, **stamps)


@dataclass(frozen=True, slots=True)
class ProfileResourceBinding:
    """One resource version a profile version pins, by identity and version."""

    resource_id: str
    resource_key: str
    resource_version: str
    category: AnnotationResourceCategory | None = None
    role: str | None = None


@dataclass(frozen=True, slots=True)
class AnnotationProfileRecord:
    """A named annotation execution profile. Platform-governed metadata."""

    id: str
    name: str
    state: QueryDefinitionState = QueryDefinitionState.DRAFT
    description: str | None = None
    latest_version_number: int = 0
    #: Set once any version was used by a run. From then on no existing version
    #: may change, only new ones may be added.
    is_referenced: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime | None = None
    record_version: int = 1

    @property
    def is_offered(self) -> bool:
        return self.state is QueryDefinitionState.PUBLISHED

    def published(self) -> AnnotationProfileRecord:
        if self.latest_version_number < 1:
            raise ConflictError("a profile with no version cannot be published")
        return replace(self, state=QueryDefinitionState.PUBLISHED)

    def archived(self) -> AnnotationProfileRecord:
        return replace(self, state=QueryDefinitionState.ARCHIVED)


@dataclass(frozen=True, slots=True)
class AnnotationProfileVersionRecord:
    """One immutable annotation profile version.

    Everything a run needs in order to be repeatable is frozen here: the pinned
    resource versions, the reference context, the capability the compute
    subsystem is asked for, the parameters, and the digest of that configuration.
    """

    id: str
    profile_id: str
    version_number: int
    capability_id: str
    resources: tuple[ProfileResourceBinding, ...]
    configuration_digest: str
    capability_version: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    genome_assembly: str | None = None
    reference_genome_resource_id: str | None = None
    #: What the run must be given (e.g. ``result_set``, ``dataset_version``).
    required_inputs: tuple[str, ...] = ("result_set",)
    #: Field keys the profile expects back, resolved from the pinned resources.
    output_field_keys: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    #: Provenance the producer must supply for a payload to be accepted.
    provenance_requirements: tuple[str, ...] = ("resource_identity", "engine_identity")
    schema_version: str | None = None
    change_note: str | None = None
    is_referenced: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime | None = None

    def referenced(self) -> AnnotationProfileVersionRecord:
        return replace(self, is_referenced=True)


@dataclass(frozen=True, slots=True)
class AnnotationRunRecord:
    """One annotation run: request, submission, outcome.

    Tenancy comes from the annotated surface, never from the request payload, so
    a run can only ever exist inside the workspace whose data it annotates.
    """

    id: str
    workspace_id: str
    profile_id: str
    profile_version_id: str
    profile_version_number: int
    state: AnnotationRunState = AnnotationRunState.REQUESTED
    project_id: str | None = None
    result_set_id: str | None = None
    dataset_version_id: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    job_id: str | None = None
    scientific_execution_id: str | None = None
    external_execution_id: str | None = None
    capability_id: str | None = None
    capability_version: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    genome_assembly: str | None = None
    #: The configuration frozen at request time: pinned resource versions,
    #: parameters and digest. Editing the profile later cannot change this.
    configuration_snapshot: dict[str, Any] = field(default_factory=dict)
    configuration_digest: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    record_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    record_version: int = 1

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            AnnotationRunState.COMPLETED,
            AnnotationRunState.FAILED,
            AnnotationRunState.CANCELLED,
            AnnotationRunState.REJECTED,
        }

    def submitted(
        self,
        *,
        at: datetime,
        scientific_execution_id: str | None,
        external_execution_id: str | None = None,
    ) -> AnnotationRunRecord:
        return replace(
            self,
            state=AnnotationRunState.SUBMITTED,
            submitted_at=at,
            scientific_execution_id=scientific_execution_id,
            external_execution_id=external_execution_id,
        )

    def running(self) -> AnnotationRunRecord:
        return replace(self, state=AnnotationRunState.RUNNING)

    def ingesting(self) -> AnnotationRunRecord:
        return replace(self, state=AnnotationRunState.INGESTING)

    def completed(self, *, at: datetime, record_count: int | None) -> AnnotationRunRecord:
        return replace(
            self,
            state=AnnotationRunState.COMPLETED,
            completed_at=at,
            record_count=record_count,
        )

    def failed(self, *, at: datetime, code: str, message: str) -> AnnotationRunRecord:
        return replace(
            self,
            state=AnnotationRunState.FAILED,
            completed_at=at,
            failure_code=code,
            failure_message=message,
        )

    def rejected(self, *, at: datetime, code: str, message: str) -> AnnotationRunRecord:
        return replace(
            self,
            state=AnnotationRunState.REJECTED,
            completed_at=at,
            failure_code=code,
            failure_message=message,
        )

    def cancelled(self, *, at: datetime) -> AnnotationRunRecord:
        return replace(self, state=AnnotationRunState.CANCELLED, completed_at=at)


@dataclass(frozen=True, slots=True)
class AnnotationResultVersionRecord:
    """One stored annotation result, versioned per annotated surface.

    ``version_number`` increases per ``(result_set/dataset version, resource
    key)``. An updated resource version therefore adds a version instead of
    replacing one, and every historical version keeps its own provenance.
    """

    id: str
    annotation_run_id: str
    workspace_id: str
    resource_id: str
    resource_key: str
    resource_version: str
    version_number: int
    state: AnnotationResultState = AnnotationResultState.REGISTERED
    project_id: str | None = None
    result_set_id: str | None = None
    dataset_version_id: str | None = None
    profile_version_id: str | None = None
    scientific_execution_id: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    genome_assembly: str | None = None
    #: Large annotation output lives in the analytical layer; this is its address.
    analytical_location: str | None = None
    storage_uri: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    row_count: int | None = None
    #: Inline rows actually written into the durable annotation tables.
    stored_record_count: int = 0
    declared_record_count: int | None = None
    rejected_record_count: int = 0
    field_keys: tuple[str, ...] = ()
    contract_version: str | None = None
    payload_digest: str | None = None
    parameters_digest: str | None = None
    completeness: str | None = None
    is_development_payload: bool = False
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    ingested_at: datetime | None = None
    created_at: datetime | None = None
    record_version: int = 1

    @property
    def is_readable(self) -> bool:
        return self.state in {
            AnnotationResultState.AVAILABLE,
            AnnotationResultState.SUPERSEDED,
        }

    def validated(self) -> AnnotationResultVersionRecord:
        return replace(self, state=AnnotationResultState.VALIDATED)

    def available(self) -> AnnotationResultVersionRecord:
        return replace(self, state=AnnotationResultState.AVAILABLE)

    def rejected(self) -> AnnotationResultVersionRecord:
        return replace(self, state=AnnotationResultState.REJECTED)

    def superseded_by(self, result_id: str) -> AnnotationResultVersionRecord:
        return replace(
            self, state=AnnotationResultState.SUPERSEDED, superseded_by_id=result_id
        )


@dataclass(frozen=True, slots=True)
class AnnotationValidationFinding:
    """One recorded validation observation about an annotation payload.

    Findings are stored, not just raised: a rejected record must remain
    explainable after the request that carried it is gone.
    """

    id: str
    annotation_run_id: str
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    annotation_result_version_id: str | None = None
    field_key: str | None = None
    variant_id: str | None = None
    record_index: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


__all__ = [
    "AnnotationFieldSpec",
    "AnnotationProfileRecord",
    "AnnotationProfileVersionRecord",
    "AnnotationResourceRecord",
    "AnnotationResultVersionRecord",
    "AnnotationRunRecord",
    "AnnotationValidationFinding",
    "ProfileResourceBinding",
]
