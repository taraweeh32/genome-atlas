"""Domain records for saved filters, presets, rankings, executions and views.

Same conventions as the Package 3–6 entities: frozen dataclasses, no ORM or
transport types, every state change a named method returning a new instance. A
mutable row carries ``version`` for optimistic concurrency; an append-only record
carries none, because there is nothing to overwrite.

The shape of this module follows one rule: **a definition is mutable metadata, a
version is immutable content**. Renaming a saved filter changes the definition;
changing a single condition creates a new version. That separation is what lets an
analysis executed months ago still resolve the exact expression it ran, even
after the filter it came from has been edited ten times.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ConflictError, ValidationError
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    DeletionState,
    QueryDefinitionState,
    QueryExecutionOutcome,
    QueryScope,
)

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2_000


def _require_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("a name is required")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(
            "name is too long", details={"max_length": MAX_NAME_LENGTH}
        )
    return cleaned


def _check_description(description: str | None) -> str | None:
    if description is None:
        return None
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            "description is too long", details={"max_length": MAX_DESCRIPTION_LENGTH}
        )
    return description


def _require_scope_context(
    scope: QueryScope,
    *,
    workspace_id: str | None,
    project_id: str | None,
    organization_id: str | None,
) -> None:
    """A scope without its context would be unenforceable, so it is refused.

    This is the domain-level half of tenant isolation: an organization-scoped
    configuration that names no organization could not be confined to one.
    """
    if scope is QueryScope.PLATFORM:
        if workspace_id or project_id or organization_id:
            raise ValidationError(
                "a platform-scoped configuration carries no tenant context"
            )
        return
    if scope is QueryScope.ORGANIZATION and not organization_id:
        raise ValidationError("an organization-scoped configuration requires an organization")
    if scope is QueryScope.PROJECT and not (project_id and workspace_id):
        raise ValidationError(
            "a project-scoped configuration requires a project and its workspace"
        )
    if scope is QueryScope.PERSONAL and not workspace_id:
        raise ValidationError("a personal configuration requires a workspace")


# --------------------------------------------------------------------------- #
# Shared definition behaviour                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Definition:
    """Fields and moves shared by all four definition kinds."""

    id: str
    name: str
    scope: QueryScope
    state: QueryDefinitionState
    created_by: str
    created_at: datetime
    updated_at: datetime
    #: The version number a client last read. Concurrent edits are rejected
    #: rather than merged.
    version: int = 1
    description: str | None = None
    owner_user_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    #: Highest content version number issued so far. Never decreases, so a
    #: version number is never reused after a version is withdrawn.
    latest_version_number: int = 0
    #: Set once any version has been referenced by an analysis execution. From
    #: that moment the definition may still be renamed or archived, but no
    #: existing version may be altered.
    is_referenced: bool = False
    deletion_state: DeletionState = DeletionState.ACTIVE
    deleted_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- lifecycle -------------------------------------------------------- #

    @property
    def lifecycle_entity(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def rename(self, *, name: str, description: str | None, at: datetime):
        """Metadata edit. Deliberately does not touch any version's content."""
        return replace(
            self,
            name=_require_name(name),
            description=_check_description(description),
            updated_at=at,
        )

    def publish(self, *, at: datetime):
        if self.latest_version_number == 0:
            raise ValidationError(
                "a definition cannot be published before it has a version"
            )
        state = require_transition(
            self.lifecycle_entity, self.state, QueryDefinitionState.PUBLISHED
        )
        return replace(self, state=state, updated_at=at)

    def archive(self, *, at: datetime):
        state = require_transition(
            self.lifecycle_entity, self.state, QueryDefinitionState.ARCHIVED
        )
        return replace(self, state=state, updated_at=at)

    def restore(self, *, at: datetime):
        state = require_transition(
            self.lifecycle_entity, self.state, QueryDefinitionState.PUBLISHED
        )
        return replace(self, state=state, updated_at=at)

    def with_new_version(self, *, number: int, at: datetime):
        if number != self.latest_version_number + 1:
            raise ConflictError(
                "version numbers are issued strictly in sequence",
                details={
                    "expected": self.latest_version_number + 1,
                    "requested": number,
                },
            )
        return replace(self, latest_version_number=number, updated_at=at)

    def mark_referenced(self, *, at: datetime):
        if self.is_referenced:
            return self
        return replace(self, is_referenced=True, updated_at=at)

    def soft_delete(self, *, at: datetime):
        state = require_transition("deletion", self.deletion_state, DeletionState.SOFT_DELETED)
        return replace(self, deletion_state=state, deleted_at=at, updated_at=at)

    def restore_deleted(self, *, at: datetime):
        state = require_transition("deletion", self.deletion_state, DeletionState.ACTIVE)
        return replace(self, deletion_state=state, deleted_at=None, updated_at=at)

    @property
    def is_usable(self) -> bool:
        return (
            self.state is QueryDefinitionState.PUBLISHED
            and self.deletion_state is DeletionState.ACTIVE
        )


@dataclass(frozen=True, slots=True)
class _Version:
    """Fields shared by all four version kinds. Append-only: no ``version``."""

    id: str
    definition_id: str
    version_number: int
    #: Canonical, validated content. Stored canonically so two definitions that
    #: mean the same thing hash the same and an execution is reproducible.
    canonical: dict[str, Any]
    canonical_hash: str
    field_dictionary_version: str
    created_by: str
    created_at: datetime
    #: Field identifiers the content requires. Lets the platform tell a user a
    #: preset does not apply to a dataset *before* running anything.
    required_field_ids: tuple[str, ...] = ()
    change_note: str | None = None
    #: True once an analysis execution referenced this exact version.
    is_referenced: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_referenced(self):
        if self.is_referenced:
            return self
        return replace(self, is_referenced=True)


# --------------------------------------------------------------------------- #
# Saved filters                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FilterDefinitionRecord(_Definition):
    """A saved filter: mutable metadata pointing at immutable versions."""

    @property
    def lifecycle_entity(self) -> str:
        return "filter_definition"

    @staticmethod
    def create(
        *,
        id: str,
        name: str,
        scope: QueryScope,
        created_by: str,
        at: datetime,
        description: str | None = None,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FilterDefinitionRecord:
        _require_scope_context(
            scope,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
        )
        return FilterDefinitionRecord(
            id=id,
            name=_require_name(name),
            scope=scope,
            state=QueryDefinitionState.DRAFT,
            created_by=created_by,
            created_at=at,
            updated_at=at,
            description=_check_description(description),
            owner_user_id=owner_user_id or created_by,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class FilterVersionRecord(_Version):
    """One immutable filter expression.

    ``canonical`` holds the canonical filter expression payload. Editing a saved
    filter never rewrites this row; it appends the next one.
    """

    condition_count: int = 0
    depth: int = 1


# --------------------------------------------------------------------------- #
# Filter presets                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FilterPresetRecord(_Definition):
    """A curated filter offered within a scope.

    A preset is not a second filtering engine: its content is the same canonical
    expression a saved filter holds. What differs is governance — who may publish
    it, and to whom it is offered.
    """

    #: Data contexts the preset is applicable to (e.g. ``result_set``).
    applicable_contexts: tuple[str, ...] = ("result_set",)

    @property
    def lifecycle_entity(self) -> str:
        return "filter_preset"

    @staticmethod
    def create(
        *,
        id: str,
        name: str,
        scope: QueryScope,
        created_by: str,
        at: datetime,
        description: str | None = None,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
        applicable_contexts: tuple[str, ...] = ("result_set",),
        metadata: dict[str, Any] | None = None,
    ) -> FilterPresetRecord:
        _require_scope_context(
            scope,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
        )
        if not applicable_contexts:
            raise ValidationError("a preset must declare at least one applicable context")
        return FilterPresetRecord(
            id=id,
            name=_require_name(name),
            scope=scope,
            state=QueryDefinitionState.DRAFT,
            created_by=created_by,
            created_at=at,
            updated_at=at,
            description=_check_description(description),
            owner_user_id=owner_user_id or created_by,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
            applicable_contexts=tuple(applicable_contexts),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class FilterPresetVersionRecord(_Version):
    """One immutable published preset expression."""

    condition_count: int = 0
    depth: int = 1


# --------------------------------------------------------------------------- #
# Ranking configurations                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RankingDefinitionRecord(_Definition):
    """A saved ranking configuration."""

    #: Registry method this configuration is written against. Kept on the
    #: definition so a listing can be filtered by method without loading versions.
    method_id: str = ""

    @property
    def lifecycle_entity(self) -> str:
        return "ranking_definition"

    @staticmethod
    def create(
        *,
        id: str,
        name: str,
        scope: QueryScope,
        method_id: str,
        created_by: str,
        at: datetime,
        description: str | None = None,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RankingDefinitionRecord:
        _require_scope_context(
            scope,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
        )
        if not method_id:
            raise ValidationError("a ranking configuration requires a method")
        return RankingDefinitionRecord(
            id=id,
            name=_require_name(name),
            scope=scope,
            state=QueryDefinitionState.DRAFT,
            created_by=created_by,
            created_at=at,
            updated_at=at,
            method_id=method_id,
            description=_check_description(description),
            owner_user_id=owner_user_id or created_by,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class RankingVersionRecord(_Version):
    """One immutable ranking configuration.

    ``canonical`` holds the canonical ranking specification: method, method
    version, components, weights, direction, tie-breakers and parameters.
    """

    method_id: str = ""
    method_version: str = ""
    component_count: int = 0


@dataclass(frozen=True, slots=True)
class RankingPresetRecord(_Definition):
    """A curated ranking configuration offered within a scope."""

    method_id: str = ""
    applicable_contexts: tuple[str, ...] = ("result_set",)

    @property
    def lifecycle_entity(self) -> str:
        return "ranking_preset"

    @staticmethod
    def create(
        *,
        id: str,
        name: str,
        scope: QueryScope,
        method_id: str,
        created_by: str,
        at: datetime,
        description: str | None = None,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
        applicable_contexts: tuple[str, ...] = ("result_set",),
        metadata: dict[str, Any] | None = None,
    ) -> RankingPresetRecord:
        _require_scope_context(
            scope,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
        )
        if not method_id:
            raise ValidationError("a ranking preset requires a method")
        if not applicable_contexts:
            raise ValidationError("a preset must declare at least one applicable context")
        return RankingPresetRecord(
            id=id,
            name=_require_name(name),
            scope=scope,
            state=QueryDefinitionState.DRAFT,
            created_by=created_by,
            created_at=at,
            updated_at=at,
            method_id=method_id,
            description=_check_description(description),
            owner_user_id=owner_user_id or created_by,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
            applicable_contexts=tuple(applicable_contexts),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class RankingPresetVersionRecord(_Version):
    """One immutable published ranking preset configuration."""

    method_id: str = ""
    method_version: str = ""
    component_count: int = 0


# --------------------------------------------------------------------------- #
# Executions                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FilterExecutionRecord:
    """What was actually executed, frozen at execution time.

    This record is the reproducibility contract. It stores the *effective*
    canonical expression together with the identity and version of everything
    that produced it, so that publishing a new preset version tomorrow cannot
    change what a query returned today.
    """

    id: str
    workspace_id: str
    executed_by: str
    executed_at: datetime
    #: Data the query read: a result set and, through it, a dataset version.
    result_set_id: str
    effective_canonical: dict[str, Any]
    effective_hash: str
    field_dictionary_version: str
    outcome: QueryExecutionOutcome
    project_id: str | None = None
    dataset_version_id: str | None = None
    #: Saved filter and preset the caller started from, each with the exact
    #: version resolved at execution time. Both are optional: a caller may filter
    #: ad hoc, or apply a preset without saving anything.
    filter_definition_id: str | None = None
    filter_version_id: str | None = None
    filter_version_number: int | None = None
    filter_preset_id: str | None = None
    filter_preset_version_id: str | None = None
    filter_preset_version_number: int | None = None
    #: The caller's own conditions, kept separable from the preset's.
    custom_canonical: dict[str, Any] | None = None
    analysis_execution_id: str | None = None
    #: Rows returned on this page and, only when it was actually computed, the
    #: total. ``None`` means not computed — never zero.
    returned_count: int = 0
    total_count: int | None = None
    page_size: int = 0
    cursor: str | None = None
    next_cursor: str | None = None
    duration_ms: int | None = None
    #: Per-condition surviving counts, present only when explicitly requested and
    #: computed. Absent rather than fabricated.
    step_counts: tuple[dict[str, Any], ...] = ()
    software_version: str | None = None
    correlation_id: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RankingExecutionRecord:
    """The ranking half of an execution, recorded separately on purpose.

    Filtering and ranking are separate capabilities, so their executions are
    separate records joined by ``filter_execution_id``. A query with no ranking
    produces no row here at all, which keeps "unranked" distinguishable from
    "ranked by nothing".
    """

    id: str
    filter_execution_id: str
    workspace_id: str
    executed_by: str
    executed_at: datetime
    method_id: str
    method_version: str
    method_implementation_id: str
    effective_canonical: dict[str, Any]
    effective_hash: str
    field_dictionary_version: str
    direction: str
    tie_breakers: tuple[str, ...]
    outcome: QueryExecutionOutcome = QueryExecutionOutcome.COMPLETED
    project_id: str | None = None
    ranking_definition_id: str | None = None
    ranking_version_id: str | None = None
    ranking_version_number: int | None = None
    ranking_preset_id: str | None = None
    ranking_preset_version_id: str | None = None
    ranking_preset_version_number: int | None = None
    analysis_execution_id: str | None = None
    scored_count: int = 0
    #: Rows for which no component had a reported value. Surfaced because an
    #: unscored variant is a data-completeness fact, not a low-priority variant.
    unscored_count: int = 0
    duration_ms: int | None = None
    software_version: str | None = None
    correlation_id: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Saved views                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SavedViewRecord:
    """Presentation state for a variant table: columns, sort, page size.

    Deliberately separate from filters and rankings. A view records how a user
    wants to *look* at data — which columns, in what order, sorted how. It never
    changes which variants exist, what they mean, or how they were prioritized,
    and it is never part of scientific provenance.
    """

    id: str
    name: str
    scope: QueryScope
    owner_user_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    description: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    #: Visible columns, in display order.
    columns: tuple[str, ...] = ()
    pinned_columns: tuple[str, ...] = ()
    column_widths: dict[str, int] = field(default_factory=dict)
    #: Table sort, which is *not* ranking: it reorders the page a user is looking
    #: at and carries no prioritization meaning.
    sort_field_id: str | None = None
    sort_descending: bool = False
    page_size: int = 50
    #: Filter/ranking the view opens with, by identity only. The view never
    #: embeds their content, so it cannot drift from the definitions.
    default_filter_definition_id: str | None = None
    default_filter_preset_id: str | None = None
    default_ranking_definition_id: str | None = None
    default_ranking_preset_id: str | None = None
    deletion_state: DeletionState = DeletionState.ACTIVE
    deleted_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        *,
        id: str,
        name: str,
        scope: QueryScope,
        owner_user_id: str,
        created_by: str,
        at: datetime,
        workspace_id: str | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
        **rest: Any,
    ) -> SavedViewRecord:
        _require_scope_context(
            scope,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
        )
        return SavedViewRecord(
            id=id,
            name=_require_name(name),
            scope=scope,
            owner_user_id=owner_user_id,
            created_by=created_by,
            created_at=at,
            updated_at=at,
            workspace_id=workspace_id,
            project_id=project_id,
            organization_id=organization_id,
            **rest,
        )

    def update(self, *, at: datetime, **changes: Any) -> SavedViewRecord:
        if "name" in changes and changes["name"] is not None:
            changes["name"] = _require_name(changes["name"])
        return replace(self, updated_at=at, **changes)

    def soft_delete(self, *, at: datetime) -> SavedViewRecord:
        state = require_transition("deletion", self.deletion_state, DeletionState.SOFT_DELETED)
        return replace(self, deletion_state=state, deleted_at=at, updated_at=at)


__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_NAME_LENGTH",
    "FilterDefinitionRecord",
    "FilterExecutionRecord",
    "FilterPresetRecord",
    "FilterPresetVersionRecord",
    "FilterVersionRecord",
    "RankingDefinitionRecord",
    "RankingExecutionRecord",
    "RankingPresetRecord",
    "RankingPresetVersionRecord",
    "RankingVersionRecord",
    "SavedViewRecord",
]
