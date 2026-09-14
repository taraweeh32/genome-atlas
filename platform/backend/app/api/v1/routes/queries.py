"""Filtering, ranking, variant query and saved-view endpoints.

Thin handlers, as everywhere: parse transport input, hand an explicit command to a
use case, shape the result. Four boundaries are visible in the layout:

* **A filter arrives as structured data.** There is no endpoint that accepts SQL,
  a query string to be interpolated, or any other executable expression. Field
  identifiers are resolved against the published dictionary, values are bound.
* **Filtering and ranking are separate resources.** ``/filters`` and ``/rankings``
  have their own lifecycles, their own permissions and their own versions. A
  ranking can never narrow a result set and a filter can never produce a score.
* **Every read is bounded.** The variant query returns one page with a cursor;
  distinct values return one bounded page. Anything expensive goes to the durable
  job system through ``/variants/query/deferred`` rather than being streamed.
* **Scope is declared by the record, never by the request.** The handler passes the
  caller's actor through; the use case decides which permission applies from the
  scope stored on the row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.query_mapping import (
    configuration_response,
    configuration_version_response,
    configuration_view_response,
    field_dictionary_response,
    field_values_response,
    filter_field_response,
    filter_validation_response,
    query_limits_response,
    ranking_method_response,
    saved_view_response,
    variant_query_response,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.query import (
    ConfigurationCollection,
    ConfigurationCreatePayload,
    ConfigurationLifecyclePayload,
    ConfigurationMetadataPayload,
    ConfigurationResponse,
    ConfigurationVersionCollection,
    ConfigurationVersionPayload,
    DeferredQueryPayload,
    DeferredQueryResponse,
    FieldDictionaryResponse,
    FieldValuesResponse,
    FilterFieldResponse,
    FilterValidationPayload,
    FilterValidationResponse,
    QueryLimitsResponse,
    RankingMethodCollection,
    RankingMethodResponse,
    SavedViewCollection,
    SavedViewCreatePayload,
    SavedViewResponse,
    SavedViewUpdatePayload,
    VariantQueryPayload,
    VariantQueryResponse,
)
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.query import (
    DescribeFilterFields,
    ExecuteVariantQuery,
    FilterPresetService,
    GetFilterField,
    RankingPresetService,
    SavedFilterService,
    SavedRankingService,
    SavedViewService,
    SearchFieldValues,
    ValidateFilterExpression,
)
from app.application.use_cases.query.deferred import (
    DEFAULT_MAX_MATERIALIZED_ROWS,
    DeferVariantQuery,
    DeferVariantQueryCommand,
)
from app.application.use_cases.query.definitions import (
    AddVersionCommand,
    ConfigurationService,
    CreateConfigurationCommand,
    GetConfigurationQuery,
    LifecycleCommand,
    ListConfigurationsQuery,
    UpdateMetadataCommand,
    ValidateFilterQuery,
)
from app.application.use_cases.query.execution import (
    FilterSelection,
    RankingSelection,
    VariantQueryCommand,
)
from app.application.use_cases.query.fields import (
    DescribeFieldsQuery,
    GetFieldQuery,
    SearchFieldValuesQuery,
)
from app.application.use_cases.query.views import (
    CreateSavedViewCommand,
    ListSavedViewsQuery,
    SavedViewQuery,
    UpdateSavedViewCommand,
)
from app.domain.authorization.permissions import Permission
from app.domain.errors import NotFoundError
from app.domain.query.fields import FilterFieldCategory
from app.domain.value_objects.enums import QueryScope

filter_fields_router = APIRouter(prefix="/filter-fields", tags=["filtering"])
filters_router = APIRouter(prefix="/filters", tags=["filtering"])
filter_presets_router = APIRouter(prefix="/filter-presets", tags=["filtering"])
ranking_methods_router = APIRouter(prefix="/ranking-methods", tags=["ranking"])
rankings_router = APIRouter(prefix="/rankings", tags=["ranking"])
ranking_presets_router = APIRouter(prefix="/ranking-presets", tags=["ranking"])
variant_query_router = APIRouter(prefix="/variants", tags=["filtering"])
saved_views_router = APIRouter(prefix="/saved-views", tags=["filtering"])
query_admin_router = APIRouter(
    prefix="/administration/query", tags=["administration"]
)


# --------------------------------------------------------------------------- #
# Field dictionary                                                            #
# --------------------------------------------------------------------------- #


@filter_fields_router.get(
    "",
    response_model=FieldDictionaryResponse,
    summary="Describe the filterable field dictionary",
    responses=ERROR_RESPONSES,
)
async def describe_filter_fields(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    result_set_id: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> FieldDictionaryResponse:
    view = await DescribeFilterFields(container.query_services()).execute(
        DescribeFieldsQuery(
            actor=caller.actor,
            request=context,
            result_set_id=result_set_id,
            category=(
                parse_enum(FilterFieldCategory, category, field="category")
                if category is not None
                else None
            ),
        )
    )
    return field_dictionary_response(view)


@filter_fields_router.get(
    "/{field_id}",
    response_model=FilterFieldResponse,
    summary="Get one field definition",
    responses=ERROR_RESPONSES,
)
async def get_filter_field(
    field_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> FilterFieldResponse:
    definition = await GetFilterField(container.query_services()).execute(
        GetFieldQuery(actor=caller.actor, request=context, field_id=field_id)
    )
    return filter_field_response(definition)


@filter_fields_router.get(
    "/{field_id}/values",
    response_model=FieldValuesResponse,
    summary="Search distinct values of a high-cardinality field",
    responses=ERROR_RESPONSES,
)
async def search_field_values(
    field_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    result_set_id: Annotated[str, Query()],
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    with_counts: Annotated[bool, Query()] = False,
) -> FieldValuesResponse:
    view = await SearchFieldValues(container.query_services()).execute(
        SearchFieldValuesQuery(
            actor=caller.actor,
            request=context,
            field_id=field_id,
            result_set_id=result_set_id,
            search=search,
            limit=limit,
            with_counts=with_counts,
        )
    )
    return field_values_response(view)


# --------------------------------------------------------------------------- #
# Shared configuration lifecycle handlers                                     #
# --------------------------------------------------------------------------- #


async def _create(
    service: ConfigurationService,
    payload: ConfigurationCreatePayload,
    caller,
    context,
) -> ConfigurationResponse:
    view = await service.create(
        CreateConfigurationCommand(
            actor=caller.actor,
            request=context,
            name=payload.name,
            scope=parse_enum(QueryScope, payload.scope, field="scope"),
            content=payload.content,
            description=payload.description,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            organization_id=payload.organization_id,
            applicable_contexts=tuple(payload.applicable_contexts or ("result_set",)),
            change_note=payload.change_note,
            publish=payload.publish,
        )
    )
    return configuration_view_response(view)


async def _list(
    service: ConfigurationService, caller, context, page
) -> ConfigurationCollection:
    paged = await service.list(
        ListConfigurationsQuery(actor=caller.actor, request=context, page=page)
    )
    return ConfigurationCollection(
        items=[configuration_response(item) for item in paged.items],
        page=page_meta(paged),
    )


async def _get(
    service: ConfigurationService,
    definition_id: str,
    caller,
    context,
    version_number: int | None = None,
) -> ConfigurationResponse:
    view = await service.get(
        GetConfigurationQuery(
            actor=caller.actor,
            request=context,
            definition_id=definition_id,
            version_number=version_number,
        )
    )
    return configuration_view_response(view)


async def _versions(
    service: ConfigurationService, definition_id: str, caller, context
) -> ConfigurationVersionCollection:
    versions = await service.list_versions(
        GetConfigurationQuery(
            actor=caller.actor, request=context, definition_id=definition_id
        )
    )
    return ConfigurationVersionCollection(
        items=[configuration_version_response(item) for item in versions]
    )


async def _update_metadata(
    service: ConfigurationService,
    definition_id: str,
    payload: ConfigurationMetadataPayload,
    caller,
    context,
) -> ConfigurationResponse:
    view = await service.update_metadata(
        UpdateMetadataCommand(
            actor=caller.actor,
            request=context,
            definition_id=definition_id,
            expected_version=payload.expected_version,
            name=payload.name,
            description=payload.description,
        )
    )
    return configuration_view_response(view)


async def _add_version(
    service: ConfigurationService,
    definition_id: str,
    payload: ConfigurationVersionPayload,
    caller,
    context,
) -> ConfigurationResponse:
    view = await service.add_version(
        AddVersionCommand(
            actor=caller.actor,
            request=context,
            definition_id=definition_id,
            expected_version=payload.expected_version,
            content=payload.content,
            change_note=payload.change_note,
        )
    )
    return configuration_view_response(view)


async def _transition(
    service: ConfigurationService,
    action: str,
    definition_id: str,
    payload: ConfigurationLifecyclePayload,
    caller,
    context,
) -> ConfigurationResponse:
    command = LifecycleCommand(
        actor=caller.actor,
        request=context,
        definition_id=definition_id,
        expected_version=payload.expected_version,
    )
    view = await getattr(service, action)(command)
    return configuration_view_response(view)


def _register_configuration_routes(
    router: APIRouter, service_type: type[ConfigurationService], *, noun: str
) -> None:
    """Attach the identical governed lifecycle to one configuration resource.

    Filters, filter presets, rankings and ranking presets share a *shape*, not a
    permission: each service names its own permissions, so registering the routes
    from one place cannot merge two kinds' authorization.
    """

    @router.get(
        "",
        response_model=ConfigurationCollection,
        summary=f"List {noun}s the caller may see",
        responses=ERROR_RESPONSES,
        name=f"list_{noun}s",
    )
    async def list_items(  # pyright: ignore[reportUnusedFunction]
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
        page: PageDep,
    ) -> ConfigurationCollection:
        return await _list(service_type(container.query_services()), caller, context, page)

    @router.post(
        "",
        response_model=ConfigurationResponse,
        status_code=status.HTTP_201_CREATED,
        summary=f"Create a {noun}",
        responses=ERROR_RESPONSES,
        name=f"create_{noun}",
    )
    async def create_item(  # pyright: ignore[reportUnusedFunction]
        payload: ConfigurationCreatePayload,
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
    ) -> ConfigurationResponse:
        return await _create(
            service_type(container.query_services()), payload, caller, context
        )

    @router.get(
        "/{definition_id}",
        response_model=ConfigurationResponse,
        summary=f"Get a {noun}, optionally at one version",
        responses=ERROR_RESPONSES,
        name=f"get_{noun}",
    )
    async def get_item(  # pyright: ignore[reportUnusedFunction]
        definition_id: str,
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
        version_number: Annotated[int | None, Query(ge=1)] = None,
    ) -> ConfigurationResponse:
        return await _get(
            service_type(container.query_services()),
            definition_id,
            caller,
            context,
            version_number,
        )

    @router.patch(
        "/{definition_id}",
        response_model=ConfigurationResponse,
        summary=f"Rename or redescribe a {noun}",
        responses=ERROR_RESPONSES,
        name=f"update_{noun}",
    )
    async def update_item(  # pyright: ignore[reportUnusedFunction]
        definition_id: str,
        payload: ConfigurationMetadataPayload,
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
    ) -> ConfigurationResponse:
        return await _update_metadata(
            service_type(container.query_services()),
            definition_id,
            payload,
            caller,
            context,
        )

    @router.get(
        "/{definition_id}/versions",
        response_model=ConfigurationVersionCollection,
        summary=f"List every version of a {noun}",
        responses=ERROR_RESPONSES,
        name=f"list_{noun}_versions",
    )
    async def list_item_versions(  # pyright: ignore[reportUnusedFunction]
        definition_id: str,
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
    ) -> ConfigurationVersionCollection:
        return await _versions(
            service_type(container.query_services()), definition_id, caller, context
        )

    @router.post(
        "/{definition_id}/versions",
        response_model=ConfigurationResponse,
        status_code=status.HTTP_201_CREATED,
        summary=f"Append a new immutable version of a {noun}",
        responses=ERROR_RESPONSES,
        name=f"create_{noun}_version",
    )
    async def add_item_version(  # pyright: ignore[reportUnusedFunction]
        definition_id: str,
        payload: ConfigurationVersionPayload,
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
    ) -> ConfigurationResponse:
        return await _add_version(
            service_type(container.query_services()),
            definition_id,
            payload,
            caller,
            context,
        )

    for action in ("publish", "archive", "restore"):

        def make(action_name: str):
            @router.post(
                f"/{{definition_id}}/{action_name}",
                response_model=ConfigurationResponse,
                summary=f"{action_name.capitalize()} a {noun}",
                responses=ERROR_RESPONSES,
                name=f"{action_name}_{noun}",
            )
            async def transition(  # pyright: ignore[reportUnusedFunction]
                definition_id: str,
                payload: ConfigurationLifecyclePayload,
                caller: CallerDep,
                container: ContainerDep,
                context: RequestContextDep,
            ) -> ConfigurationResponse:
                return await _transition(
                    service_type(container.query_services()),
                    action_name,
                    definition_id,
                    payload,
                    caller,
                    context,
                )

            return transition

        make(action)

    @router.delete(
        "/{definition_id}",
        response_model=ConfigurationResponse,
        summary=f"Soft-delete a {noun}",
        responses=ERROR_RESPONSES,
        name=f"delete_{noun}",
    )
    async def delete_item(  # pyright: ignore[reportUnusedFunction]
        definition_id: str,
        payload: ConfigurationLifecyclePayload,
        caller: CallerDep,
        container: ContainerDep,
        context: RequestContextDep,
    ) -> ConfigurationResponse:
        return await _transition(
            service_type(container.query_services()),
            "soft_delete",
            definition_id,
            payload,
            caller,
            context,
        )


# --------------------------------------------------------------------------- #
# Filter validation (declared before the identifier routes below)             #
# --------------------------------------------------------------------------- #


@filters_router.post(
    "/validate",
    response_model=FilterValidationResponse,
    summary="Validate a filter expression without saving or running it",
    responses=ERROR_RESPONSES,
)
async def validate_filter_expression(
    payload: FilterValidationPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> FilterValidationResponse:
    view = await ValidateFilterExpression(container.query_services()).execute(
        ValidateFilterQuery(
            actor=caller.actor, request=context, content=payload.expression
        )
    )
    return filter_validation_response(view)


_register_configuration_routes(filters_router, SavedFilterService, noun="filter")
_register_configuration_routes(
    filter_presets_router, FilterPresetService, noun="filter_preset"
)
_register_configuration_routes(rankings_router, SavedRankingService, noun="ranking")
_register_configuration_routes(
    ranking_presets_router, RankingPresetService, noun="ranking_preset"
)


# --------------------------------------------------------------------------- #
# Ranking methods                                                             #
# --------------------------------------------------------------------------- #


@ranking_methods_router.get(
    "",
    response_model=RankingMethodCollection,
    summary="List registered ranking methods",
    responses=ERROR_RESPONSES,
)
async def list_ranking_methods(
    caller: CallerDep, container: ContainerDep, context: RequestContextDep
) -> RankingMethodCollection:
    del caller, context
    registry = container.query_services().methods
    return RankingMethodCollection(
        items=[
            ranking_method_response(method) for method in registry.available_methods()
        ]
    )


@ranking_methods_router.get(
    "/{method_id}",
    response_model=RankingMethodResponse,
    summary="Get one ranking method",
    responses=ERROR_RESPONSES,
)
async def get_ranking_method(
    method_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> RankingMethodResponse:
    del caller, context
    method = container.query_services().methods.get(method_id)
    if method is None:
        raise NotFoundError("ranking_method", method_id)
    return ranking_method_response(method)


# --------------------------------------------------------------------------- #
# Variant query                                                               #
# --------------------------------------------------------------------------- #


def _filter_selection(payload) -> FilterSelection:
    if payload is None:
        return FilterSelection()
    return FilterSelection(
        expression=payload.expression,
        filter_definition_id=payload.filter_definition_id,
        filter_version_number=payload.filter_version_number,
        filter_preset_id=payload.filter_preset_id,
        filter_preset_version_number=payload.filter_preset_version_number,
    )


def _ranking_selection(payload) -> RankingSelection:
    if payload is None:
        return RankingSelection()
    return RankingSelection(
        configuration=payload.configuration,
        ranking_definition_id=payload.ranking_definition_id,
        ranking_version_number=payload.ranking_version_number,
        ranking_preset_id=payload.ranking_preset_id,
        ranking_preset_version_number=payload.ranking_preset_version_number,
    )


@variant_query_router.post(
    "/query",
    response_model=VariantQueryResponse,
    summary="Run a bounded, server-side filtered and optionally ranked variant query",
    responses=ERROR_RESPONSES,
)
async def query_variants(
    payload: VariantQueryPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> VariantQueryResponse:
    page = await ExecuteVariantQuery(container.query_services()).execute(
        VariantQueryCommand(
            actor=caller.actor,
            request=context,
            result_set_id=payload.result_set_id,
            filter=_filter_selection(payload.filter),
            ranking=_ranking_selection(payload.ranking),
            field_ids=tuple(payload.field_ids or ()),
            page_size=payload.page_size,
            cursor=payload.cursor,
            sort_field_id=payload.sort_field_id,
            sort_descending=payload.sort_descending,
            include_total=payload.include_total,
        )
    )
    return variant_query_response(page)


@variant_query_router.post(
    "/query/deferred",
    response_model=DeferredQueryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run an expensive variant query as a durable background job",
    responses=ERROR_RESPONSES,
)
async def defer_variant_query(
    payload: DeferredQueryPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DeferredQueryResponse:
    accepted = await DeferVariantQuery(container.query_services()).execute(
        DeferVariantQueryCommand(
            actor=caller.actor,
            request=context,
            result_set_id=payload.result_set_id,
            filter=_filter_selection(payload.filter),
            ranking=_ranking_selection(payload.ranking),
            field_ids=tuple(payload.field_ids or ()),
            sort_field_id=payload.sort_field_id,
            sort_descending=payload.sort_descending,
            max_rows=payload.max_rows or DEFAULT_MAX_MATERIALIZED_ROWS,
            context=dict(payload.context or {}),
        )
    )
    return DeferredQueryResponse(
        job_id=accepted.job_id,
        result_set_id=accepted.result_set_id,
        effective_hash=accepted.effective_hash,
        field_dictionary_version=accepted.field_dictionary_version,
        max_rows=accepted.max_rows,
    )


# --------------------------------------------------------------------------- #
# Saved views                                                                 #
# --------------------------------------------------------------------------- #


@saved_views_router.get(
    "",
    response_model=SavedViewCollection,
    summary="List saved table views the caller may see",
    responses=ERROR_RESPONSES,
)
async def list_saved_views(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> SavedViewCollection:
    paged = await SavedViewService(container.query_services()).list(
        ListSavedViewsQuery(actor=caller.actor, request=context, page=page)
    )
    return SavedViewCollection(
        items=[saved_view_response(item) for item in paged.items],
        page=page_meta(paged),
    )


@saved_views_router.post(
    "",
    response_model=SavedViewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved table view",
    responses=ERROR_RESPONSES,
)
async def create_saved_view(
    payload: SavedViewCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> SavedViewResponse:
    view = await SavedViewService(container.query_services()).create(
        CreateSavedViewCommand(
            actor=caller.actor,
            request=context,
            name=payload.name,
            scope=parse_enum(QueryScope, payload.scope, field="scope"),
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            organization_id=payload.organization_id,
            description=payload.description,
            columns=tuple(payload.columns or ()),
            pinned_columns=tuple(payload.pinned_columns or ()),
            column_widths=payload.column_widths,
            sort_field_id=payload.sort_field_id,
            sort_descending=payload.sort_descending,
            page_size=payload.page_size,
            default_filter_definition_id=payload.default_filter_definition_id,
            default_filter_preset_id=payload.default_filter_preset_id,
            default_ranking_definition_id=payload.default_ranking_definition_id,
            default_ranking_preset_id=payload.default_ranking_preset_id,
        )
    )
    return saved_view_response(view)


@saved_views_router.get(
    "/{view_id}",
    response_model=SavedViewResponse,
    summary="Get a saved table view",
    responses=ERROR_RESPONSES,
)
async def get_saved_view(
    view_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> SavedViewResponse:
    view = await SavedViewService(container.query_services()).get(
        SavedViewQuery(actor=caller.actor, request=context, view_id=view_id)
    )
    return saved_view_response(view)


def _view_changes(payload: SavedViewUpdatePayload) -> dict[str, object]:
    """Only the keys the caller actually sent; omission is not a reset."""
    sent = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    changes: dict[str, object] = {}
    for key, value in sent.items():
        if value is None and key not in {
            "description",
            "sort_field_id",
            "default_filter_definition_id",
            "default_filter_preset_id",
            "default_ranking_definition_id",
            "default_ranking_preset_id",
        }:
            continue
        if key in {"columns", "pinned_columns"} and value is not None:
            changes[key] = tuple(value)
        else:
            changes[key] = value
    return changes


@saved_views_router.patch(
    "/{view_id}",
    response_model=SavedViewResponse,
    summary="Update a saved table view",
    responses=ERROR_RESPONSES,
)
async def update_saved_view(
    view_id: str,
    payload: SavedViewUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> SavedViewResponse:
    view = await SavedViewService(container.query_services()).update(
        UpdateSavedViewCommand(
            actor=caller.actor,
            request=context,
            view_id=view_id,
            expected_version=payload.expected_version,
            changes=_view_changes(payload),
        )
    )
    return saved_view_response(view)


@saved_views_router.delete(
    "/{view_id}",
    response_model=SavedViewResponse,
    summary="Soft-delete a saved table view",
    responses=ERROR_RESPONSES,
)
async def delete_saved_view(
    view_id: str,
    payload: SavedViewUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> SavedViewResponse:
    view = await SavedViewService(container.query_services()).delete(
        UpdateSavedViewCommand(
            actor=caller.actor,
            request=context,
            view_id=view_id,
            expected_version=payload.expected_version,
            changes={},
        )
    )
    return saved_view_response(view)


# --------------------------------------------------------------------------- #
# Administration                                                              #
# --------------------------------------------------------------------------- #


async def _require_platform_query_administration(services, caller, context) -> None:
    """Administration surfaces are platform-governed, and the denial is recorded."""
    now = services.clock.now()
    async with services.unit_of_work.begin() as repositories:
        recorder = ActivityRecorder(repositories, context)
        await services.authorization.require(
            caller.actor,
            Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
            recorder=recorder,
            occurred_at=now,
        )


@query_admin_router.get(
    "/filter-fields",
    response_model=FieldDictionaryResponse,
    summary="The complete filter-field registry, including unavailable fields",
    responses=ERROR_RESPONSES,
)
async def administer_filter_fields(
    caller: CallerDep, container: ContainerDep, context: RequestContextDep
) -> FieldDictionaryResponse:
    services = container.query_services()
    await _require_platform_query_administration(services, caller, context)
    registry = services.fields
    return FieldDictionaryResponse(
        version=registry.version,
        fields=[filter_field_response(item) for item in registry.definitions],
        result_set_id=None,
        available_field_ids=None,
    )


@query_admin_router.get(
    "/ranking-methods",
    response_model=RankingMethodCollection,
    summary="The complete ranking-method registry, including unavailable methods",
    responses=ERROR_RESPONSES,
)
async def administer_ranking_methods(
    caller: CallerDep, container: ContainerDep, context: RequestContextDep
) -> RankingMethodCollection:
    services = container.query_services()
    await _require_platform_query_administration(services, caller, context)
    return RankingMethodCollection(
        items=[ranking_method_response(method) for method in services.methods.methods]
    )


@query_admin_router.get(
    "/limits",
    response_model=QueryLimitsResponse,
    summary="The configured filtering and ranking safety limits",
    responses=ERROR_RESPONSES,
)
async def read_query_limits(
    caller: CallerDep, container: ContainerDep, context: RequestContextDep
) -> QueryLimitsResponse:
    del caller, context
    return query_limits_response(container.query_services())


__all__ = [
    "filter_fields_router",
    "filter_presets_router",
    "filters_router",
    "query_admin_router",
    "ranking_methods_router",
    "ranking_presets_router",
    "rankings_router",
    "saved_views_router",
    "variant_query_router",
]
