"""Annotation resource, profile, run and result endpoints.

Thin handlers, as everywhere else: parse transport input, hand an explicit command
to a use case, shape the result. No handler decides access, a state transition or a
scope.

Three boundaries are visible in the layout:

* **Registry and profiles are platform-governed, runs and results are tenant
  content.** Registering a resource version or publishing a profile sits under
  ``/administration``; requesting a run and reading its results is authorized
  through the workspace or project of the surface being annotated.
* **A delivery carries structured claims only.** The ingestion endpoint accepts
  values, artifact references and provenance — never a command, a path to execute
  or a scope. Scope comes from the run row.
* **Bulk values are not returned here.** A result version exposes counts,
  provenance and its analytical location; the values themselves are read through
  the paginated variant and filtering surfaces.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.annotation_mapping import (
    field_spec_from_payload,
    filter_field_response,
    ingestion_payload,
    profile_response,
    profile_version_response,
    resource_response,
    result_response,
    run_response,
)
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.schemas.annotation import (
    AnnotationFieldCollection,
    AnnotationIngestionResponse,
    AnnotationProfileCollection,
    AnnotationProfileResponse,
    AnnotationProfileVersionResponse,
    AnnotationResourceCollection,
    AnnotationResourceResponse,
    AnnotationResultCollection,
    AnnotationResultResponse,
    AnnotationRunCollection,
    AnnotationRunResponse,
    CreateProfilePayload,
    IngestAnnotationPayloadBody,
    ProfileVersionPayload,
    RegisterResourcePayload,
    RequestRunPayload,
    TransitionResourcePayload,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.application.use_cases.annotation.ingestion import (
    AnnotationResultReader,
    IngestAnnotationCommand,
    IngestAnnotationPayload,
)
from app.application.use_cases.annotation.profiles import (
    AnnotationProfileService,
    CreateProfileCommand,
    ProfileVersionInput,
)
from app.application.use_cases.annotation.resources import (
    AnnotationResourceCatalogue,
    ListResourcesQuery,
    RegisterAnnotationResource,
    RegisterResourceCommand,
    TransitionAnnotationResource,
    TransitionResourceCommand,
)
from app.application.use_cases.annotation.runs import (
    AnnotationRunReader,
    ListRunsQuery,
    RequestAnnotationRun,
    RequestRunCommand,
)
from app.domain.value_objects.enums import (
    AnnotationResourceCategory,
    AnnotationRunState,
    ScientificResourceState,
)

resources_router = APIRouter(prefix="/annotation-resources", tags=["annotation"])
fields_router = APIRouter(prefix="/annotation-fields", tags=["annotation"])
profiles_router = APIRouter(prefix="/annotation-profiles", tags=["annotation"])
runs_router = APIRouter(prefix="/annotation-runs", tags=["annotation"])
results_router = APIRouter(prefix="/annotation-results", tags=["annotation"])
admin_resources_router = APIRouter(
    prefix="/administration/annotation-resources", tags=["administration"]
)
admin_profiles_router = APIRouter(
    prefix="/administration/annotation-profiles", tags=["administration"]
)


# --------------------------------------------------------------------------- #
# Registry reads                                                              #
# --------------------------------------------------------------------------- #


@resources_router.get(
    "",
    response_model=AnnotationResourceCollection,
    summary="List registered annotation resource versions",
    responses=ERROR_RESPONSES,
)
async def list_annotation_resources(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    category: Annotated[str | None, Query()] = None,
    resource_key: Annotated[str | None, Query()] = None,
    usable_only: Annotated[bool, Query()] = False,
) -> AnnotationResourceCollection:
    paged = await AnnotationResourceCatalogue(container.annotation_services()).list(
        ListResourcesQuery(
            actor=caller.actor,
            request=context,
            page=page,
            category=parse_enum(AnnotationResourceCategory, category, field="category")
            if category
            else None,
            resource_key=resource_key,
            usable_only=usable_only,
        )
    )
    return AnnotationResourceCollection(
        items=[resource_response(item) for item in paged.items], page=page_meta(paged)
    )


@resources_router.get(
    "/{resource_id}",
    response_model=AnnotationResourceResponse,
    summary="Get one annotation resource version with its declared fields",
    responses=ERROR_RESPONSES,
)
async def get_annotation_resource(
    resource_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationResourceResponse:
    record = await AnnotationResourceCatalogue(container.annotation_services()).get(
        caller.actor, context, resource_id
    )
    return resource_response(record)


@fields_router.get(
    "",
    response_model=AnnotationFieldCollection,
    summary="List annotation fields currently offered to filtering and ranking",
    responses=ERROR_RESPONSES,
)
async def list_annotation_fields(
    caller: CallerDep, container: ContainerDep, context: RequestContextDep
) -> AnnotationFieldCollection:
    services = container.annotation_services()
    definitions = await AnnotationResourceCatalogue(services).fields(
        caller.actor, context
    )
    registry = await container.annotation_field_dictionary().refresh_if_stale(
        container.unit_of_work
    )
    return AnnotationFieldCollection(
        items=[filter_field_response(item) for item in definitions],
        registry_version=registry.version,
    )


# --------------------------------------------------------------------------- #
# Registry administration                                                     #
# --------------------------------------------------------------------------- #


@admin_resources_router.post(
    "",
    response_model=AnnotationResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an annotation resource version",
    responses=ERROR_RESPONSES,
)
async def register_annotation_resource(
    payload: RegisterResourcePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationResourceResponse:
    record = await RegisterAnnotationResource(container.annotation_services()).execute(
        RegisterResourceCommand(
            actor=caller.actor,
            request=context,
            resource_key=payload.resource_key,
            version=payload.version,
            display_name=payload.display_name,
            category=parse_enum(
                AnnotationResourceCategory, payload.category, field="category"
            ),
            provider=payload.provider,
            description=payload.description,
            genome_assembly=payload.genome_assembly,
            reference_genome_resource_id=payload.reference_genome_resource_id,
            release_label=payload.release_label,
            released_at=payload.released_at,
            schema_version=payload.schema_version,
            checksum_algorithm=payload.checksum_algorithm,
            checksum_value=payload.checksum_value,
            size_bytes=payload.size_bytes,
            fields=tuple(field_spec_from_payload(spec) for spec in payload.fields),
            provenance=payload.provenance,
            licensing=payload.licensing,
            metadata=payload.metadata,
        )
    )
    return resource_response(record)


@admin_resources_router.post(
    "/{resource_id}/state",
    response_model=AnnotationResourceResponse,
    summary="Activate, deprecate, retire or invalidate a resource version",
    responses=ERROR_RESPONSES,
)
async def transition_annotation_resource(
    resource_id: str,
    payload: TransitionResourcePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationResourceResponse:
    record = await TransitionAnnotationResource(
        container.annotation_services()
    ).execute(
        TransitionResourceCommand(
            actor=caller.actor,
            request=context,
            resource_id=resource_id,
            state=parse_enum(ScientificResourceState, payload.state, field="state"),
            reason=payload.reason,
        )
    )
    return resource_response(record)


# --------------------------------------------------------------------------- #
# Profiles                                                                    #
# --------------------------------------------------------------------------- #


def _version_input(payload: ProfileVersionPayload) -> ProfileVersionInput:
    return ProfileVersionInput(
        capability_id=payload.capability_id,
        resource_ids=tuple(payload.resource_ids),
        capability_version=payload.capability_version,
        engine_resource_id=payload.engine_resource_id,
        engine_version=payload.engine_version,
        genome_assembly=payload.genome_assembly,
        reference_genome_resource_id=payload.reference_genome_resource_id,
        required_inputs=tuple(payload.required_inputs)
        if payload.required_inputs
        else ProfileVersionInput.required_inputs,
        parameters=payload.parameters,
        provenance_requirements=tuple(payload.provenance_requirements)
        if payload.provenance_requirements
        else ProfileVersionInput.provenance_requirements,
        schema_version=payload.schema_version,
        change_note=payload.change_note,
        metadata=payload.metadata,
    )


@profiles_router.get(
    "",
    response_model=AnnotationProfileCollection,
    summary="List annotation execution profiles",
    responses=ERROR_RESPONSES,
)
async def list_annotation_profiles(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    offered_only: Annotated[bool, Query()] = False,
) -> AnnotationProfileCollection:
    paged = await AnnotationProfileService(container.annotation_services()).list(
        caller.actor, context, page, offered_only=offered_only
    )
    return AnnotationProfileCollection(
        items=[profile_response(item) for item in paged.items], page=page_meta(paged)
    )


@profiles_router.get(
    "/{profile_id}",
    response_model=AnnotationProfileResponse,
    summary="Get a profile with its immutable versions",
    responses=ERROR_RESPONSES,
)
async def get_annotation_profile(
    profile_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationProfileResponse:
    view = await AnnotationProfileService(container.annotation_services()).get(
        caller.actor, context, profile_id
    )
    return profile_response(view.profile, versions=view.versions)


@admin_profiles_router.post(
    "",
    response_model=AnnotationProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an annotation profile with its first version",
    responses=ERROR_RESPONSES,
)
async def create_annotation_profile(
    payload: CreateProfilePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationProfileResponse:
    view = await AnnotationProfileService(container.annotation_services()).create(
        CreateProfileCommand(
            actor=caller.actor,
            request=context,
            name=payload.name,
            version=_version_input(payload.version),
            description=payload.description,
            metadata=payload.metadata,
        )
    )
    return profile_response(view.profile, versions=view.versions)


@admin_profiles_router.post(
    "/{profile_id}/versions",
    response_model=AnnotationProfileVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append a new immutable profile version",
    responses=ERROR_RESPONSES,
)
async def add_annotation_profile_version(
    profile_id: str,
    payload: ProfileVersionPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationProfileVersionResponse:
    version = await AnnotationProfileService(
        container.annotation_services()
    ).add_version(caller.actor, context, profile_id, _version_input(payload))
    return profile_version_response(version)


@admin_profiles_router.post(
    "/{profile_id}/publish",
    response_model=AnnotationProfileResponse,
    summary="Publish a profile so runs may reference it",
    responses=ERROR_RESPONSES,
)
async def publish_annotation_profile(
    profile_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationProfileResponse:
    profile = await AnnotationProfileService(container.annotation_services()).publish(
        caller.actor, context, profile_id
    )
    return profile_response(profile)


@admin_profiles_router.post(
    "/{profile_id}/archive",
    response_model=AnnotationProfileResponse,
    summary="Archive a profile; existing runs and results stay readable",
    responses=ERROR_RESPONSES,
)
async def archive_annotation_profile(
    profile_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationProfileResponse:
    profile = await AnnotationProfileService(container.annotation_services()).archive(
        caller.actor, context, profile_id
    )
    return profile_response(profile)


# --------------------------------------------------------------------------- #
# Runs                                                                        #
# --------------------------------------------------------------------------- #


@runs_router.post(
    "",
    response_model=AnnotationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request annotation of a result surface or dataset version",
    responses=ERROR_RESPONSES,
)
async def request_annotation_run(
    payload: RequestRunPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationRunResponse:
    view = await RequestAnnotationRun(container.annotation_services()).execute(
        RequestRunCommand(
            actor=caller.actor,
            request=context,
            annotation_profile_id=payload.annotation_profile_id,
            result_set_id=payload.result_set_id,
            dataset_version_id=payload.dataset_version_id,
            profile_version_number=payload.profile_version_number,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
        )
    )
    return run_response(view.run, findings=view.findings)


@runs_router.get(
    "",
    response_model=AnnotationRunCollection,
    summary="List annotation runs the caller may read",
    responses=ERROR_RESPONSES,
)
async def list_annotation_runs(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    result_set_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> AnnotationRunCollection:
    paged = await AnnotationRunReader(container.annotation_services()).list(
        ListRunsQuery(
            actor=caller.actor,
            request=context,
            page=page,
            workspace_id=workspace_id,
            project_id=project_id,
            result_set_id=result_set_id,
            state=parse_enum(AnnotationRunState, state, field="state")
            if state
            else None,
        )
    )
    return AnnotationRunCollection(
        items=[run_response(item) for item in paged.items], page=page_meta(paged)
    )


@runs_router.get(
    "/{run_id}",
    response_model=AnnotationRunResponse,
    summary="Get an annotation run with its provenance and validation findings",
    responses=ERROR_RESPONSES,
)
async def get_annotation_run(
    run_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationRunResponse:
    view = await AnnotationRunReader(container.annotation_services()).get(
        caller.actor, context, run_id
    )
    return run_response(view.run, findings=view.findings)


@runs_router.post(
    "/{run_id}/cancel",
    response_model=AnnotationRunResponse,
    summary="Cancel an annotation run that has not finished",
    responses=ERROR_RESPONSES,
)
async def cancel_annotation_run(
    run_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationRunResponse:
    run = await AnnotationRunReader(container.annotation_services()).cancel(
        caller.actor, context, run_id
    )
    return run_response(run)


@runs_router.post(
    "/{run_id}/results",
    response_model=AnnotationIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Deliver an annotation payload produced for this run",
    responses=ERROR_RESPONSES,
)
async def ingest_annotation_result(
    run_id: str,
    payload: IngestAnnotationPayloadBody,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationIngestionResponse:
    view = await IngestAnnotationPayload(container.annotation_services()).execute(
        IngestAnnotationCommand(
            request=context,
            payload=ingestion_payload(payload, annotation_run_id=run_id),
            actor=caller.actor,
        )
    )
    return AnnotationIngestionResponse(
        result=result_response(view.result),
        stored_record_count=view.stored_record_count,
        rejected_record_count=view.rejected_record_count,
        findings=[dict(item) for item in view.findings],
    )


# --------------------------------------------------------------------------- #
# Result metadata                                                             #
# --------------------------------------------------------------------------- #


@results_router.get(
    "",
    response_model=AnnotationResultCollection,
    summary="List annotation result versions for a result surface",
    responses=ERROR_RESPONSES,
)
async def list_annotation_results(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    result_set_id: Annotated[str, Query()],
) -> AnnotationResultCollection:
    paged = await AnnotationResultReader(
        container.annotation_services()
    ).list_for_surface(
        caller.actor, context, result_set_id=result_set_id, page=page
    )
    return AnnotationResultCollection(
        items=[result_response(item) for item in paged.items], page=page_meta(paged)
    )


@results_router.get(
    "/{result_id}",
    response_model=AnnotationResultResponse,
    summary="Get one annotation result version with its full provenance",
    responses=ERROR_RESPONSES,
)
async def get_annotation_result(
    result_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AnnotationResultResponse:
    result = await AnnotationResultReader(container.annotation_services()).get(
        caller.actor, context, result_id
    )
    return result_response(result)


__all__ = [
    "admin_profiles_router",
    "admin_resources_router",
    "fields_router",
    "profiles_router",
    "resources_router",
    "results_router",
    "runs_router",
]
