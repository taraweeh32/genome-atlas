"""Reading validation history.

Validation runs are append-only: re-validating an artifact adds a run rather than
rewriting the previous one, so "what was known when" survives. These queries
exist so a reviewer can see that history, scoped by the same permission that
governs the dataset the subject belongs to.

Findings are returned with their severity and category intact. The frontend
renders them; it never decides from them whether something may be accepted.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.data.dependencies import (
    READ,
    DataServices,
    require_dataset_access,
)
from app.domain.authorization.context import ActorContext
from app.domain.data.entities import Dataset, ValidationIssue, ValidationRun
from app.domain.errors import NotFoundError, ValidationError

#: Subjects a validation run may be attached to.
SUBJECT_TYPES = frozenset({"file_artifact", "dataset_version", "import_session"})


@dataclass(frozen=True, slots=True)
class ValidationRunView:
    run: ValidationRun
    issues: tuple[ValidationIssue, ...] = ()
    issue_total: int = 0


async def _dataset_for_run(repositories, run: ValidationRun) -> Dataset | None:
    """Find the dataset that governs access to a run, whatever it is attached to."""
    if run.dataset_version_id:
        version = await repositories.dataset_versions.get(run.dataset_version_id)
        if version is not None:
            return await repositories.datasets.get(version.dataset_id)
    if run.file_artifact_id:
        artifact = await repositories.file_artifacts.get(run.file_artifact_id)
        if artifact is not None and artifact.dataset_id:
            return await repositories.datasets.get(artifact.dataset_id)
    if run.import_session_id:
        session = await repositories.import_sessions.get(run.import_session_id)
        if session is not None and session.dataset_id:
            return await repositories.datasets.get(session.dataset_id)
    return None


@dataclass(frozen=True, slots=True)
class ListValidationRunsQuery:
    actor: ActorContext
    subject_type: str
    subject_id: str
    page: Page
    request: RequestContext


class ListValidationRuns:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: ListValidationRunsQuery) -> Paged[ValidationRun]:
        if query.subject_type not in SUBJECT_TYPES:
            raise ValidationError(
                "unsupported validation subject",
                details={"field": "subject_type", "allowed": sorted(SUBJECT_TYPES)},
            )
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            dataset = await self._resolve_subject_dataset(
                repositories, query.subject_type, query.subject_id
            )
            if dataset is None or not dataset.is_active:
                raise NotFoundError(query.subject_type, query.subject_id)
            await require_dataset_access(
                self._services,
                repositories,
                query.actor,
                dataset,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.validation_runs.list_for_subject(
                subject_type=query.subject_type, subject_id=query.subject_id, page=query.page
            )

    async def _resolve_subject_dataset(
        self,
        repositories,
        subject_type: str,
        subject_id: str,
    ) -> Dataset | None:
        if subject_type == "dataset_version":
            version = await repositories.dataset_versions.get(subject_id)
            return (
                await repositories.datasets.get(version.dataset_id)
                if version is not None
                else None
            )
        if subject_type == "file_artifact":
            artifact = await repositories.file_artifacts.get(subject_id)
            if artifact is None or artifact.dataset_id is None:
                return None
            return await repositories.datasets.get(artifact.dataset_id)
        session = await repositories.import_sessions.get(subject_id)
        if session is None or session.dataset_id is None:
            return None
        return await repositories.datasets.get(session.dataset_id)


@dataclass(frozen=True, slots=True)
class GetValidationRunQuery:
    actor: ActorContext
    run_id: str
    page: Page
    request: RequestContext


class GetValidationRun:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: GetValidationRunQuery) -> ValidationRunView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            run = await repositories.validation_runs.get(query.run_id)
            if run is None:
                raise NotFoundError("validation_run", query.run_id)
            dataset = await _dataset_for_run(repositories, run)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("validation_run", query.run_id)
            await require_dataset_access(
                self._services,
                repositories,
                query.actor,
                dataset,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            issues = await repositories.validation_issues.list_for_run(run.id, page=query.page)
        return ValidationRunView(run=run, issues=issues.items, issue_total=issues.total)


__all__ = [
    "SUBJECT_TYPES",
    "GetValidationRun",
    "GetValidationRunQuery",
    "ListValidationRuns",
    "ListValidationRunsQuery",
    "ValidationRunView",
]
