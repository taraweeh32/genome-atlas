"""Shaping filtering, ranking and view results for transport.

Mapping only. Nothing here decides access, and nothing here computes a value the
application layer did not already produce — in particular no count is invented
and no absent value is turned into a zero: a field the surface never reported is
returned as null, because "not reported" and "zero" are different facts.
"""

from __future__ import annotations

from typing import Any

from app.api.v1.schemas.query import (
    ConfigurationResponse,
    ConfigurationVersionResponse,
    FieldDictionaryResponse,
    FieldValueResponse,
    FieldValuesResponse,
    FilterExecutionResponse,
    FilterFieldResponse,
    FilterValidationIssueResponse,
    FilterValidationResponse,
    QueryLimitsResponse,
    RankingExecutionResponse,
    RankingMethodResponse,
    SavedViewResponse,
    VariantQueryResponse,
)
from app.domain.query.fields import FilterFieldDefinition
from app.domain.query.ranking import RankingMethodDefinition


def filter_field_response(definition: FilterFieldDefinition) -> FilterFieldResponse:
    return FilterFieldResponse(
        id=definition.id,
        label=definition.label,
        description=definition.description,
        data_type=definition.data_type.value,
        category=definition.category.value,
        origin=definition.origin.value,
        supported_operators=[
            operator.value for operator in definition.supported_operators
        ],
        nullable=definition.nullable,
        missing_semantics=[item.value for item in definition.missing_semantics],
        allowed_values=(
            list(definition.allowed_values)
            if definition.allowed_values is not None
            else None
        ),
        high_cardinality=definition.high_cardinality,
        searchable=definition.searchable,
        sortable=definition.sortable,
        filterable=definition.filterable,
        scientific_category=definition.scientific_category,
        requires_context=list(definition.requires_context),
        version=definition.version,
        available=definition.available,
    )


def field_dictionary_response(view: Any) -> FieldDictionaryResponse:
    return FieldDictionaryResponse(
        version=view.version,
        fields=[filter_field_response(item) for item in view.fields],
        result_set_id=view.result_set_id,
        available_field_ids=(
            list(view.available_field_ids)
            if view.available_field_ids is not None
            else None
        ),
    )


def field_values_response(view: Any) -> FieldValuesResponse:
    return FieldValuesResponse(
        field_id=view.field_id,
        result_set_id=view.result_set_id,
        values=[
            FieldValueResponse(
                value=item.get("value"), count=item.get("occurrence_count")
            )
            for item in view.values
        ],
        truncated=view.truncated,
        field_dictionary_version=view.field_dictionary_version,
    )


def filter_validation_response(view: Any) -> FilterValidationResponse:
    return FilterValidationResponse(
        valid=view.valid,
        canonical=view.canonical,
        canonical_hash=view.canonical_hash,
        field_dictionary_version=view.field_dictionary_version,
        condition_count=view.condition_count,
        depth=view.depth,
        field_ids=list(view.field_ids),
        issues=[
            FilterValidationIssueResponse(
                path=str(issue.get("path", "$")),
                message=str(issue.get("message", "")),
                code=issue.get("code"),
                field_id=issue.get("field_id"),
                detail=issue.get("detail"),
            )
            for issue in view.issues
        ],
    )


def configuration_version_response(version: Any) -> ConfigurationVersionResponse:
    return ConfigurationVersionResponse(
        id=version.id,
        definition_id=version.definition_id,
        version_number=version.version_number,
        canonical=version.canonical,
        canonical_hash=version.canonical_hash,
        field_dictionary_version=version.field_dictionary_version,
        required_field_ids=list(version.required_field_ids),
        change_note=version.change_note,
        is_referenced=version.is_referenced,
        created_by=version.created_by,
        created_at=version.created_at,
        condition_count=getattr(version, "condition_count", None),
        depth=getattr(version, "depth", None),
        method_id=getattr(version, "method_id", None) or None,
        method_version=getattr(version, "method_version", None) or None,
        component_count=getattr(version, "component_count", None),
    )


def configuration_response(
    definition: Any,
    *,
    latest_version: Any | None = None,
    capabilities: tuple[str, ...] = (),
) -> ConfigurationResponse:
    contexts = getattr(definition, "applicable_contexts", None)
    return ConfigurationResponse(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        scope=definition.scope.value,
        state=definition.state.value,
        deletion_state=definition.deletion_state.value,
        owner_user_id=definition.owner_user_id,
        workspace_id=definition.workspace_id,
        project_id=definition.project_id,
        organization_id=definition.organization_id,
        latest_version_number=definition.latest_version_number,
        is_referenced=definition.is_referenced,
        version=definition.version,
        created_by=definition.created_by,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
        applicable_contexts=list(contexts) if contexts is not None else None,
        method_id=getattr(definition, "method_id", None) or None,
        capabilities=list(capabilities),
        latest_version=(
            configuration_version_response(latest_version)
            if latest_version is not None
            else None
        ),
    )


def configuration_view_response(view: Any) -> ConfigurationResponse:
    return configuration_response(
        view.definition,
        latest_version=view.latest_version,
        capabilities=view.capabilities,
    )


def ranking_method_response(method: RankingMethodDefinition) -> RankingMethodResponse:
    return RankingMethodResponse(
        id=method.id,
        name=method.name,
        description=method.description,
        version=method.version,
        implementation_id=method.implementation_id,
        supported_component_kinds=[
            kind.value for kind in method.supported_component_kinds
        ],
        requires_components=method.requires_components,
        min_components=method.min_components,
        max_components=method.max_components,
        supported_parameters=list(method.supported_parameters),
        supported_contexts=list(method.supported_contexts),
        deterministic=method.deterministic,
        available=method.available,
        scientifically_validated=method.scientifically_validated,
    )


def filter_execution_response(record: Any) -> FilterExecutionResponse:
    return FilterExecutionResponse(
        id=record.id,
        result_set_id=record.result_set_id,
        effective_canonical=record.effective_canonical,
        effective_hash=record.effective_hash,
        field_dictionary_version=record.field_dictionary_version,
        outcome=record.outcome.value,
        filter_definition_id=record.filter_definition_id,
        filter_version_number=record.filter_version_number,
        filter_preset_id=record.filter_preset_id,
        filter_preset_version_number=record.filter_preset_version_number,
        custom_canonical=record.custom_canonical,
        returned_count=record.returned_count,
        total_count=record.total_count,
        page_size=record.page_size,
        duration_ms=record.duration_ms,
        software_version=record.software_version,
        executed_at=record.executed_at,
        executed_by=record.executed_by,
    )


def ranking_execution_response(record: Any) -> RankingExecutionResponse:
    return RankingExecutionResponse(
        id=record.id,
        filter_execution_id=record.filter_execution_id,
        method_id=record.method_id,
        method_version=record.method_version,
        method_implementation_id=record.method_implementation_id,
        effective_canonical=record.effective_canonical,
        effective_hash=record.effective_hash,
        direction=record.direction,
        tie_breakers=list(record.tie_breakers),
        outcome=record.outcome.value,
        ranking_definition_id=record.ranking_definition_id,
        ranking_version_number=record.ranking_version_number,
        ranking_preset_id=record.ranking_preset_id,
        ranking_preset_version_number=record.ranking_preset_version_number,
        scored_count=record.scored_count,
        unscored_count=record.unscored_count,
        duration_ms=record.duration_ms,
        executed_at=record.executed_at,
    )


def variant_query_response(page: Any) -> VariantQueryResponse:
    return VariantQueryResponse(
        result_set_id=page.result_set_id,
        columns=list(page.columns),
        field_ids=list(page.field_ids),
        rows=[dict(row) for row in page.rows],
        returned_count=page.returned_count,
        total_count=page.total_count,
        next_cursor=page.next_cursor,
        execution=filter_execution_response(page.execution),
        ranking_execution=(
            ranking_execution_response(page.ranking_execution)
            if page.ranking_execution is not None
            else None
        ),
        ranking_window_exceeded=page.ranking_window_exceeded,
        ranking_window_rows=page.ranking_window_rows,
    )


def saved_view_response(
    view: Any, *, capabilities: tuple[str, ...] = ()
) -> SavedViewResponse:
    record = getattr(view, "view", view)
    granted = getattr(view, "capabilities", capabilities)
    return SavedViewResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        scope=record.scope.value,
        owner_user_id=record.owner_user_id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        organization_id=record.organization_id,
        columns=list(record.columns),
        pinned_columns=list(record.pinned_columns),
        column_widths=dict(record.column_widths),
        sort_field_id=record.sort_field_id,
        sort_descending=record.sort_descending,
        page_size=record.page_size,
        default_filter_definition_id=record.default_filter_definition_id,
        default_filter_preset_id=record.default_filter_preset_id,
        default_ranking_definition_id=record.default_ranking_definition_id,
        default_ranking_preset_id=record.default_ranking_preset_id,
        deletion_state=record.deletion_state.value,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        capabilities=list(granted),
    )


def query_limits_response(services: Any) -> QueryLimitsResponse:
    limits = services.limits
    return QueryLimitsResponse(
        field_dictionary_version=services.fields.version,
        max_conditions=limits.max_conditions,
        max_depth=limits.max_depth,
        max_values_per_condition=limits.max_values_per_condition,
        max_value_length=limits.max_value_length,
        max_expression_bytes=limits.max_expression_bytes,
        max_text_match_conditions=limits.max_text_match_conditions,
        max_page_size=services.max_page_size,
        software_version=services.software_version,
    )


__all__ = [
    "configuration_response",
    "configuration_version_response",
    "configuration_view_response",
    "field_dictionary_response",
    "field_values_response",
    "filter_execution_response",
    "filter_field_response",
    "filter_validation_response",
    "query_limits_response",
    "ranking_execution_response",
    "ranking_method_response",
    "saved_view_response",
    "variant_query_response",
]
