"""The filter field dictionary and bounded value search.

Two capabilities, both read-only, both deliberately narrow:

* **Describe the dictionary.** Which fields exist, what type each is, which
  operators it supports, how a missing value behaves, whether it is high
  cardinality. When a result set is named, the answer is additionally restricted
  to the fields that surface actually carries, so a user is never offered a
  condition that cannot apply.
* **Search a field's values.** For genes, transcripts, sample identifiers and
  other high-cardinality fields, the platform never exposes an unbounded distinct
  query. A search term is required to be optional but the result is always
  bounded, always authorized through the result set, and always reports whether it
  was truncated rather than implying completeness.

Nothing here interprets a value. A gene symbol is returned as it is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.query.dependencies import (
    QUERY_EXECUTE,
    QueryServices,
    resolve_workspace_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.query.fields import FilterFieldCategory, FilterFieldDefinition


@dataclass(frozen=True, slots=True)
class DescribeFieldsQuery:
    actor: ActorContext
    request: RequestContext
    #: When present, the dictionary is narrowed to what this surface carries.
    result_set_id: str | None = None
    category: FilterFieldCategory | None = None


@dataclass(frozen=True, slots=True)
class FieldDictionaryView:
    version: str
    fields: tuple[FilterFieldDefinition, ...]
    #: Field identifiers the addressed surface actually provides, when a surface
    #: was named. ``None`` means no surface was named, which is different from a
    #: surface that provides nothing.
    available_field_ids: tuple[str, ...] | None
    result_set_id: str | None = None


class DescribeFilterFields:
    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(self, query: DescribeFieldsQuery) -> FieldDictionaryView:
        registry = self._services.fields
        available: tuple[str, ...] | None = None
        if query.result_set_id is not None:
            location, _ = await _authorized_location(
                self._services, query.actor, query.request, query.result_set_id
            )
            description = await self._services.query_engine.describe(location)
            columns = frozenset(column.name for column in description.columns)
            available = tuple(
                definition.id
                for definition in registry.available_for_columns(columns)
            )
        fields = registry.filterable()
        if query.category is not None:
            fields = tuple(
                definition
                for definition in fields
                if definition.category is query.category
            )
        return FieldDictionaryView(
            version=registry.version,
            fields=fields,
            available_field_ids=available,
            result_set_id=query.result_set_id,
        )


@dataclass(frozen=True, slots=True)
class GetFieldQuery:
    actor: ActorContext
    request: RequestContext
    field_id: str


class GetFilterField:
    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(self, query: GetFieldQuery) -> FilterFieldDefinition:
        definition = self._services.fields.get(query.field_id)
        if definition is None:
            raise NotFoundError("filter_field", query.field_id)
        return definition


@dataclass(frozen=True, slots=True)
class SearchFieldValuesQuery:
    actor: ActorContext
    request: RequestContext
    field_id: str
    result_set_id: str
    search: str | None = None
    limit: int = 50
    #: Occurrence counts cost a full aggregation, so they are opt-in and reported
    #: as absent rather than zero when not requested.
    with_counts: bool = False


@dataclass(frozen=True, slots=True)
class FieldValuesView:
    field_id: str
    result_set_id: str
    values: tuple[dict[str, Any], ...]
    truncated: bool
    field_dictionary_version: str


class SearchFieldValues:
    """Bounded, authorized distinct-value search over one column."""

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(self, query: SearchFieldValuesQuery) -> FieldValuesView:
        definition = self._services.fields.get(query.field_id)
        if definition is None:
            raise NotFoundError("filter_field", query.field_id)
        if not definition.searchable:
            # Not every column is a picker. Refusing is the point: an unbounded
            # distinct scan over a genomic surface is a denial-of-service shape.
            raise ValidationError(
                "this field does not support value search",
                details={"field_id": definition.id},
            )
        location, _ = await _authorized_location(
            self._services, query.actor, query.request, query.result_set_id
        )
        result = await self._services.query_engine.distinct_values(
            location,
            column=definition.column,
            search=query.search,
            limit=max(1, min(query.limit, 200)),
            with_counts=query.with_counts,
        )
        return FieldValuesView(
            field_id=definition.id,
            result_set_id=query.result_set_id,
            values=tuple(
                {"value": entry.value, "occurrence_count": entry.occurrence_count}
                for entry in result.values
            ),
            truncated=result.truncated,
            field_dictionary_version=self._services.fields.version,
        )


async def _authorized_location(
    services: QueryServices,
    actor: ActorContext,
    request: RequestContext,
    result_set_id: str,
) -> tuple[str, Any]:
    """Resolve a readable surface location, or refuse.

    Authorization happens through the result set's own scope, never through the
    identifier the caller supplied, which is what stops a known identifier from
    becoming a read.
    """
    if services.query_engine is None:
        raise ConflictError("analytical querying is not available")
    now = services.clock.now()
    async with services.unit_of_work.begin() as repositories:
        recorder = ActivityRecorder(repositories, request)
        result_set = await repositories.result_sets.get(result_set_id)
        if result_set is None:
            raise NotFoundError("result_set", result_set_id)
        await resolve_workspace_scope(
            services,
            repositories,
            actor,
            workspace_id=result_set.workspace_id,
            project_id=result_set.project_id,
            action=QUERY_EXECUTE,
            recorder=recorder,
            occurred_at=now,
        )
        if not result_set.is_readable:
            raise ConflictError(
                "this result surface is not readable",
                details={"state": result_set.state.value},
            )
        if result_set.analytical_location is None:
            raise ConflictError(
                "this result set has no materialized content to query",
                details={"state": result_set.state.value},
            )
        return result_set.analytical_location, result_set


__all__ = [
    "DescribeFieldsQuery",
    "DescribeFilterFields",
    "FieldDictionaryView",
    "FieldValuesView",
    "GetFieldQuery",
    "GetFilterField",
    "SearchFieldValues",
    "SearchFieldValuesQuery",
]
