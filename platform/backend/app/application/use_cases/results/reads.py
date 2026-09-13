"""Reading, downloading and withdrawing result surfaces.

Reading is separated into three distinct capabilities on purpose:

* **metadata** — what this surface is, where it came from, whether it is usable;
* **content** — a bounded window of the materialized rows;
* **bytes** — a time-limited grant to download a produced artifact.

They are separate permissions because they are separate exposures. Someone who
may see that an analysis produced 40,000 rows does not automatically get the
file. And ``SUPERSEDED`` surfaces stay readable — a finalized historical report
must still resolve what it was built from — while ``INVALIDATED`` and ``FAILED``
ones do not, because the platform has stopped vouching for them.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports import AnalyticalPage
from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.results.dependencies import (
    RESULT_DOWNLOAD,
    RESULT_READ,
    ResultServices,
    readable_workspace_scope,
    require_result_access,
    result_capabilities,
)
from app.application.use_cases.results.ingestion import ResultSetView
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

#: The largest window a single content read may return. Presentation reads are
#: paged; bulk extraction is an authorized, durable export, not a wide page.
MAX_CONTENT_ROWS = 500
from app.domain.events import EventType
from app.domain.value_objects.enums import AuditOutcome, ResultSetState
from app.domain.variant.results import ResultArtifactRecord


@dataclass(frozen=True, slots=True)
class ListResultSetsQuery:
    actor: ActorContext
    request: RequestContext
    page: Page
    workspace_id: str | None = None
    project_id: str | None = None
    analysis_execution_id: str | None = None
    states: tuple[ResultSetState, ...] = ()


class ListResultSets:
    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, query: ListResultSetsQuery) -> Paged:
        async with self._services.unit_of_work.begin() as repositories:
            workspace_ids = readable_workspace_scope(
                query.actor, workspace_id=query.workspace_id
            )
            if query.workspace_id is not None and not workspace_ids:
                # An explicit request for a workspace the caller cannot read is
                # refused rather than answered with an empty page: "you may not
                # look here" and "there is nothing here" are different answers.
                raise AuthorizationError(
                    "you may not read results in this workspace",
                    details={"workspace_id": query.workspace_id},
                )
            page = await repositories.result_sets.list_for_scope(
                workspace_ids=workspace_ids,
                page=query.page,
                project_id=query.project_id,
                analysis_execution_id=query.analysis_execution_id,
                states=query.states,
            )
        return page


@dataclass(frozen=True, slots=True)
class GetResultSetQuery:
    actor: ActorContext
    result_set_id: str
    request: RequestContext


class GetResultSet:
    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, query: GetResultSetQuery) -> ResultSetView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            result_set = await repositories.result_sets.get(query.result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", query.result_set_id)
            scope = await require_result_access(
                self._services,
                repositories,
                query.actor,
                result_set,
                action=RESULT_READ,
                recorder=recorder,
                occurred_at=now,
            )
            artifacts = await repositories.result_artifacts.list_for_result_set(
                result_set.id
            )
        return ResultSetView(
            result_set=result_set,
            artifacts=artifacts,
            capabilities=result_capabilities(scope.actor, result_set),
        )


@dataclass(frozen=True, slots=True)
class ReadResultPageQuery:
    actor: ActorContext
    result_set_id: str
    request: RequestContext
    offset: int = 0
    limit: int = 100


@dataclass(frozen=True, slots=True)
class ResultContentView:
    result_set_id: str
    page: AnalyticalPage
    is_development_payload: bool
    state: ResultSetState


class ReadResultPage:
    """Returns a bounded window of a materialized surface."""

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, query: ReadResultPageQuery) -> ResultContentView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            result_set = await repositories.result_sets.get(query.result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", query.result_set_id)
            await require_result_access(
                self._services,
                repositories,
                query.actor,
                result_set,
                action=RESULT_READ,
                recorder=recorder,
                occurred_at=now,
            )
            if not result_set.is_readable:
                # The state is the reason, and it is reported as such: a withdrawn
                # or failed surface is not silently returned as empty.
                raise ConflictError(
                    "this result surface is not readable",
                    details={
                        "state": result_set.state.value,
                        "invalidation_reason": result_set.invalidation_reason,
                        "failure_code": result_set.failure_code,
                    },
                )
            if result_set.analytical_location is None or self._services.analytics is None:
                raise ConflictError(
                    "this result set has no materialized content to read",
                    details={"state": result_set.state.value},
                )
            page = await self._services.analytics.read_page(
                result_set.analytical_location,
                offset=max(query.offset, 0),
                # Bounded here as well as in the reader: an unbounded read of a
                # genomic surface is a denial-of-service shape, and the caller
                # does not get to choose.
                limit=min(max(query.limit, 1), MAX_CONTENT_ROWS),
            )
        return ResultContentView(
            result_set_id=result_set.id,
            page=page,
            is_development_payload=bool(
                (result_set.metadata or {}).get("is_development_payload")
            ),
            state=result_set.state,
        )


@dataclass(frozen=True, slots=True)
class AuthorizeArtifactDownloadCommand:
    actor: ActorContext
    artifact_id: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class ArtifactDownloadGrant:
    artifact: ResultArtifactRecord
    url: str
    expires_in_seconds: int


class AuthorizeArtifactDownload:
    """Issues a short-lived transfer grant for a verified artifact.

    Only ``ACCEPTED``/``SUPERSEDED`` artifacts are downloadable. Handing out bytes
    that failed verification would make the verification step decorative, and the
    grant is audited because a genomic artifact leaving the platform is exactly
    the event an audit trail exists for.
    """

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, command: AuthorizeArtifactDownloadCommand) -> ArtifactDownloadGrant:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            artifact = await repositories.result_artifacts.get(command.artifact_id)
            if artifact is None:
                raise NotFoundError("result_artifact", command.artifact_id)
            result_set = await repositories.result_sets.get(artifact.result_set_id)
            if result_set is None:
                raise NotFoundError("result_artifact", command.artifact_id)
            scope = await require_result_access(
                self._services,
                repositories,
                command.actor,
                result_set,
                action=RESULT_DOWNLOAD,
                recorder=recorder,
                occurred_at=now,
            )
            if not artifact.is_readable:
                raise ConflictError(
                    "this artifact has not been verified",
                    details={"state": artifact.state.value},
                )
            if artifact.storage_uri is None or self._services.object_storage is None:
                raise ConflictError(
                    "this artifact has no downloadable bytes",
                    details={"artifact_key": artifact.artifact_key},
                )
            expires = self._services.download_url_seconds
            url = await self._services.object_storage.presign_download(
                artifact.storage_uri,
                expires_seconds=expires,
                filename=artifact.artifact_key,
            )
            await recorder.audit(
                action="result_artifact.download_authorized",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="result_artifact",
                resource_id=artifact.id,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                detail={
                    "result_set_id": result_set.id,
                    "artifact_key": artifact.artifact_key,
                    "expires_in_seconds": expires,
                },
            )
            await recorder.event(
                event_type=EventType.RESULT_ARTIFACT_DOWNLOAD_AUTHORIZED,
                aggregate_type="result_artifact",
                aggregate_id=artifact.id,
                occurred_at=now,
                workspace_id=result_set.workspace_id,
                payload={"result_set_id": result_set.id},
            )
        return ArtifactDownloadGrant(
            artifact=artifact, url=url, expires_in_seconds=expires
        )


@dataclass(frozen=True, slots=True)
class InvalidateResultSetCommand:
    actor: ActorContext
    result_set_id: str
    reason: str
    request: RequestContext


class InvalidateResultSet:
    """Withdraws a result surface without altering a byte of its content.

    Used when an input is withdrawn or a scientific resource turns out to be
    defective. Content immutability and presentability are different properties:
    the rows stay exactly as produced, and the platform records that it no longer
    presents them as usable, together with the reason.
    """

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, command: InvalidateResultSetCommand) -> ResultSetView:
        now = self._services.clock.now()
        if not command.reason.strip():
            raise ValidationError(
                "invalidating a result requires a recorded reason",
                details={"field": "reason"},
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            result_set = await repositories.result_sets.get(command.result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", command.result_set_id)
            # Withdrawal is a platform-level scientific-data action: it affects
            # every report and interpretation built on the surface, so it is not
            # a tenant-role capability.
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_RESULT_ADMINISTER,
                recorder=recorder,
                occurred_at=now,
            )
            invalidated = await repositories.result_sets.save(
                result_set.invalidated(reason=command.reason)
            )
            await recorder.audit(
                action="result_set.invalidated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="result_set",
                resource_id=invalidated.id,
                workspace_id=invalidated.workspace_id,
                project_id=invalidated.project_id,
                previous_state=result_set.state.value,
                new_state=invalidated.state.value,
                detail={"reason": command.reason},
            )
            await recorder.event(
                event_type=EventType.RESULT_SET_INVALIDATED,
                aggregate_type="result_set",
                aggregate_id=invalidated.id,
                occurred_at=now,
                workspace_id=invalidated.workspace_id,
                payload={"reason": command.reason},
            )
            artifacts = await repositories.result_artifacts.list_for_result_set(
                invalidated.id
            )
        return ResultSetView(result_set=invalidated, artifacts=artifacts)


@dataclass(frozen=True, slots=True)
class SupersedeResultSetCommand:
    actor: ActorContext
    result_set_id: str
    superseded_by_result_set_id: str
    request: RequestContext


class SupersedeResultSet:
    """Records that a newer surface replaced an older one for the same result key.

    Supersession is explicit rather than inferred. The platform will not guess
    that a re-run's output replaces an earlier one — lineage that a machine
    guessed is lineage nobody can defend — so the link is stated, checked
    (same result key, same analysis lineage, no self-reference) and audited.
    Both rows survive: the older one stays readable so historical reports resolve.
    """

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    async def execute(self, command: SupersedeResultSetCommand) -> ResultSetView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            older = await repositories.result_sets.get(command.result_set_id)
            newer = await repositories.result_sets.get(command.superseded_by_result_set_id)
            if older is None:
                raise NotFoundError("result_set", command.result_set_id)
            if newer is None:
                raise NotFoundError("result_set", command.superseded_by_result_set_id)
            await require_result_access(
                self._services,
                repositories,
                command.actor,
                older,
                action=RESULT_DOWNLOAD,
                recorder=recorder,
                occurred_at=now,
            )
            if newer.result_key != older.result_key:
                raise ValidationError(
                    "a result set can only be superseded by one holding the same result key",
                    details={"field": "superseded_by_result_set_id"},
                )
            if newer.workspace_id != older.workspace_id:
                raise ValidationError(
                    "result sets in different workspaces cannot supersede each other",
                    details={"field": "superseded_by_result_set_id"},
                )
            if newer.state is not ResultSetState.AVAILABLE:
                raise ConflictError(
                    "only an available result set can supersede another",
                    details={"state": newer.state.value},
                )
            superseded = await repositories.result_sets.save(
                older.superseded_by(result_set_id=newer.id)
            )
            await recorder.audit(
                action="result_set.superseded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="result_set",
                resource_id=superseded.id,
                workspace_id=superseded.workspace_id,
                project_id=superseded.project_id,
                previous_state=older.state.value,
                new_state=superseded.state.value,
                detail={"superseded_by_result_set_id": newer.id},
            )
            await recorder.event(
                event_type=EventType.RESULT_SET_SUPERSEDED,
                aggregate_type="result_set",
                aggregate_id=superseded.id,
                occurred_at=now,
                workspace_id=superseded.workspace_id,
                payload={"superseded_by_result_set_id": newer.id},
            )
            artifacts = await repositories.result_artifacts.list_for_result_set(
                superseded.id
            )
        return ResultSetView(result_set=superseded, artifacts=artifacts)


__all__ = [
    "ArtifactDownloadGrant",
    "AuthorizeArtifactDownload",
    "AuthorizeArtifactDownloadCommand",
    "GetResultSet",
    "GetResultSetQuery",
    "InvalidateResultSet",
    "InvalidateResultSetCommand",
    "ListResultSets",
    "ListResultSetsQuery",
    "ReadResultPage",
    "ReadResultPageQuery",
    "ResultContentView",
    "SupersedeResultSet",
    "SupersedeResultSetCommand",
]
