"""Saved views: how a user wants to look at a variant table.

A view holds visible columns, their order, pinned columns, widths, table sort and
page size, plus the identity of a filter or ranking it opens with. It is
presentation state and nothing more:

* it never contains scientific content, so it can never drift from the data;
* it references filters and rankings by identity, never by embedded content, so a
  view cannot silently pin an old expression;
* its table sort carries no prioritization meaning — sorting a column is not
  ranking, and the two are stored separately for exactly that reason.

Because a view is not provenance, it is mutable in place under an
optimistic-concurrency check rather than versioned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.query.dependencies import (
    SAVED_VIEW,
    QueryServices,
    authorized_scopes,
    configuration_capabilities,
    require_configuration_access,
    require_creation_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.query.entities import SavedViewRecord
from app.domain.value_objects.enums import AuditOutcome, QueryScope
from app.infrastructure.persistence.repositories.base import new_id

#: A view may not pin more columns than a table can meaningfully freeze, and may
#: not request a page larger than the query layer will serve.
MAX_VIEW_COLUMNS = 200


@dataclass(frozen=True, slots=True)
class SavedViewView:
    view: SavedViewRecord
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreateSavedViewCommand:
    actor: ActorContext
    request: RequestContext
    name: str
    scope: QueryScope
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    description: str | None = None
    columns: tuple[str, ...] = ()
    pinned_columns: tuple[str, ...] = ()
    column_widths: dict[str, int] | None = None
    sort_field_id: str | None = None
    sort_descending: bool = False
    page_size: int = 50
    default_filter_definition_id: str | None = None
    default_filter_preset_id: str | None = None
    default_ranking_definition_id: str | None = None
    default_ranking_preset_id: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateSavedViewCommand:
    actor: ActorContext
    request: RequestContext
    view_id: str
    expected_version: int
    changes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SavedViewQuery:
    actor: ActorContext
    request: RequestContext
    view_id: str


@dataclass(frozen=True, slots=True)
class ListSavedViewsQuery:
    actor: ActorContext
    request: RequestContext
    page: Page


class SavedViewService:
    def __init__(self, services: QueryServices) -> None:
        self._services = services

    def _validate_presentation(
        self,
        *,
        columns: tuple[str, ...],
        pinned: tuple[str, ...],
        sort_field_id: str | None,
        page_size: int,
    ) -> None:
        registry = self._services.fields
        if len(columns) > MAX_VIEW_COLUMNS:
            raise ValidationError(
                "a view declares more columns than allowed",
                details={"maximum": MAX_VIEW_COLUMNS, "requested": len(columns)},
            )
        unknown = [field_id for field_id in columns if registry.get(field_id) is None]
        if unknown:
            raise ValidationError(
                "unknown fields in the column layout", details={"field_ids": unknown}
            )
        outside = [field_id for field_id in pinned if field_id not in columns]
        if outside:
            raise ValidationError(
                "pinned columns must also be visible", details={"field_ids": outside}
            )
        if sort_field_id is not None:
            definition = registry.get(sort_field_id)
            if definition is None:
                raise ValidationError(
                    "unknown sort field", details={"field_id": sort_field_id}
                )
            if not definition.sortable:
                raise ValidationError(
                    "this field cannot be sorted", details={"field_id": sort_field_id}
                )
        if page_size < 1 or page_size > self._services.max_page_size:
            raise ValidationError(
                "the view page size is outside the permitted range",
                details={"maximum": self._services.max_page_size, "requested": page_size},
            )

    async def create(self, command: CreateSavedViewCommand) -> SavedViewView:
        now = self._services.clock.now()
        self._validate_presentation(
            columns=command.columns,
            pinned=command.pinned_columns,
            sort_field_id=command.sort_field_id,
            page_size=command.page_size,
        )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await require_creation_scope(
                self._services,
                repositories,
                command.actor,
                kind=SAVED_VIEW,
                scope=command.scope,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                organization_id=command.organization_id,
                recorder=recorder,
                occurred_at=now,
            )
            view = SavedViewRecord.create(
                id=new_id("viw"),
                name=command.name,
                scope=command.scope,
                owner_user_id=actor.actor_id,
                created_by=actor.actor_id,
                at=now,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                organization_id=command.organization_id,
                description=command.description,
                columns=command.columns,
                pinned_columns=command.pinned_columns,
                column_widths=dict(command.column_widths or {}),
                sort_field_id=command.sort_field_id,
                sort_descending=command.sort_descending,
                page_size=command.page_size,
                default_filter_definition_id=command.default_filter_definition_id,
                default_filter_preset_id=command.default_filter_preset_id,
                default_ranking_definition_id=command.default_ranking_definition_id,
                default_ranking_preset_id=command.default_ranking_preset_id,
            )
            await repositories.saved_views.add(view)
            await recorder.audit(
                action="saved_view.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="saved_view",
                resource_id=view.id,
                workspace_id=view.workspace_id,
                project_id=view.project_id,
                organization_id=view.organization_id,
                detail={"scope": view.scope.value},
            )
        return SavedViewView(
            view=view,
            capabilities=configuration_capabilities(actor, view, kind=SAVED_VIEW),
        )

    async def get(self, query: SavedViewQuery) -> SavedViewView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            view = await repositories.saved_views.get(query.view_id)
            if view is None:
                raise NotFoundError("saved_view", query.view_id)
            await require_configuration_access(
                self._services,
                repositories,
                query.actor,
                view,
                kind=SAVED_VIEW,
                manage=False,
                recorder=recorder,
                occurred_at=now,
            )
        return SavedViewView(
            view=view,
            capabilities=configuration_capabilities(query.actor, view, kind=SAVED_VIEW),
        )

    async def list(self, query: ListSavedViewsQuery) -> Paged:
        async with self._services.unit_of_work.begin() as repositories:
            return await repositories.saved_views.list_for_scope(
                scopes=authorized_scopes(query.actor, kind=SAVED_VIEW),
                page=query.page,
            )

    async def update(self, command: UpdateSavedViewCommand) -> SavedViewView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            view = await self._for_write(repositories, command, recorder=recorder, at=now)
            changes = dict(command.changes)
            columns = tuple(changes.get("columns", view.columns))
            pinned = tuple(changes.get("pinned_columns", view.pinned_columns))
            self._validate_presentation(
                columns=columns,
                pinned=pinned,
                sort_field_id=changes.get("sort_field_id", view.sort_field_id),
                page_size=int(changes.get("page_size", view.page_size)),
            )
            if "columns" in changes:
                changes["columns"] = columns
            if "pinned_columns" in changes:
                changes["pinned_columns"] = pinned
            updated = await repositories.saved_views.save(view.update(at=now, **changes))
            await recorder.audit(
                action="saved_view.updated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="saved_view",
                resource_id=updated.id,
                workspace_id=updated.workspace_id,
                project_id=updated.project_id,
                organization_id=updated.organization_id,
                detail={"fields": sorted(changes)},
            )
        return SavedViewView(
            view=updated,
            capabilities=configuration_capabilities(
                command.actor, updated, kind=SAVED_VIEW
            ),
        )

    async def delete(self, command: UpdateSavedViewCommand) -> SavedViewView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            view = await self._for_write(repositories, command, recorder=recorder, at=now)
            updated = await repositories.saved_views.save(view.soft_delete(at=now))
            await recorder.audit(
                action="saved_view.deleted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="saved_view",
                resource_id=updated.id,
                workspace_id=updated.workspace_id,
                project_id=updated.project_id,
                organization_id=updated.organization_id,
                previous_state=view.deletion_state.value,
                new_state=updated.deletion_state.value,
            )
        return SavedViewView(
            view=updated,
            capabilities=configuration_capabilities(
                command.actor, updated, kind=SAVED_VIEW
            ),
        )

    async def _for_write(
        self,
        repositories: Any,
        command: UpdateSavedViewCommand,
        *,
        recorder: ActivityRecorder,
        at: Any,
    ) -> SavedViewRecord:
        view = await repositories.saved_views.get(command.view_id)
        if view is None:
            raise NotFoundError("saved_view", command.view_id)
        await require_configuration_access(
            self._services,
            repositories,
            command.actor,
            view,
            kind=SAVED_VIEW,
            manage=True,
            recorder=recorder,
            occurred_at=at,
        )
        if view.version != command.expected_version:
            raise ConflictError(
                "this view was modified by someone else",
                details={
                    "expected_version": command.expected_version,
                    "current_version": view.version,
                },
            )
        return view


__all__ = [
    "MAX_VIEW_COLUMNS",
    "CreateSavedViewCommand",
    "ListSavedViewsQuery",
    "SavedViewQuery",
    "SavedViewService",
    "SavedViewView",
    "UpdateSavedViewCommand",
]
