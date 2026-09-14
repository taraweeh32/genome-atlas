"""Persistence for saved filters, presets, ranking configurations, views and
query executions.

Three properties are enforced by the statements themselves rather than by
convention:

* **Definition metadata is version-checked.** Renaming, publishing or archiving a
  definition uses ``UPDATE ... WHERE version = :expected``, so two concurrent
  editors cannot silently overwrite one another — the loser is told to re-read.
* **Content is append-only.** There is no UPDATE against any ``*_versions`` table.
  Editing a saved filter inserts the next version; the previous rows stay exactly
  as an execution referenced them. The only mutation permitted is flipping
  ``is_referenced`` to true, which records a fact and never alters content.
* **Reads are scope-explicit.** Every listing takes the caller's authorized scopes
  and turns them into a WHERE clause over the ownership columns. A caller with no
  memberships sees platform-scoped configurations and nothing else; there is no
  code path that lists "all" configurations for a tenant caller.

Filter and ranking rows never contain variant data. They contain the *question*;
the answer lives in Parquet and is read through DuckDB.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy import Select, insert, or_, select, update

from app.application.repositories import Page, Paged, QueryScopeFilter
from app.domain.query.entities import (
    FilterDefinitionRecord,
    FilterExecutionRecord,
    FilterPresetRecord,
    FilterPresetVersionRecord,
    FilterVersionRecord,
    RankingDefinitionRecord,
    RankingExecutionRecord,
    RankingPresetRecord,
    RankingPresetVersionRecord,
    RankingVersionRecord,
    SavedViewRecord,
)
from app.domain.value_objects.enums import (
    DeletionState,
    QueryDefinitionState,
    QueryExecutionOutcome,
    QueryScope,
)
from app.infrastructure.persistence.models.queries import (
    FilterExecution,
    FilterPreset,
    FilterPresetVersion,
    RankingExecution,
    RankingPreset,
    RankingPresetVersion,
)
from app.infrastructure.persistence.models.results import (
    FilterDefinition,
    FilterDefinitionVersion,
    RankingConfiguration,
    RankingConfigurationVersion,
    SavedView,
)
from app.infrastructure.persistence.repositories.base import SqlRepository

_FILTERS = FilterDefinition.__table__
_FILTER_VERSIONS = FilterDefinitionVersion.__table__
_FILTER_PRESETS = FilterPreset.__table__
_FILTER_PRESET_VERSIONS = FilterPresetVersion.__table__
_RANKINGS = RankingConfiguration.__table__
_RANKING_VERSIONS = RankingConfigurationVersion.__table__
_RANKING_PRESETS = RankingPreset.__table__
_RANKING_PRESET_VERSIONS = RankingPresetVersion.__table__
_FILTER_EXECUTIONS = FilterExecution.__table__
_RANKING_EXECUTIONS = RankingExecution.__table__
_SAVED_VIEWS = SavedView.__table__


def _scope_id(record: Any) -> str | None:
    """The single identifier a scope is confined by.

    Stored redundantly alongside the typed ownership columns because the
    uniqueness of a name is per scope context: two projects may both have a
    "Rare disease" filter, and a unique constraint needs one column to say so.
    """
    scope = record.scope
    if scope is QueryScope.PLATFORM:
        return None
    if scope is QueryScope.ORGANIZATION:
        return record.organization_id
    if scope is QueryScope.PROJECT:
        return record.project_id
    return record.owner_user_id


def _definition_values(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "scope": record.scope.value,
        "state": record.state.value,
        "scope_id": _scope_id(record),
        "owner_user_id": record.owner_user_id,
        "workspace_id": record.workspace_id,
        "project_id": record.project_id,
        "organization_id": record.organization_id,
        "latest_version_number": record.latest_version_number,
        "is_referenced": record.is_referenced,
        "deletion_state": record.deletion_state.value,
        "deleted_at": record.deleted_at,
        "metadata_json": dict(record.metadata),
        "created_by": record.created_by,
        "updated_by": record.created_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "version": record.version,
    }


def _definition_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "scope": QueryScope(row["scope"]),
        "state": QueryDefinitionState(row["state"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "description": row["description"],
        "owner_user_id": row["owner_user_id"],
        "workspace_id": row["workspace_id"],
        "project_id": row["project_id"],
        "organization_id": row["organization_id"],
        "latest_version_number": row["latest_version_number"],
        "is_referenced": row["is_referenced"],
        "deletion_state": DeletionState(row["deletion_state"]),
        "deleted_at": row["deleted_at"],
        "metadata": dict(row["metadata_json"] or {}),
    }


def _version_fields(row: Mapping[str, Any], *, definition_key: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "definition_id": row[definition_key],
        "version_number": row["version_number"],
        "canonical_hash": row["canonical_hash"] or "",
        "field_dictionary_version": row["field_dictionary_version"] or "",
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "required_field_ids": tuple(row["required_field_ids"] or ()),
        "change_note": row["change_note"],
        "is_referenced": row["is_referenced"],
        "metadata": dict(row["metadata_json"] or {}),
    }


def _version_values(record: Any, *, definition_key: str) -> dict[str, Any]:
    return {
        "id": record.id,
        definition_key: record.definition_id,
        "version_number": record.version_number,
        "canonical_hash": record.canonical_hash,
        "field_dictionary_version": record.field_dictionary_version,
        "required_field_ids": list(record.required_field_ids),
        "change_note": record.change_note,
        "is_referenced": record.is_referenced,
        "metadata_json": dict(record.metadata),
        "created_by": record.created_by,
        "created_at": record.created_at,
    }


def _scope_clause(table, scopes: QueryScopeFilter):
    """Turn authorized scopes into a WHERE clause over ownership columns.

    Every branch is keyed by an identifier the caller was authorized for, so a
    configuration belonging to an unrelated tenant is not merely hidden from a
    response — it is never selected.
    """
    clauses = []
    if scopes.include_platform:
        clauses.append(table.c.scope == QueryScope.PLATFORM.value)
    if scopes.user_id:
        clauses.append(
            (table.c.scope == QueryScope.PERSONAL.value)
            & (table.c.owner_user_id == scopes.user_id)
        )
    if scopes.project_ids:
        clauses.append(
            (table.c.scope == QueryScope.PROJECT.value)
            & table.c.project_id.in_(scopes.project_ids)
        )
    if scopes.organization_ids:
        clauses.append(
            (table.c.scope == QueryScope.ORGANIZATION.value)
            & table.c.organization_id.in_(scopes.organization_ids)
        )
    if not clauses:
        # Nothing was authorized. Fail closed with a predicate that matches no row
        # rather than omitting the clause entirely.
        return table.c.id.is_(None)
    return or_(*clauses)


class _DefinitionRepository(SqlRepository):
    """Shared behaviour for the four definition/version table pairs.

    One implementation, four bindings: a saved filter and a ranking preset are
    governed identically even though what they contain has nothing in common.
    Sharing the *governance* code while keeping the ports separate is what keeps
    filtering and ranking independent without duplicating lifecycle logic.
    """

    _table: Any
    _versions: Any
    _definition_key: str
    _record: Any
    _version_record: Any

    def _to_record(self, row: Mapping[str, Any]) -> Any:
        raise NotImplementedError

    def _to_version(self, row: Mapping[str, Any]) -> Any:
        raise NotImplementedError

    def _extra_values(self, record: Any) -> dict[str, Any]:
        return {}

    def _extra_version_values(self, record: Any) -> dict[str, Any]:
        return {}

    async def add(self, definition: Any) -> Any:
        values = _definition_values(definition) | self._extra_values(definition)
        await self._session.execute(insert(self._table).values(**values))
        return definition

    async def get(self, definition_id: str) -> Any | None:
        row = await self._fetch_one(
            select(self._table).where(self._table.c.id == definition_id)
        )
        return self._to_record(row) if row else None

    async def save(self, definition: Any) -> Any:
        values = _definition_values(definition) | self._extra_values(definition)
        for key in ("id", "created_at", "created_by", "version"):
            values.pop(key, None)
        next_version = await self._versioned_update(
            self._table,
            entity_id=definition.id,
            expected_version=definition.version,
            values=values,
        )
        return replace(definition, version=next_version)

    async def add_version(self, version: Any) -> Any:
        values = _version_values(
            version, definition_key=self._definition_key
        ) | self._extra_version_values(version)
        await self._session.execute(insert(self._versions).values(**values))
        return version

    async def get_version(self, version_id: str) -> Any | None:
        row = await self._fetch_one(
            select(self._versions).where(self._versions.c.id == version_id)
        )
        return self._to_version(row) if row else None

    async def find_version(self, *, definition_id: str, version_number: int) -> Any | None:
        row = await self._fetch_one(
            select(self._versions).where(
                self._versions.c[self._definition_key] == definition_id,
                self._versions.c.version_number == version_number,
            )
        )
        return self._to_version(row) if row else None

    async def latest_version(self, definition_id: str) -> Any | None:
        row = await self._fetch_one(
            select(self._versions)
            .where(self._versions.c[self._definition_key] == definition_id)
            .order_by(self._versions.c.version_number.desc())
            .limit(1)
        )
        return self._to_version(row) if row else None

    async def list_versions(self, definition_id: str) -> tuple[Any, ...]:
        rows = await self._fetch_all(
            select(self._versions)
            .where(self._versions.c[self._definition_key] == definition_id)
            .order_by(self._versions.c.version_number.asc())
        )
        return tuple(self._to_version(row) for row in rows)

    async def mark_version_referenced(self, version_id: str) -> None:
        """Record that an execution froze this version. Content is untouched."""
        await self._session.execute(
            update(self._versions)
            .where(self._versions.c.id == version_id)
            .values(is_referenced=True)
        )

    async def list_for_scope(self, *, scopes: QueryScopeFilter, page: Page) -> Paged[Any]:
        statement: Select = (
            select(self._table)
            .where(
                _scope_clause(self._table, scopes),
                self._table.c.deletion_state == DeletionState.ACTIVE.value,
            )
            .order_by(self._table.c.name.asc(), self._table.c.id.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(
            items=tuple(self._to_record(row) for row in rows), total=total, page=page
        )


class SqlFilterDefinitionRepository(_DefinitionRepository):
    _table = _FILTERS
    _versions = _FILTER_VERSIONS
    _definition_key = "filter_definition_id"

    def _to_record(self, row: Mapping[str, Any]) -> FilterDefinitionRecord:
        return FilterDefinitionRecord(**_definition_fields(row))

    def _to_version(self, row: Mapping[str, Any]) -> FilterVersionRecord:
        return FilterVersionRecord(
            **_version_fields(row, definition_key=self._definition_key),
            canonical=dict(row["predicate_tree"] or {}),
            condition_count=row["condition_count"],
            depth=row["depth"],
        )

    def _extra_values(self, record: FilterDefinitionRecord) -> dict[str, Any]:
        return {"is_preset": False, "current_version_number": record.latest_version_number}

    def _extra_version_values(self, record: FilterVersionRecord) -> dict[str, Any]:
        return {
            "predicate_tree": dict(record.canonical),
            "condition_count": record.condition_count,
            "depth": record.depth,
        }


class SqlFilterPresetRepository(_DefinitionRepository):
    _table = _FILTER_PRESETS
    _versions = _FILTER_PRESET_VERSIONS
    _definition_key = "filter_preset_id"

    def _to_record(self, row: Mapping[str, Any]) -> FilterPresetRecord:
        return FilterPresetRecord(
            **_definition_fields(row),
            applicable_contexts=tuple(row["applicable_contexts"] or ()),
        )

    def _to_version(self, row: Mapping[str, Any]) -> FilterPresetVersionRecord:
        return FilterPresetVersionRecord(
            **_version_fields(row, definition_key=self._definition_key),
            canonical=dict(row["canonical"] or {}),
            condition_count=row["condition_count"],
            depth=row["depth"],
        )

    def _extra_values(self, record: FilterPresetRecord) -> dict[str, Any]:
        return {"applicable_contexts": list(record.applicable_contexts)}

    def _extra_version_values(self, record: FilterPresetVersionRecord) -> dict[str, Any]:
        return {
            "canonical": dict(record.canonical),
            "condition_count": record.condition_count,
            "depth": record.depth,
        }


class SqlRankingDefinitionRepository(_DefinitionRepository):
    _table = _RANKINGS
    _versions = _RANKING_VERSIONS
    _definition_key = "ranking_configuration_id"

    def _to_record(self, row: Mapping[str, Any]) -> RankingDefinitionRecord:
        return RankingDefinitionRecord(
            **_definition_fields(row), method_id=row["method_key"]
        )

    def _to_version(self, row: Mapping[str, Any]) -> RankingVersionRecord:
        return RankingVersionRecord(
            **_version_fields(row, definition_key=self._definition_key),
            canonical=dict(row["canonical"] or {}),
            method_id=row["method_key"],
            method_version=row["method_version"] or "",
            component_count=row["component_count"],
        )

    def _extra_values(self, record: RankingDefinitionRecord) -> dict[str, Any]:
        return {
            "method_key": record.method_id,
            "is_preset": False,
            "current_version_number": record.latest_version_number,
        }

    def _extra_version_values(self, record: RankingVersionRecord) -> dict[str, Any]:
        return {
            "canonical": dict(record.canonical),
            "method_key": record.method_id,
            "method_version": record.method_version,
            "component_count": record.component_count,
        }


class SqlRankingPresetRepository(_DefinitionRepository):
    _table = _RANKING_PRESETS
    _versions = _RANKING_PRESET_VERSIONS
    _definition_key = "ranking_preset_id"

    def _to_record(self, row: Mapping[str, Any]) -> RankingPresetRecord:
        return RankingPresetRecord(
            **_definition_fields(row),
            method_id=row["method_id"],
            applicable_contexts=tuple(row["applicable_contexts"] or ()),
        )

    def _to_version(self, row: Mapping[str, Any]) -> RankingPresetVersionRecord:
        return RankingPresetVersionRecord(
            **_version_fields(row, definition_key=self._definition_key),
            canonical=dict(row["canonical"] or {}),
            method_id=row["method_id"],
            method_version=row["method_version"],
            component_count=row["component_count"],
        )

    def _extra_values(self, record: RankingPresetRecord) -> dict[str, Any]:
        return {
            "method_id": record.method_id,
            "applicable_contexts": list(record.applicable_contexts),
        }

    def _extra_version_values(self, record: RankingPresetVersionRecord) -> dict[str, Any]:
        return {
            "canonical": dict(record.canonical),
            "method_id": record.method_id,
            "method_version": record.method_version,
            "component_count": record.component_count,
        }


class SqlQueryExecutionRepository(SqlRepository):
    """Append-only execution history. No update statement exists here."""

    async def add_filter_execution(
        self, execution: FilterExecutionRecord
    ) -> FilterExecutionRecord:
        await self._session.execute(
            insert(_FILTER_EXECUTIONS).values(
                id=execution.id,
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                executed_by=execution.executed_by,
                executed_at=execution.executed_at,
                result_set_id=execution.result_set_id,
                dataset_version_id=execution.dataset_version_id,
                analysis_execution_id=execution.analysis_execution_id,
                effective_canonical=dict(execution.effective_canonical),
                effective_hash=execution.effective_hash,
                field_dictionary_version=execution.field_dictionary_version,
                outcome=execution.outcome.value,
                filter_definition_id=execution.filter_definition_id,
                filter_version_id=execution.filter_version_id,
                filter_version_number=execution.filter_version_number,
                filter_preset_id=execution.filter_preset_id,
                filter_preset_version_id=execution.filter_preset_version_id,
                filter_preset_version_number=execution.filter_preset_version_number,
                custom_canonical=execution.custom_canonical,
                returned_count=execution.returned_count,
                total_count=execution.total_count,
                page_size=execution.page_size,
                cursor=execution.cursor,
                next_cursor=execution.next_cursor,
                duration_ms=execution.duration_ms,
                step_counts={"steps": list(execution.step_counts)}
                if execution.step_counts
                else None,
                software_version=execution.software_version,
                correlation_id=execution.correlation_id,
                failure_reason=execution.failure_reason,
                metadata_json=dict(execution.metadata),
            )
        )
        return execution

    async def add_ranking_execution(
        self, execution: RankingExecutionRecord
    ) -> RankingExecutionRecord:
        await self._session.execute(
            insert(_RANKING_EXECUTIONS).values(
                id=execution.id,
                filter_execution_id=execution.filter_execution_id,
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                executed_by=execution.executed_by,
                executed_at=execution.executed_at,
                method_id=execution.method_id,
                method_version=execution.method_version,
                method_implementation_id=execution.method_implementation_id,
                effective_canonical=dict(execution.effective_canonical),
                effective_hash=execution.effective_hash,
                field_dictionary_version=execution.field_dictionary_version,
                direction=execution.direction,
                tie_breakers={"columns": list(execution.tie_breakers)},
                outcome=execution.outcome.value,
                ranking_definition_id=execution.ranking_definition_id,
                ranking_version_id=execution.ranking_version_id,
                ranking_version_number=execution.ranking_version_number,
                ranking_preset_id=execution.ranking_preset_id,
                ranking_preset_version_id=execution.ranking_preset_version_id,
                ranking_preset_version_number=execution.ranking_preset_version_number,
                analysis_execution_id=execution.analysis_execution_id,
                scored_count=execution.scored_count,
                unscored_count=execution.unscored_count,
                duration_ms=execution.duration_ms,
                software_version=execution.software_version,
                correlation_id=execution.correlation_id,
                failure_reason=execution.failure_reason,
                metadata_json=dict(execution.metadata),
            )
        )
        return execution

    async def get_filter_execution(self, execution_id: str) -> FilterExecutionRecord | None:
        row = await self._fetch_one(
            select(_FILTER_EXECUTIONS).where(_FILTER_EXECUTIONS.c.id == execution_id)
        )
        return _to_filter_execution(row) if row else None

    async def get_ranking_execution_for_filter(
        self, filter_execution_id: str
    ) -> RankingExecutionRecord | None:
        row = await self._fetch_one(
            select(_RANKING_EXECUTIONS).where(
                _RANKING_EXECUTIONS.c.filter_execution_id == filter_execution_id
            )
        )
        return _to_ranking_execution(row) if row else None

    async def list_filter_executions(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        result_set_id: str | None = None,
    ) -> Paged[FilterExecutionRecord]:
        statement: Select = select(_FILTER_EXECUTIONS).where(
            _FILTER_EXECUTIONS.c.workspace_id.in_(workspace_ids or ("",))
        )
        if result_set_id is not None:
            statement = statement.where(_FILTER_EXECUTIONS.c.result_set_id == result_set_id)
        statement = statement.order_by(
            _FILTER_EXECUTIONS.c.executed_at.desc(), _FILTER_EXECUTIONS.c.id.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(
            items=tuple(_to_filter_execution(row) for row in rows), total=total, page=page
        )


def _to_filter_execution(row: Mapping[str, Any]) -> FilterExecutionRecord:
    steps = (row["step_counts"] or {}).get("steps", []) if row["step_counts"] else []
    return FilterExecutionRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        executed_by=row["executed_by"],
        executed_at=row["executed_at"],
        result_set_id=row["result_set_id"],
        effective_canonical=dict(row["effective_canonical"] or {}),
        effective_hash=row["effective_hash"],
        field_dictionary_version=row["field_dictionary_version"],
        outcome=QueryExecutionOutcome(row["outcome"]),
        project_id=row["project_id"],
        dataset_version_id=row["dataset_version_id"],
        filter_definition_id=row["filter_definition_id"],
        filter_version_id=row["filter_version_id"],
        filter_version_number=row["filter_version_number"],
        filter_preset_id=row["filter_preset_id"],
        filter_preset_version_id=row["filter_preset_version_id"],
        filter_preset_version_number=row["filter_preset_version_number"],
        custom_canonical=row["custom_canonical"],
        analysis_execution_id=row["analysis_execution_id"],
        returned_count=row["returned_count"],
        total_count=row["total_count"],
        page_size=row["page_size"],
        cursor=row["cursor"],
        next_cursor=row["next_cursor"],
        duration_ms=row["duration_ms"],
        step_counts=tuple(steps),
        software_version=row["software_version"],
        correlation_id=row["correlation_id"],
        failure_reason=row["failure_reason"],
        metadata=dict(row["metadata_json"] or {}),
    )


def _to_ranking_execution(row: Mapping[str, Any]) -> RankingExecutionRecord:
    return RankingExecutionRecord(
        id=row["id"],
        filter_execution_id=row["filter_execution_id"],
        workspace_id=row["workspace_id"],
        executed_by=row["executed_by"],
        executed_at=row["executed_at"],
        method_id=row["method_id"],
        method_version=row["method_version"],
        method_implementation_id=row["method_implementation_id"],
        effective_canonical=dict(row["effective_canonical"] or {}),
        effective_hash=row["effective_hash"],
        field_dictionary_version=row["field_dictionary_version"],
        direction=row["direction"],
        tie_breakers=tuple((row["tie_breakers"] or {}).get("columns", ())),
        outcome=QueryExecutionOutcome(row["outcome"]),
        project_id=row["project_id"],
        ranking_definition_id=row["ranking_definition_id"],
        ranking_version_id=row["ranking_version_id"],
        ranking_version_number=row["ranking_version_number"],
        ranking_preset_id=row["ranking_preset_id"],
        ranking_preset_version_id=row["ranking_preset_version_id"],
        ranking_preset_version_number=row["ranking_preset_version_number"],
        analysis_execution_id=row["analysis_execution_id"],
        scored_count=row["scored_count"],
        unscored_count=row["unscored_count"],
        duration_ms=row["duration_ms"],
        software_version=row["software_version"],
        correlation_id=row["correlation_id"],
        failure_reason=row["failure_reason"],
        metadata=dict(row["metadata_json"] or {}),
    )


class SqlSavedViewRepository(SqlRepository):
    """Presentation state. Version-checked like any other mutable row."""

    async def add(self, view: SavedViewRecord) -> SavedViewRecord:
        await self._session.execute(insert(_SAVED_VIEWS).values(**_view_values(view)))
        return view

    async def get(self, view_id: str) -> SavedViewRecord | None:
        row = await self._fetch_one(select(_SAVED_VIEWS).where(_SAVED_VIEWS.c.id == view_id))
        return _to_saved_view(row) if row else None

    async def save(self, view: SavedViewRecord) -> SavedViewRecord:
        values = _view_values(view)
        for key in ("id", "created_at", "created_by", "version"):
            values.pop(key, None)
        next_version = await self._versioned_update(
            _SAVED_VIEWS,
            entity_id=view.id,
            expected_version=view.version,
            values=values,
        )
        return replace(view, version=next_version)

    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[SavedViewRecord]:
        statement: Select = (
            select(_SAVED_VIEWS)
            .where(
                _scope_clause(_SAVED_VIEWS, scopes),
                _SAVED_VIEWS.c.deletion_state == DeletionState.ACTIVE.value,
            )
            .order_by(_SAVED_VIEWS.c.name.asc(), _SAVED_VIEWS.c.id.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_saved_view(row) for row in rows), total=total, page=page)


def _view_values(view: SavedViewRecord) -> dict[str, Any]:
    return {
        "id": view.id,
        "name": view.name,
        "description": view.description,
        "scope": view.scope.value,
        "scope_id": _scope_id(view),
        "filter_definition_id": view.default_filter_definition_id,
        "ranking_configuration_id": view.default_ranking_definition_id,
        "filter_preset_id": view.default_filter_preset_id,
        "ranking_preset_id": view.default_ranking_preset_id,
        "column_layout": {
            "columns": list(view.columns),
            "pinned": list(view.pinned_columns),
            "widths": dict(view.column_widths),
        },
        "sort_specification": {
            "field_id": view.sort_field_id,
            "descending": view.sort_descending,
        },
        "page_size": view.page_size,
        "owner_user_id": view.owner_user_id,
        "workspace_id": view.workspace_id,
        "project_id": view.project_id,
        "organization_id": view.organization_id,
        "metadata_json": dict(view.metadata),
        "deletion_state": view.deletion_state.value,
        "deleted_at": view.deleted_at,
        "created_by": view.created_by,
        "created_at": view.created_at,
        "updated_at": view.updated_at,
        "version": view.version,
    }


def _to_saved_view(row: Mapping[str, Any]) -> SavedViewRecord:
    layout = row["column_layout"] or {}
    sort = row["sort_specification"] or {}
    return SavedViewRecord(
        id=row["id"],
        name=row["name"],
        scope=QueryScope(row["scope"]),
        owner_user_id=row["owner_user_id"] or row["created_by"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
        description=row["description"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        organization_id=row["organization_id"],
        columns=tuple(layout.get("columns", ())),
        pinned_columns=tuple(layout.get("pinned", ())),
        column_widths=dict(layout.get("widths", {})),
        sort_field_id=sort.get("field_id"),
        sort_descending=bool(sort.get("descending", False)),
        page_size=row["page_size"],
        default_filter_definition_id=row["filter_definition_id"],
        default_filter_preset_id=row["filter_preset_id"],
        default_ranking_definition_id=row["ranking_configuration_id"],
        default_ranking_preset_id=row["ranking_preset_id"],
        deletion_state=DeletionState(row["deletion_state"]),
        deleted_at=row["deleted_at"],
        metadata=dict(row["metadata_json"] or {}),
    )


__all__ = [
    "SqlFilterDefinitionRepository",
    "SqlFilterPresetRepository",
    "SqlQueryExecutionRepository",
    "SqlRankingDefinitionRepository",
    "SqlRankingPresetRepository",
    "SqlSavedViewRepository",
]
