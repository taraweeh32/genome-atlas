"""Shared dependencies and governance for the annotation use cases.

Annotation resources and profiles are **platform-governed**: they are versioned
scientific identities, not tenant content, so registering, activating or retiring
one requires the platform annotation-administration permission and nothing else
grants it. Ordinary users read them.

Annotation *runs and results* are tenant content: they belong to the workspace or
project of the surface they annotate. Their scope always comes from that surface's
row, never from the request, which is what stops a known result-set identifier
from becoming a cross-tenant write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.services.authorization import AuthorizationService
from app.application.services.recorder import ActivityRecorder
from app.core.app_config import ApplicationSettings
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import NotFoundError


@dataclass(frozen=True)
class AnnotationServices:
    """The dependency bundle every annotation use case shares."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    #: The only door to the scientific compute subsystem. Optional so that
    #: registry and profile management need no scientific wiring at all.
    scientific: Any | None = None
    #: Composed filter field dictionary, invalidated when the registry changes.
    dictionary: Any | None = None
    #: Verifies that a declared artifact checksum matches the stored bytes.
    checksums: Any | None = None
    software_version: str = "package-8"


@dataclass(frozen=True, slots=True)
class ScopedPermission:
    workspace: Permission
    project: Permission


ANNOTATION_READ = ScopedPermission(
    Permission.WORKSPACE_ANNOTATION_READ, Permission.PROJECT_ANNOTATION_READ
)
ANNOTATION_EXECUTE = ScopedPermission(
    Permission.WORKSPACE_ANNOTATION_EXECUTE, Permission.PROJECT_ANNOTATION_EXECUTE
)

PLATFORM_ADMINISTER = Permission.PLATFORM_ANNOTATION_RESOURCE_ADMINISTER
PLATFORM_READ = Permission.PLATFORM_ANNOTATION_READ


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str
    project_id: str | None


async def require_platform_administration(
    services: AnnotationServices,
    repositories: Any,
    actor: ActorContext,
    *,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> None:
    """Registry governance is platform-level. No tenant role substitutes for it."""
    await services.authorization.require(
        actor,
        PLATFORM_ADMINISTER,
        recorder=recorder,
        occurred_at=occurred_at,
    )


async def resolve_scope(
    services: AnnotationServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the annotated surface itself declares."""
    if project_id is not None:
        actor = await services.authorization.ensure_project_scope(
            repositories, actor, project_id
        )
        await services.authorization.require(
            actor,
            action.project,
            recorder=recorder,
            occurred_at=occurred_at,
            project_id=project_id,
        )
    else:
        await services.authorization.require(
            actor,
            action.workspace,
            recorder=recorder,
            occurred_at=occurred_at,
            workspace_id=workspace_id,
        )
    return ResolvedScope(actor=actor, workspace_id=workspace_id, project_id=project_id)


@dataclass(frozen=True, slots=True)
class AnnotatedSurface:
    """The surface a run annotates, with the tenancy it carries."""

    workspace_id: str
    project_id: str | None
    result_set_id: str | None = None
    dataset_version_id: str | None = None
    analytical_location: str | None = None
    genome_assembly: str | None = None
    input_kind: str = "result_set"


async def resolve_surface(
    repositories: Any,
    *,
    result_set_id: str | None,
    dataset_version_id: str | None,
) -> AnnotatedSurface:
    """Load the annotated surface and take its tenancy from the stored row."""
    if result_set_id is not None:
        result_set = await repositories.result_sets.get(result_set_id)
        if result_set is None:
            raise NotFoundError("result_set", result_set_id)
        provenance = getattr(result_set, "provenance", None)
        return AnnotatedSurface(
            workspace_id=result_set.workspace_id,
            project_id=result_set.project_id,
            result_set_id=result_set.id,
            analytical_location=result_set.analytical_location,
            genome_assembly=(
                getattr(provenance, "genome_assembly", None) if provenance else None
            ),
            input_kind="result_set",
        )
    if dataset_version_id is not None:
        version = await repositories.dataset_versions.get(dataset_version_id)
        if version is None:
            raise NotFoundError("dataset_version", dataset_version_id)
        dataset = await repositories.datasets.get(version.dataset_id)
        if dataset is None:
            raise NotFoundError("dataset_version", dataset_version_id)
        return AnnotatedSurface(
            workspace_id=dataset.workspace_id,
            project_id=dataset.project_id,
            dataset_version_id=version.id,
            genome_assembly=getattr(version, "genome_assembly", None),
            input_kind="dataset_version",
        )
    raise NotFoundError("annotation_surface", "unspecified")


def readable_workspace_scope(
    actor: ActorContext,
    *,
    workspace_id: str | None = None,
    action: ScopedPermission = ANNOTATION_READ,
) -> tuple[str, ...]:
    """Workspaces the actor may read annotation runs in.

    Built from grants the platform holds, never from identifiers the client sent,
    so a listing physically cannot reach another tenant's runs.
    """
    direct = tuple(
        candidate
        for candidate in actor.workspaces
        if action.workspace in actor.workspace_capabilities(candidate)
        and (workspace_id is None or candidate == workspace_id)
    )
    through_projects = tuple(
        grant.workspace_id
        for project_id, grant in actor.projects.items()
        if action.project in actor.project_capabilities(project_id)
        and (workspace_id is None or grant.workspace_id == workspace_id)
    )
    return tuple(dict.fromkeys(direct + through_projects))


__all__ = [
    "ANNOTATION_EXECUTE",
    "ANNOTATION_READ",
    "PLATFORM_ADMINISTER",
    "PLATFORM_READ",
    "AnnotatedSurface",
    "AnnotationServices",
    "ResolvedScope",
    "ScopedPermission",
    "readable_workspace_scope",
    "require_platform_administration",
    "resolve_scope",
    "resolve_surface",
]
