"""Transport schemas for filtering, ranking and saved views.

Three conventions are load-bearing here:

* **A filter is structured data, never text.** Every expression crosses the
  boundary as a nested object of conditions and groups. There is no field
  anywhere in this module that accepts SQL, an expression language or anything
  else that could be executed.
* **Filtering and ranking are separate payloads.** A request may carry both, but
  neither can reach into the other: a ranking body cannot narrow a result set and
  a filter body cannot produce a score.
* **Nothing is optional by omission.** ``extra="forbid"`` is inherited from
  ``ApiModel``, so a misspelled key is a validation error rather than a silently
  ignored instruction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.api.v1.schemas.common import ApiModel
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Field dictionary                                                            #
# --------------------------------------------------------------------------- #


class FilterFieldResponse(ApiModel):
    id: str
    label: str
    description: str
    data_type: str
    category: str
    origin: str
    supported_operators: list[str]
    nullable: bool
    missing_semantics: list[str]
    allowed_values: list[str] | None = None
    high_cardinality: bool
    searchable: bool
    sortable: bool
    filterable: bool
    scientific_category: str | None = None
    requires_context: list[str]
    version: str
    available: bool


class FieldDictionaryResponse(ApiModel):
    version: str
    fields: list[FilterFieldResponse]
    result_set_id: str | None = None
    available_field_ids: list[str] | None = Field(
        default=None,
        description=(
            "Fields the addressed surface actually carries. Null means no surface "
            "was named, which is not the same as a surface carrying nothing."
        ),
    )


class FieldValueResponse(ApiModel):
    value: Any = None
    count: int | None = Field(
        default=None,
        description="Occurrence count when counts were requested; null otherwise.",
    )


class FieldValuesResponse(ApiModel):
    field_id: str
    result_set_id: str
    values: list[FieldValueResponse]
    truncated: bool = Field(
        description="True when more distinct values exist than the bounded page returned."
    )
    field_dictionary_version: str


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


class FilterValidationPayload(ApiModel):
    expression: dict[str, Any] = Field(
        description="A filter group: nested conditions and AND/OR/NOT groups."
    )


class FilterValidationIssueResponse(ApiModel):
    path: str
    message: str
    code: str | None = None
    field_id: str | None = None
    detail: dict[str, Any] | None = None


class FilterValidationResponse(ApiModel):
    valid: bool
    canonical: dict[str, Any] | None = None
    canonical_hash: str | None = None
    field_dictionary_version: str
    condition_count: int
    depth: int
    field_ids: list[str]
    issues: list[FilterValidationIssueResponse]


# --------------------------------------------------------------------------- #
# Configuration lifecycle (saved filters, presets, rankings, ranking presets)  #
# --------------------------------------------------------------------------- #


class ConfigurationCreatePayload(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    scope: str = Field(description="platform, organization, project or personal.")
    content: dict[str, Any] = Field(
        description="Filter expression or ranking configuration, validated server-side."
    )
    description: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    applicable_contexts: list[str] | None = None
    change_note: str | None = None
    publish: bool = True


class ConfigurationMetadataPayload(ApiModel):
    expected_version: int = Field(
        ge=1, description="Concurrency guard; a stale value is rejected, never merged."
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ConfigurationVersionPayload(ApiModel):
    expected_version: int = Field(ge=1)
    content: dict[str, Any]
    change_note: str | None = None


class ConfigurationLifecyclePayload(ApiModel):
    expected_version: int = Field(ge=1)


class ConfigurationVersionResponse(ApiModel):
    id: str
    definition_id: str
    version_number: int
    canonical: dict[str, Any]
    canonical_hash: str
    field_dictionary_version: str
    required_field_ids: list[str]
    change_note: str | None = None
    is_referenced: bool
    created_by: str
    created_at: datetime
    condition_count: int | None = None
    depth: int | None = None
    method_id: str | None = None
    method_version: str | None = None
    component_count: int | None = None


class ConfigurationResponse(ApiModel):
    id: str
    name: str
    description: str | None = None
    scope: str
    state: str
    deletion_state: str
    owner_user_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    latest_version_number: int
    is_referenced: bool
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    applicable_contexts: list[str] | None = None
    method_id: str | None = None
    capabilities: list[str] = Field(
        default_factory=list,
        description="Server-granted actions. The UI enables controls from these only.",
    )
    latest_version: ConfigurationVersionResponse | None = None


class ConfigurationCollection(ApiModel):
    items: list[ConfigurationResponse]
    page: PageMeta


class ConfigurationVersionCollection(ApiModel):
    items: list[ConfigurationVersionResponse]


# --------------------------------------------------------------------------- #
# Ranking methods                                                             #
# --------------------------------------------------------------------------- #


class RankingMethodResponse(ApiModel):
    id: str
    name: str
    description: str
    version: str
    implementation_id: str
    supported_component_kinds: list[str]
    requires_components: bool
    min_components: int
    max_components: int
    supported_parameters: list[str]
    supported_contexts: list[str]
    deterministic: bool
    available: bool
    scientifically_validated: bool = Field(
        description=(
            "False for every shipped method: these produce a transparent "
            "prioritization score, not a validated scientific conclusion."
        )
    )


class RankingMethodCollection(ApiModel):
    items: list[RankingMethodResponse]


# --------------------------------------------------------------------------- #
# Variant query                                                               #
# --------------------------------------------------------------------------- #


class FilterSelectionPayload(ApiModel):
    expression: dict[str, Any] | None = None
    filter_definition_id: str | None = None
    filter_version_number: int | None = Field(default=None, ge=1)
    filter_preset_id: str | None = None
    filter_preset_version_number: int | None = Field(default=None, ge=1)


class RankingSelectionPayload(ApiModel):
    configuration: dict[str, Any] | None = None
    ranking_definition_id: str | None = None
    ranking_version_number: int | None = Field(default=None, ge=1)
    ranking_preset_id: str | None = None
    ranking_preset_version_number: int | None = Field(default=None, ge=1)


class VariantQueryPayload(ApiModel):
    result_set_id: str
    filter: FilterSelectionPayload | None = None
    ranking: RankingSelectionPayload | None = None
    field_ids: list[str] | None = None
    page_size: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
    sort_field_id: str | None = Field(
        default=None,
        description="Table sort. Ignored when a ranking is active; sorting is not ranking.",
    )
    sort_descending: bool = False
    include_total: bool = False


class FilterExecutionResponse(ApiModel):
    id: str
    result_set_id: str
    effective_canonical: dict[str, Any]
    effective_hash: str
    field_dictionary_version: str
    outcome: str
    filter_definition_id: str | None = None
    filter_version_number: int | None = None
    filter_preset_id: str | None = None
    filter_preset_version_number: int | None = None
    custom_canonical: dict[str, Any] | None = None
    returned_count: int
    total_count: int | None = None
    page_size: int
    duration_ms: int | None = None
    software_version: str | None = None
    executed_at: datetime
    executed_by: str


class RankingExecutionResponse(ApiModel):
    id: str
    filter_execution_id: str
    method_id: str
    method_version: str
    method_implementation_id: str
    effective_canonical: dict[str, Any]
    effective_hash: str
    direction: str
    tie_breakers: list[str]
    outcome: str
    ranking_definition_id: str | None = None
    ranking_version_number: int | None = None
    ranking_preset_id: str | None = None
    ranking_preset_version_number: int | None = None
    scored_count: int
    unscored_count: int = Field(
        description="Rows no component could score. A data fact, not a low priority."
    )
    duration_ms: int | None = None
    executed_at: datetime


class VariantQueryResponse(ApiModel):
    result_set_id: str
    columns: list[str]
    field_ids: list[str]
    rows: list[dict[str, Any]]
    returned_count: int
    total_count: int | None = None
    next_cursor: str | None = None
    execution: FilterExecutionResponse
    ranking_execution: RankingExecutionResponse | None = None
    ranking_window_exceeded: bool = False
    ranking_window_rows: int | None = None


class DeferredQueryPayload(ApiModel):
    result_set_id: str
    filter: FilterSelectionPayload | None = None
    ranking: RankingSelectionPayload | None = None
    field_ids: list[str] | None = None
    sort_field_id: str | None = None
    sort_descending: bool = False
    max_rows: int | None = Field(default=None, ge=1)
    context: dict[str, Any] | None = None


class DeferredQueryResponse(ApiModel):
    job_id: str
    result_set_id: str
    effective_hash: str
    field_dictionary_version: str
    max_rows: int


# --------------------------------------------------------------------------- #
# Saved views                                                                 #
# --------------------------------------------------------------------------- #


class SavedViewCreatePayload(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    scope: str
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    description: str | None = None
    columns: list[str] | None = None
    pinned_columns: list[str] | None = None
    column_widths: dict[str, int] | None = None
    sort_field_id: str | None = None
    sort_descending: bool = False
    page_size: int = Field(default=50, ge=1, le=200)
    default_filter_definition_id: str | None = None
    default_filter_preset_id: str | None = None
    default_ranking_definition_id: str | None = None
    default_ranking_preset_id: str | None = None


class SavedViewUpdatePayload(ApiModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    columns: list[str] | None = None
    pinned_columns: list[str] | None = None
    column_widths: dict[str, int] | None = None
    sort_field_id: str | None = None
    sort_descending: bool | None = None
    page_size: int | None = Field(default=None, ge=1, le=200)
    default_filter_definition_id: str | None = None
    default_filter_preset_id: str | None = None
    default_ranking_definition_id: str | None = None
    default_ranking_preset_id: str | None = None


class SavedViewResponse(ApiModel):
    id: str
    name: str
    description: str | None = None
    scope: str
    owner_user_id: str
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    columns: list[str]
    pinned_columns: list[str]
    column_widths: dict[str, int]
    sort_field_id: str | None = None
    sort_descending: bool
    page_size: int
    default_filter_definition_id: str | None = None
    default_filter_preset_id: str | None = None
    default_ranking_definition_id: str | None = None
    default_ranking_preset_id: str | None = None
    deletion_state: str
    version: int
    created_at: datetime
    updated_at: datetime
    capabilities: list[str] = Field(default_factory=list)


class SavedViewCollection(ApiModel):
    items: list[SavedViewResponse]
    page: PageMeta


# --------------------------------------------------------------------------- #
# Administration                                                              #
# --------------------------------------------------------------------------- #


class QueryLimitsResponse(ApiModel):
    """The configured safety limits, so a client can stay inside them."""

    field_dictionary_version: str
    max_conditions: int
    max_depth: int
    max_values_per_condition: int
    max_value_length: int
    max_expression_bytes: int
    max_text_match_conditions: int
    max_page_size: int
    software_version: str


__all__ = [
    "ConfigurationCollection",
    "ConfigurationCreatePayload",
    "ConfigurationLifecyclePayload",
    "ConfigurationMetadataPayload",
    "ConfigurationResponse",
    "ConfigurationVersionCollection",
    "ConfigurationVersionPayload",
    "ConfigurationVersionResponse",
    "DeferredQueryPayload",
    "DeferredQueryResponse",
    "FieldDictionaryResponse",
    "FieldValueResponse",
    "FieldValuesResponse",
    "FilterExecutionResponse",
    "FilterFieldResponse",
    "FilterSelectionPayload",
    "FilterValidationIssueResponse",
    "FilterValidationPayload",
    "FilterValidationResponse",
    "QueryLimitsResponse",
    "RankingExecutionResponse",
    "RankingMethodCollection",
    "RankingMethodResponse",
    "RankingSelectionPayload",
    "SavedViewCollection",
    "SavedViewCreatePayload",
    "SavedViewResponse",
    "SavedViewUpdatePayload",
    "VariantQueryPayload",
    "VariantQueryResponse",
]
