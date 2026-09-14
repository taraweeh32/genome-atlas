"""In-memory doubles for the filtering, ranking, view and execution repositories.

These mirror the SQL repositories' *semantics*, which for this package means four
behaviours the use cases rely on for correctness:

* definition metadata is version-checked, so a concurrent edit raises a conflict
  instead of silently winning;
* version content is append-only — there is no code path here that rewrites a
  stored canonical expression, only one that flips ``is_referenced``;
* listings are scope-filtered exactly as the SQL clause is, so a test that leaks
  across tenants in memory would leak in PostgreSQL too;
* executions are immutable records with no update method at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.application.repositories import Page, Paged, QueryScopeFilter
from app.domain.errors import ConcurrencyConflictError
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
from app.domain.value_objects.enums import DeletionState, QueryScope


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


def _bump(entity, expected_version: int):
    if entity.version != expected_version:
        raise ConcurrencyConflictError(
            f"{type(entity).__name__.lower()} {entity.id} was modified concurrently"
        )
    return replace(entity, version=entity.version + 1)


def _in_scope(record, scopes: QueryScopeFilter) -> bool:
    """The in-memory twin of the SQL scope clause. Fails closed by construction."""
    scope = record.scope
    if scope is QueryScope.PLATFORM:
        return scopes.include_platform
    if scope is QueryScope.PERSONAL:
        return bool(scopes.user_id) and record.owner_user_id == scopes.user_id
    if scope is QueryScope.PROJECT:
        return record.project_id in scopes.project_ids
    if scope is QueryScope.ORGANIZATION:
        return record.organization_id in scopes.organization_ids
    return False


@dataclass(slots=True)
class _MemoryDefinitions:
    """Shared behaviour for saved filters, presets and ranking configurations."""

    definitions: dict[str, object] = field(default_factory=dict)
    versions: dict[str, object] = field(default_factory=dict)

    async def add(self, definition):
        self.definitions[definition.id] = definition
        return definition

    async def get(self, definition_id: str):
        return self.definitions.get(definition_id)

    async def save(self, definition):
        stored = self.definitions.get(definition.id)
        if stored is None:
            raise ConcurrencyConflictError(f"{definition.id} no longer exists")
        updated = _bump(stored, definition.version)
        updated = replace(definition, version=updated.version)
        self.definitions[definition.id] = updated
        return updated

    async def add_version(self, version):
        self.versions[version.id] = version
        return version

    async def get_version(self, version_id: str):
        return self.versions.get(version_id)

    async def find_version(self, *, definition_id: str, version_number: int):
        for candidate in self.versions.values():
            if (
                candidate.definition_id == definition_id
                and candidate.version_number == version_number
            ):
                return candidate
        return None

    async def latest_version(self, definition_id: str):
        candidates = [
            candidate
            for candidate in self.versions.values()
            if candidate.definition_id == definition_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate.version_number)

    async def list_versions(self, definition_id: str) -> tuple:
        return tuple(
            sorted(
                (
                    candidate
                    for candidate in self.versions.values()
                    if candidate.definition_id == definition_id
                ),
                key=lambda candidate: candidate.version_number,
            )
        )

    async def mark_version_referenced(self, version_id: str) -> None:
        stored = self.versions.get(version_id)
        if stored is not None:
            self.versions[version_id] = stored.mark_referenced()

    async def list_for_scope(self, *, scopes: QueryScopeFilter, page: Page) -> Paged:
        items = sorted(
            (
                record
                for record in self.definitions.values()
                if _in_scope(record, scopes)
                and record.deletion_state is DeletionState.ACTIVE
            ),
            key=lambda record: (record.name, record.id),
        )
        return _paged(items, page)


@dataclass(slots=True)
class MemoryFilterDefinitions(_MemoryDefinitions):
    """Saved filters."""

    definitions: dict[str, FilterDefinitionRecord] = field(default_factory=dict)
    versions: dict[str, FilterVersionRecord] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryFilterPresets(_MemoryDefinitions):
    definitions: dict[str, FilterPresetRecord] = field(default_factory=dict)
    versions: dict[str, FilterPresetVersionRecord] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRankingDefinitions(_MemoryDefinitions):
    definitions: dict[str, RankingDefinitionRecord] = field(default_factory=dict)
    versions: dict[str, RankingVersionRecord] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRankingPresets(_MemoryDefinitions):
    definitions: dict[str, RankingPresetRecord] = field(default_factory=dict)
    versions: dict[str, RankingPresetVersionRecord] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryQueryExecutions:
    """Append-only. Deliberately offers no way to modify a recorded execution."""

    filter_executions: dict[str, FilterExecutionRecord] = field(default_factory=dict)
    ranking_executions: dict[str, RankingExecutionRecord] = field(default_factory=dict)

    async def add_filter_execution(
        self, execution: FilterExecutionRecord
    ) -> FilterExecutionRecord:
        self.filter_executions[execution.id] = execution
        return execution

    async def add_ranking_execution(
        self, execution: RankingExecutionRecord
    ) -> RankingExecutionRecord:
        self.ranking_executions[execution.id] = execution
        return execution

    async def get_filter_execution(self, execution_id: str) -> FilterExecutionRecord | None:
        return self.filter_executions.get(execution_id)

    async def get_ranking_execution_for_filter(
        self, filter_execution_id: str
    ) -> RankingExecutionRecord | None:
        for execution in self.ranking_executions.values():
            if execution.filter_execution_id == filter_execution_id:
                return execution
        return None

    async def list_filter_executions(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        result_set_id: str | None = None,
    ) -> Paged[FilterExecutionRecord]:
        items = sorted(
            (
                execution
                for execution in self.filter_executions.values()
                if execution.workspace_id in workspace_ids
                and (result_set_id is None or execution.result_set_id == result_set_id)
            ),
            key=lambda execution: (execution.executed_at, execution.id),
            reverse=True,
        )
        return _paged(items, page)


@dataclass(slots=True)
class MemorySavedViews:
    views: dict[str, SavedViewRecord] = field(default_factory=dict)

    async def add(self, view: SavedViewRecord) -> SavedViewRecord:
        self.views[view.id] = view
        return view

    async def get(self, view_id: str) -> SavedViewRecord | None:
        return self.views.get(view_id)

    async def save(self, view: SavedViewRecord) -> SavedViewRecord:
        stored = self.views.get(view.id)
        if stored is None:
            raise ConcurrencyConflictError(f"{view.id} no longer exists")
        updated = replace(view, version=_bump(stored, view.version).version)
        self.views[view.id] = updated
        return updated

    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[SavedViewRecord]:
        items = sorted(
            (
                view
                for view in self.views.values()
                if _in_scope(view, scopes) and view.deletion_state is DeletionState.ACTIVE
            ),
            key=lambda view: (view.name, view.id),
        )
        return _paged(items, page)


__all__ = [
    "MemoryFilterDefinitions",
    "MemoryFilterPresets",
    "MemoryQueryExecutions",
    "MemoryRankingDefinitions",
    "MemoryRankingPresets",
    "MemorySavedViews",
]
