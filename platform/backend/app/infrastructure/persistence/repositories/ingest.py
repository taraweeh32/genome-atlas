"""Import-session, column-mapping and validation repositories.

Validation runs are append-only history: a re-validation inserts a new run
instead of rewriting the previous one, so "what was known when" survives. Issues
are written in one batch per run, because a partially recorded finding list would
misrepresent an outcome.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy import delete, insert, select

from app.application.repositories import Page, Paged
from app.domain.data.entities import (
    ColumnMapping,
    ImportSession,
    ValidationIssue,
    ValidationRun,
)
from app.domain.value_objects.enums import (
    FieldConcept,
    ImportSessionState,
    InputFormat,
    MappingOrigin,
    MappingStatus,
    ReferenceBuildDeclaration,
    ValidationCategory,
    ValidationRunState,
    ValidationSeverity,
    ValueSemantics,
)
from app.infrastructure.persistence.models.ingest import ImportSession as ImportSessionModel
from app.infrastructure.persistence.models.ingest import ValidationIssue as ValidationIssueModel
from app.infrastructure.persistence.models.ingest import ValidationRun as ValidationRunModel
from app.infrastructure.persistence.models.uploads import (
    DatasetColumnMapping as ColumnMappingModel,
)
from app.infrastructure.persistence.repositories.base import SqlRepository

_IMPORTS = ImportSessionModel.__table__
_MAPPINGS = ColumnMappingModel.__table__
_RUNS = ValidationRunModel.__table__
_ISSUES = ValidationIssueModel.__table__


def to_import_session(row: Mapping[str, Any]) -> ImportSession:
    return ImportSession(
        id=row["id"],
        workspace_id=row["workspace_id"],
        state=ImportSessionState(row["state"]),
        initiated_by=row["initiated_by"],
        project_id=row["project_id"],
        dataset_id=row["dataset_id"],
        dataset_version_id=row["dataset_version_id"],
        file_artifact_id=row["file_artifact_id"],
        declared_format=InputFormat(row["declared_format"]),
        detected_format=InputFormat(row["detected_format"]),
        reference_build_declared=ReferenceBuildDeclaration(row["reference_build_declared"]),
        mapping_metadata=row["mapping_metadata"] or {},
        import_provenance=row["import_provenance"] or {},
        importer_version=row["importer_version"],
        idempotency_key=row["idempotency_key"],
        mapping_confirmed_at=row["mapping_confirmed_at"],
        submitted_at=row["submitted_at"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        rejection_reason=row["rejection_reason"],
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
        version=row["version"],
    )


def to_column_mapping(row: Mapping[str, Any]) -> ColumnMapping:
    return ColumnMapping(
        id=row["id"],
        import_session_id=row["import_session_id"],
        source_column_name=row["source_column_name"],
        source_column_index=row["source_column_index"],
        status=MappingStatus(row["status"]),
        origin=MappingOrigin(row["origin"]),
        target_concept=FieldConcept(row["target_concept"]),
        declared_unit=row["declared_unit"],
        sample_value_semantics=ValueSemantics(row["sample_value_semantics"]),
        notes=row["notes"],
        created_at=row["created_at"],
    )


def to_validation_run(row: Mapping[str, Any]) -> ValidationRun:
    return ValidationRun(
        id=row["id"],
        state=ValidationRunState(row["state"]),
        validator_name=row["validator_name"],
        validator_version=row["validator_version"],
        import_session_id=row["import_session_id"],
        dataset_version_id=row["dataset_version_id"],
        file_artifact_id=row["file_artifact_id"],
        requested_by=row["requested_by"],
        correlation_id=row["correlation_id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        blocking_issue_count=row["blocking_issue_count"],
        error_issue_count=row["error_issue_count"],
        warning_issue_count=row["warning_issue_count"],
        info_issue_count=row["info_issue_count"],
        summary=row["summary"] or {},
        created_at=row["created_at"],
    )


def to_validation_issue(row: Mapping[str, Any]) -> ValidationIssue:
    return ValidationIssue(
        id=row["id"],
        validation_run_id=row["validation_run_id"],
        severity=ValidationSeverity(row["severity"]),
        category=ValidationCategory(row["category"]),
        code=row["code"],
        message=row["message"],
        validation_rule_id=row["validation_rule_id"],
        locator=row["locator"] or {},
        value_semantics=ValueSemantics(row["value_semantics"]),
        observed_value=row["observed_value"],
        details=row["details"] or {},
        created_at=row["created_at"],
    )


_SUBJECT_COLUMNS = {
    "file_artifact": _RUNS.c.file_artifact_id,
    "dataset_version": _RUNS.c.dataset_version_id,
    "import_session": _RUNS.c.import_session_id,
}


class SqlImportSessionRepository(SqlRepository):
    async def add(self, session: ImportSession) -> ImportSession:
        await self._session.execute(
            insert(_IMPORTS).values(
                id=session.id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                dataset_id=session.dataset_id,
                dataset_version_id=session.dataset_version_id,
                file_artifact_id=session.file_artifact_id,
                state=session.state.value,
                initiated_by=session.initiated_by,
                declared_format=session.declared_format.value,
                detected_format=session.detected_format.value,
                reference_build_declared=session.reference_build_declared.value,
                mapping_metadata=session.mapping_metadata,
                import_provenance=session.import_provenance,
                importer_version=session.importer_version,
                idempotency_key=session.idempotency_key,
                correlation_id=session.correlation_id,
                version=1,
            )
        )
        return session

    async def get(self, session_id: str) -> ImportSession | None:
        row = await self._fetch_one(select(_IMPORTS).where(_IMPORTS.c.id == session_id))
        return to_import_session(row) if row else None

    async def save(self, session: ImportSession) -> ImportSession:
        version = await self._versioned_update(
            _IMPORTS,
            entity_id=session.id,
            expected_version=session.version,
            values={
                "state": session.state.value,
                "dataset_version_id": session.dataset_version_id,
                "detected_format": session.detected_format.value,
                "reference_build_declared": session.reference_build_declared.value,
                "mapping_metadata": session.mapping_metadata,
                "import_provenance": session.import_provenance,
                "importer_version": session.importer_version,
                "mapping_confirmed_at": session.mapping_confirmed_at,
                "submitted_at": session.submitted_at,
                "decided_at": session.decided_at,
                "decided_by": session.decided_by,
                "rejection_reason": session.rejection_reason,
            },
        )
        return replace(session, version=version)

    async def get_by_idempotency_key(self, key: str) -> ImportSession | None:
        row = await self._fetch_one(
            select(_IMPORTS).where(_IMPORTS.c.idempotency_key == key)
        )
        return to_import_session(row) if row else None

    async def list_for_dataset(self, dataset_id: str, *, page: Page) -> Paged[ImportSession]:
        statement = (
            select(_IMPORTS)
            .where(_IMPORTS.c.dataset_id == dataset_id)
            .order_by(_IMPORTS.c.created_at.desc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_import_session(row) for row in rows), total, page)


class SqlColumnMappingRepository(SqlRepository):
    async def replace_all(
        self, import_session_id: str, mappings: tuple[ColumnMapping, ...]
    ) -> tuple[ColumnMapping, ...]:
        """Replace the mapping set for a still-open session.

        A mapping set is only meaningful as a whole, so it is rewritten
        atomically. Once a session is submitted the use case refuses to call
        this at all, which is what keeps a submitted import's configuration
        faithful to what was actually decided.
        """
        await self._session.execute(
            delete(_MAPPINGS).where(_MAPPINGS.c.import_session_id == import_session_id)
        )
        if not mappings:
            return ()
        await self._session.execute(
            insert(_MAPPINGS),
            [
                {
                    "id": mapping.id,
                    "import_session_id": mapping.import_session_id,
                    "source_column_name": mapping.source_column_name,
                    "source_column_index": mapping.source_column_index,
                    "status": mapping.status.value,
                    "origin": mapping.origin.value,
                    "target_concept": mapping.target_concept.value,
                    "declared_unit": mapping.declared_unit,
                    "sample_value_semantics": mapping.sample_value_semantics.value,
                    "notes": mapping.notes,
                }
                for mapping in mappings
            ],
        )
        return mappings

    async def list_for_session(self, import_session_id: str) -> tuple[ColumnMapping, ...]:
        rows = await self._fetch_all(
            select(_MAPPINGS)
            .where(_MAPPINGS.c.import_session_id == import_session_id)
            .order_by(_MAPPINGS.c.source_column_index.asc())
        )
        return tuple(to_column_mapping(row) for row in rows)


class SqlValidationRunRepository(SqlRepository):
    async def add(self, run: ValidationRun) -> ValidationRun:
        await self._session.execute(
            insert(_RUNS).values(
                id=run.id,
                import_session_id=run.import_session_id,
                dataset_version_id=run.dataset_version_id,
                file_artifact_id=run.file_artifact_id,
                state=run.state.value,
                requested_by=run.requested_by,
                validator_name=run.validator_name,
                validator_version=run.validator_version,
                correlation_id=run.correlation_id,
                started_at=run.started_at,
                completed_at=run.completed_at,
                blocking_issue_count=run.blocking_issue_count,
                error_issue_count=run.error_issue_count,
                warning_issue_count=run.warning_issue_count,
                info_issue_count=run.info_issue_count,
                summary=run.summary,
            )
        )
        return run

    async def get(self, run_id: str) -> ValidationRun | None:
        row = await self._fetch_one(select(_RUNS).where(_RUNS.c.id == run_id))
        return to_validation_run(row) if row else None

    async def save(self, run: ValidationRun) -> ValidationRun:
        await self._session.execute(
            _RUNS.update()
            .where(_RUNS.c.id == run.id)
            .values(
                state=run.state.value,
                started_at=run.started_at,
                completed_at=run.completed_at,
                blocking_issue_count=run.blocking_issue_count,
                error_issue_count=run.error_issue_count,
                warning_issue_count=run.warning_issue_count,
                info_issue_count=run.info_issue_count,
                summary=run.summary,
            )
        )
        return run

    async def list_for_subject(
        self, *, subject_type: str, subject_id: str, page: Page
    ) -> Paged[ValidationRun]:
        column = _SUBJECT_COLUMNS.get(subject_type)
        if column is None:
            return Paged((), 0, page)
        statement = (
            select(_RUNS).where(column == subject_id).order_by(_RUNS.c.created_at.desc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_validation_run(row) for row in rows), total, page)

    async def latest_for_subject(
        self, *, subject_type: str, subject_id: str
    ) -> ValidationRun | None:
        column = _SUBJECT_COLUMNS.get(subject_type)
        if column is None:
            return None
        row = await self._fetch_one(
            select(_RUNS).where(column == subject_id).order_by(_RUNS.c.created_at.desc())
        )
        return to_validation_run(row) if row else None


class SqlValidationIssueRepository(SqlRepository):
    async def add_many(self, issues: tuple[ValidationIssue, ...]) -> None:
        if not issues:
            return
        await self._session.execute(
            insert(_ISSUES),
            [
                {
                    "id": issue.id,
                    "validation_run_id": issue.validation_run_id,
                    "validation_rule_id": issue.validation_rule_id,
                    "severity": issue.severity.value,
                    "category": issue.category.value,
                    "code": issue.code,
                    "message": issue.message,
                    "locator": issue.locator,
                    "value_semantics": issue.value_semantics.value,
                    "observed_value": issue.observed_value,
                    "details": issue.details,
                }
                for issue in issues
            ],
        )

    async def list_for_run(self, run_id: str, *, page: Page) -> Paged[ValidationIssue]:
        statement = (
            select(_ISSUES)
            .where(_ISSUES.c.validation_run_id == run_id)
            .order_by(_ISSUES.c.created_at.asc(), _ISSUES.c.id.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_validation_issue(row) for row in rows), total, page)


__all__ = [
    "SqlColumnMappingRepository",
    "SqlImportSessionRepository",
    "SqlValidationIssueRepository",
    "SqlValidationRunRepository",
    "to_column_mapping",
    "to_import_session",
    "to_validation_issue",
    "to_validation_run",
]
