"""Variant and result-surface endpoints.

Thin handlers, as everywhere else: parse transport input, hand an explicit command
to a use case, shape the result. No handler decides access, a state transition or
a scope.

Three boundaries are visible in the layout:

* **Metadata, content and bytes are three endpoints with three permissions.**
  Listing result sets, reading a window of rows, and obtaining a download grant
  are separate exposures and are authorized separately.
* **A variant is always read through a dataset version.** Canonical variants are
  shared across tenants, so ``dataset_version_id`` is required — it is what makes
  the read authorizable at all.
* **Withdrawal is administrative.** Invalidating a surface affects every report
  built on it, so it sits behind a platform permission, and it never edits content.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.result_mapping import (
    artifact_response,
    result_content_response,
    result_set_response,
    variant_detail_response,
    variant_response,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.results import (
    ArtifactDownloadResponse,
    ResultContentResponse,
    ResultInvalidatePayload,
    ResultSetCollection,
    ResultSetResponse,
    ResultSupersedePayload,
    VariantCollection,
    VariantDetailResponse,
)
from app.application.use_cases.results.reads import (
    AuthorizeArtifactDownload,
    AuthorizeArtifactDownloadCommand,
    GetResultSet,
    GetResultSetQuery,
    InvalidateResultSet,
    InvalidateResultSetCommand,
    ListResultSets,
    ListResultSetsQuery,
    ReadResultPage,
    ReadResultPageQuery,
    SupersedeResultSet,
    SupersedeResultSetCommand,
)
from app.application.use_cases.results.variants import (
    GetVariant,
    GetVariantQuery,
    ListDatasetVersionVariants,
    ListDatasetVersionVariantsQuery,
)
from app.domain.value_objects.enums import ResultSetState

router = APIRouter(prefix="/result-sets", tags=["results"])
variants_router = APIRouter(prefix="/variants", tags=["variants"])
platform_results_router = APIRouter(
    prefix="/administration/result-sets", tags=["administration"]
)


@router.get(
    "",
    response_model=ResultSetCollection,
    summary="List result sets in a workspace or project",
    responses=ERROR_RESPONSES,
)
async def list_result_sets(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    analysis_execution_id: Annotated[str | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
) -> ResultSetCollection:
    paged = await ListResultSets(container.result_services()).execute(
        ListResultSetsQuery(
            actor=caller.actor,
            request=context,
            page=page,
            workspace_id=workspace_id,
            project_id=project_id,
            analysis_execution_id=analysis_execution_id,
            states=tuple(
                parse_enum(ResultSetState, item, field="state") for item in state or ()
            ),
        )
    )
    return ResultSetCollection(
        items=[result_set_response(item) for item in paged.items], page=page_meta(paged)
    )


@router.get(
    "/{result_set_id}",
    response_model=ResultSetResponse,
    summary="Get a result set with its artifacts and provenance",
    responses=ERROR_RESPONSES,
)
async def get_result_set(
    result_set_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ResultSetResponse:
    view = await GetResultSet(container.result_services()).execute(
        GetResultSetQuery(
            actor=caller.actor, result_set_id=result_set_id, request=context
        )
    )
    return result_set_response(
        view.result_set, artifacts=view.artifacts, capabilities=view.capabilities
    )


@router.get(
    "/{result_set_id}/content",
    response_model=ResultContentResponse,
    summary="Read a bounded window of a materialized result surface",
    responses=ERROR_RESPONSES,
)
async def read_result_content(
    result_set_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ResultContentResponse:
    view = await ReadResultPage(container.result_services()).execute(
        ReadResultPageQuery(
            actor=caller.actor,
            result_set_id=result_set_id,
            request=context,
            offset=offset,
            limit=limit,
        )
    )
    return result_content_response(view, offset=offset)


@router.post(
    "/{result_set_id}/artifacts/{artifact_id}/download",
    response_model=ArtifactDownloadResponse,
    summary="Obtain a short-lived download grant for a verified artifact",
    responses=ERROR_RESPONSES,
)
async def download_artifact(
    result_set_id: str,
    artifact_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ArtifactDownloadResponse:
    grant = await AuthorizeArtifactDownload(container.result_services()).execute(
        AuthorizeArtifactDownloadCommand(
            actor=caller.actor, artifact_id=artifact_id, request=context
        )
    )
    return ArtifactDownloadResponse(
        artifact_id=grant.artifact.id,
        artifact_key=grant.artifact.artifact_key,
        url=grant.url,
        expires_in_seconds=grant.expires_in_seconds,
    )


@router.post(
    "/{result_set_id}/supersede",
    response_model=ResultSetResponse,
    summary="Record that a newer result set replaced this one",
    responses=ERROR_RESPONSES,
)
async def supersede_result_set(
    result_set_id: str,
    payload: ResultSupersedePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ResultSetResponse:
    view = await SupersedeResultSet(container.result_services()).execute(
        SupersedeResultSetCommand(
            actor=caller.actor,
            result_set_id=result_set_id,
            superseded_by_result_set_id=payload.superseded_by_result_set_id,
            request=context,
        )
    )
    return result_set_response(view.result_set, artifacts=view.artifacts)


@platform_results_router.post(
    "/{result_set_id}/invalidate",
    response_model=ResultSetResponse,
    status_code=status.HTTP_200_OK,
    summary="Withdraw a result surface without altering its content",
    responses=ERROR_RESPONSES,
)
async def invalidate_result_set(
    result_set_id: str,
    payload: ResultInvalidatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ResultSetResponse:
    view = await InvalidateResultSet(container.result_services()).execute(
        InvalidateResultSetCommand(
            actor=caller.actor,
            result_set_id=result_set_id,
            reason=payload.reason,
            request=context,
        )
    )
    return result_set_response(view.result_set, artifacts=view.artifacts)


# --------------------------------------------------------------------------- #
# Variants                                                                    #
# --------------------------------------------------------------------------- #


@variants_router.get(
    "",
    response_model=VariantCollection,
    summary="List the variants recorded for a dataset version",
    responses=ERROR_RESPONSES,
)
async def list_variants(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    dataset_version_id: Annotated[str, Query()],
    contig: Annotated[str | None, Query(max_length=64)] = None,
    position_from: Annotated[int | None, Query(ge=0)] = None,
    position_to: Annotated[int | None, Query(ge=0)] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> VariantCollection:
    paged = await ListDatasetVersionVariants(container.result_services()).execute(
        ListDatasetVersionVariantsQuery(
            actor=caller.actor,
            dataset_version_id=dataset_version_id,
            request=context,
            page=page,
            contig=contig,
            position_from=position_from,
            position_to=position_to,
            query=query,
        )
    )
    return VariantCollection(
        items=[variant_response(item) for item in paged.items], page=page_meta(paged)
    )


@variants_router.get(
    "/{variant_id}",
    response_model=VariantDetailResponse,
    summary="Get a variant with every recorded context and its provenance",
    responses=ERROR_RESPONSES,
)
async def get_variant(
    variant_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    dataset_version_id: Annotated[str, Query()],
) -> VariantDetailResponse:
    view = await GetVariant(container.result_services()).execute(
        GetVariantQuery(
            actor=caller.actor,
            variant_id=variant_id,
            dataset_version_id=dataset_version_id,
            request=context,
        )
    )
    return variant_detail_response(view)


__all__ = ["platform_results_router", "router", "variants_router"]
