"""Import sessions: what a source column *means*, decided by a human.

An import turns a verified artifact into a candidate dataset version. The
platform's job here is narrow and strict:

* Offer a suggested mapping so the screen is usable, and keep suggestions
  distinguishable from decisions forever (``MappingOrigin``).
* Refuse to submit an import whose mapping is incomplete, ambiguous, or missing a
  concept the dataset kind requires.
* Preserve the confirmed configuration verbatim for provenance, and keep the
  per-column decisions queryable as rows.
* Run the import as a durable job, and record its structural validation as a
  validation run.

What it deliberately does **not** do: normalize coordinates, interpret alleles,
resolve a reference build, or decide that a mapped column named ``chromosome``
contains valid contigs. Those are scientific operations that belong to the
scientific compute subsystem behind its versioned contract. An import that
succeeds here means "the declared structure is coherent and was recorded", never
"these variants are valid".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.data.dependencies import (
    IMPORT,
    READ,
    DataServices,
    require_dataset_access,
)
from app.domain.authorization.context import ActorContext
from app.domain.data.entities import (
    ColumnMapping,
    Dataset,
    ImportSession,
    ValidationIssue,
    ValidationRun,
    outcome_for,
)
from app.domain.data.formats import TABULAR_FORMATS
from app.domain.data.semantics import classify, is_absent
from app.domain.data.mapping import (
    MappingDecision,
    suggest_mapping,
    validate_mapping,
)
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.events import EventType
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    AuditOutcome,
    DatasetState,
    DatasetVersionState,
    FieldConcept,
    FileValidationState,
    ImportSessionState,
    InputFormat,
    JobKind,
    MappingOrigin,
    MappingStatus,
    ValidationCategory,
    ValidationRunState,
    ValidationSeverity,
    ValueSemantics,
)
from app.infrastructure.persistence.repositories.base import new_id

IMPORTER_NAME = "platform-tabular-importer"
IMPORTER_VERSION = "1"

STRUCTURE_VALIDATOR_NAME = "platform-import-structure-validator"
STRUCTURE_VALIDATOR_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ImportSessionView:
    session: ImportSession
    mappings: tuple[ColumnMapping, ...]
    latest_validation: ValidationRun | None = None
    #: Why this import cannot be submitted yet, or ``None`` when it can.
    submission_blocked_reason: str | None = None


def _submission_blocker(session: ImportSession, mappings: tuple[ColumnMapping, ...]) -> str | None:
    if session.state is not ImportSessionState.OPEN:
        return "not_open"
    if session.detected_format in TABULAR_FORMATS or session.detected_format is InputFormat.VCF:
        if not mappings:
            return "no_columns_inspected"
        if session.mapping_confirmed_at is None:
            return "mapping_not_confirmed"
        if any(mapping.status is MappingStatus.UNMAPPED for mapping in mappings):
            return "columns_unmapped"
    return None


async def _load_session_scope(
    services: DataServices,
    repositories,
    actor: ActorContext,
    session_id: str,
    *,
    action,
    recorder: ActivityRecorder,
    occurred_at,
) -> tuple[ImportSession, Dataset, str]:
    session = await repositories.import_sessions.get(session_id)
    if session is None or session.dataset_id is None:
        raise NotFoundError("import_session", session_id)
    dataset = await repositories.datasets.get(session.dataset_id)
    if dataset is None or not dataset.is_active:
        raise NotFoundError("import_session", session_id)
    scope = await require_dataset_access(
        services,
        repositories,
        actor,
        dataset,
        action=action,
        recorder=recorder,
        occurred_at=occurred_at,
    )
    actor_id = scope.actor.actor_id
    if actor_id is None:  # pragma: no cover
        raise AuthorizationError("authentication is required")
    return session, dataset, actor_id


# --------------------------------------------------------------------------- #
# Opening an import                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OpenImportSessionCommand:
    actor: ActorContext
    artifact_id: str
    idempotency_key: str | None
    request: RequestContext


class OpenImportSession:
    """Open an import over a verified artifact and offer a suggested mapping."""

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: OpenImportSessionCommand) -> ImportSessionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            artifact = await repositories.file_artifacts.get(command.artifact_id)
            if artifact is None or artifact.dataset_id is None:
                raise NotFoundError("file_artifact", command.artifact_id)
            dataset = await repositories.datasets.get(artifact.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("file_artifact", command.artifact_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=IMPORT,
                recorder=recorder,
                occurred_at=now,
            )
            actor_id = scope.actor.actor_id
            if actor_id is None:  # pragma: no cover
                raise AuthorizationError("authentication is required")
            if dataset.state is DatasetState.ARCHIVED:
                raise ConflictError("an archived dataset cannot be imported into")
            if command.idempotency_key:
                existing = await repositories.import_sessions.get_by_idempotency_key(
                    command.idempotency_key
                )
                if existing is not None:
                    mappings = await repositories.column_mappings.list_for_session(existing.id)
                    return ImportSessionView(
                        session=existing,
                        mappings=mappings,
                        submission_blocked_reason=_submission_blocker(existing, mappings),
                    )
            if not artifact.is_retrievable:
                raise ConflictError(
                    "this file has not completed verification and cannot be imported",
                    details={
                        "scan_state": artifact.scan_state.value,
                        "validation_state": artifact.validation_state.value,
                    },
                )
            if artifact.validation_state is not FileValidationState.VALID:
                raise ConflictError(
                    "this file did not pass verification and cannot be imported",
                    details={"validation_state": artifact.validation_state.value},
                )
            if artifact.dataset_version_id is None:  # pragma: no cover
                raise ConflictError("this file is not attached to a dataset version")
            version = await repositories.dataset_versions.get(artifact.dataset_version_id)
            if version is None:  # pragma: no cover
                raise NotFoundError("dataset_version", artifact.dataset_version_id)
            if version.state not in (
                DatasetVersionState.VALIDATING,
                DatasetVersionState.VALIDATED,
            ):
                raise ConflictError(
                    "this version is no longer open to import",
                    details={"version_state": version.state.value},
                )

            session = await repositories.import_sessions.add(
                ImportSession(
                    id=new_id("imp"),
                    workspace_id=dataset.workspace_id,
                    state=ImportSessionState.OPEN,
                    initiated_by=actor_id,
                    project_id=dataset.project_id,
                    dataset_id=dataset.id,
                    dataset_version_id=version.id,
                    file_artifact_id=artifact.id,
                    declared_format=artifact.declared_format,
                    detected_format=artifact.detected_format,
                    reference_build_declared=version.reference_build_declared,
                    importer_version=f"{IMPORTER_NAME}:{IMPORTER_VERSION}",
                    idempotency_key=command.idempotency_key,
                    correlation_id=command.request.correlation_id,
                )
            )
            await recorder.audit(
                action="import_session.opened",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="import_session",
                resource_id=session.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                new_state=session.state.value,
                detail={"file_artifact_id": artifact.id},
            )
            await recorder.event(
                event_type=EventType.IMPORT_SESSION_OPENED,
                aggregate_type="import_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
                idempotency_suffix=session.id,
            )
            storage_key = artifact.storage_key
            filename = artifact.filename

        # Inspection happens outside the transaction: it reads object storage.
        inspection = await self._services.inspector.inspect(
            storage_key, declared_filename=filename
        )
        suggestions = suggest_mapping([column.name for column in inspection.columns])
        semantics_by_index = {
            column.index: (
                ValueSemantics.MISSING
                if column.non_empty_sample_count == 0 and inspection.sampled_record_count
                else ValueSemantics.PRESENT
            )
            for column in inspection.columns
        }

        async with self._services.unit_of_work.begin() as repositories:
            mappings = await repositories.column_mappings.replace_all(
                session.id,
                tuple(
                    ColumnMapping(
                        id=new_id("dcm"),
                        import_session_id=session.id,
                        source_column_name=decision.source_column_name,
                        source_column_index=decision.source_column_index,
                        # A suggestion is recorded as unmapped until a human
                        # confirms it: an import must never run on a guess.
                        status=(
                            MappingStatus.UNMAPPED
                            if decision.target_concept is FieldConcept.IGNORED
                            else MappingStatus.MAPPED
                        ),
                        origin=MappingOrigin.SYSTEM_SUGGESTED,
                        target_concept=decision.target_concept,
                        sample_value_semantics=semantics_by_index.get(
                            decision.source_column_index, ValueSemantics.PRESENT
                        ),
                    )
                    for decision in suggestions
                ),
            )
            session = await repositories.import_sessions.save(
                replace(
                    session,
                    detected_format=inspection.detected_format,
                    import_provenance={
                        "inspector_version": self._services.inspector.version,
                        "detected_format": inspection.detected_format.value,
                        "compression": inspection.compression.value,
                        "header_line_count": inspection.header_line_count,
                        "sampled_record_count": inspection.sampled_record_count,
                        "coverage": (
                            "bounded_prefix" if inspection.truncated else "complete_object"
                        ),
                        "problems": list(inspection.problems),
                    },
                )
            )
        return ImportSessionView(
            session=session,
            mappings=mappings,
            submission_blocked_reason=_submission_blocker(session, mappings),
        )


# --------------------------------------------------------------------------- #
# Reading                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GetImportSessionQuery:
    actor: ActorContext
    session_id: str
    request: RequestContext


class GetImportSession:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: GetImportSessionQuery) -> ImportSessionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            session, _dataset, _actor_id = await _load_session_scope(
                self._services,
                repositories,
                query.actor,
                query.session_id,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            mappings = await repositories.column_mappings.list_for_session(session.id)
            validation = await repositories.validation_runs.latest_for_subject(
                subject_type="import_session", subject_id=session.id
            )
        return ImportSessionView(
            session=session,
            mappings=mappings,
            latest_validation=validation,
            submission_blocked_reason=_submission_blocker(session, mappings),
        )


@dataclass(frozen=True, slots=True)
class ListImportSessionsQuery:
    actor: ActorContext
    dataset_id: str
    page: Page
    request: RequestContext


class ListImportSessions:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: ListImportSessionsQuery) -> Paged[ImportSession]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            dataset = await repositories.datasets.get(query.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset", query.dataset_id)
            await require_dataset_access(
                self._services,
                repositories,
                query.actor,
                dataset,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.import_sessions.list_for_dataset(
                dataset.id, page=query.page
            )


# --------------------------------------------------------------------------- #
# Confirming the mapping                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ColumnMappingRequest:
    source_column_index: int
    source_column_name: str
    target_concept: FieldConcept
    declared_unit: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmColumnMappingCommand:
    actor: ActorContext
    session_id: str
    decisions: tuple[ColumnMappingRequest, ...]
    request: RequestContext


class ConfirmColumnMapping:
    """Record the submitter's mapping decisions.

    The whole set is replaced atomically, because a mapping is only meaningful as
    a whole. Every row is written with ``USER_SELECTED`` origin: after this, the
    platform can always tell which decisions a person made and which it merely
    proposed.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: ConfirmColumnMappingCommand) -> ImportSessionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            session, dataset, actor_id = await _load_session_scope(
                self._services,
                repositories,
                command.actor,
                command.session_id,
                action=IMPORT,
                recorder=recorder,
                occurred_at=now,
            )
            if session.state is not ImportSessionState.OPEN:
                # A submitted import's configuration is provenance and is never
                # edited in place; re-importing opens a new session.
                raise ConflictError(
                    "this import is no longer open for mapping changes",
                    details={"state": session.state.value},
                )
            inspected = await repositories.column_mappings.list_for_session(session.id)
            if not inspected:
                raise ConflictError("no source columns were inspected for this import")
            headers = [mapping.source_column_name for mapping in inspected]
            semantics = {
                mapping.source_column_index: mapping.sample_value_semantics
                for mapping in inspected
            }
            decisions = validate_mapping(
                kind=dataset.kind,
                headers=headers,
                decisions=[
                    MappingDecision(
                        source_column_name=item.source_column_name,
                        source_column_index=item.source_column_index,
                        target_concept=item.target_concept,
                        declared_unit=item.declared_unit,
                        notes=item.notes,
                    )
                    for item in command.decisions
                ],
            )
            mappings = await repositories.column_mappings.replace_all(
                session.id,
                tuple(
                    ColumnMapping(
                        id=new_id("dcm"),
                        import_session_id=session.id,
                        source_column_name=decision.source_column_name,
                        source_column_index=decision.source_column_index,
                        status=decision.status,
                        origin=MappingOrigin.USER_SELECTED,
                        target_concept=decision.target_concept,
                        declared_unit=decision.declared_unit,
                        sample_value_semantics=semantics.get(
                            decision.source_column_index, ValueSemantics.PRESENT
                        ),
                        notes=decision.notes,
                    )
                    for decision in decisions
                ),
            )
            session = await repositories.import_sessions.save(
                replace(
                    session,
                    mapping_confirmed_at=now,
                    # Kept verbatim, so the configuration that was actually
                    # confirmed survives independently of the rows.
                    mapping_metadata={
                        "confirmed_by": actor_id,
                        "confirmed_at": now.isoformat(),
                        "dataset_kind": dataset.kind.value,
                        "columns": [
                            {
                                "source_column_index": decision.source_column_index,
                                "source_column_name": decision.source_column_name,
                                "target_concept": decision.target_concept.value,
                                "declared_unit": decision.declared_unit,
                            }
                            for decision in decisions
                        ],
                    },
                )
            )
            await recorder.audit(
                action="import_session.mapping_confirmed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="import_session",
                resource_id=session.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                detail={"column_count": len(mappings)},
            )
            await recorder.event(
                event_type=EventType.IMPORT_SESSION_MAPPING_CONFIRMED,
                aggregate_type="import_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
            )
        return ImportSessionView(
            session=session,
            mappings=mappings,
            submission_blocked_reason=_submission_blocker(session, mappings),
        )


# --------------------------------------------------------------------------- #
# Submitting and abandoning                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SubmitImportCommand:
    actor: ActorContext
    session_id: str
    request: RequestContext


class SubmitImport:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: SubmitImportCommand) -> ImportSessionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            session, dataset, actor_id = await _load_session_scope(
                self._services,
                repositories,
                command.actor,
                command.session_id,
                action=IMPORT,
                recorder=recorder,
                occurred_at=now,
            )
            mappings = await repositories.column_mappings.list_for_session(session.id)
            blocker = _submission_blocker(session, mappings)
            if blocker is not None:
                raise ConflictError(
                    "this import cannot be submitted yet", details={"reason": blocker}
                )
            session = await repositories.import_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "import_session", session.state, ImportSessionState.SUBMITTED
                    ),
                    submitted_at=now,
                )
            )
            job_id = await repositories.jobs.enqueue(
                kind=JobKind.DATASET_IMPORT,
                payload={
                    "import_session_id": session.id,
                    "dataset_version_id": session.dataset_version_id,
                },
                correlation_id=command.request.correlation_id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                requested_by=actor_id,
                idempotency_key=f"import-execution:{session.id}",
            )
            await recorder.audit(
                action="import_session.submitted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="import_session",
                resource_id=session.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                new_state=session.state.value,
                detail={"import_job_id": job_id},
            )
            await recorder.event(
                event_type=EventType.IMPORT_SESSION_SUBMITTED,
                aggregate_type="import_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
            )
        return ImportSessionView(session=session, mappings=mappings)


@dataclass(frozen=True, slots=True)
class AbandonImportSessionCommand:
    actor: ActorContext
    session_id: str
    reason: str | None
    request: RequestContext


class AbandonImportSession:
    """Close an import without importing. The session and its reason are kept."""

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: AbandonImportSessionCommand) -> ImportSessionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            session, dataset, actor_id = await _load_session_scope(
                self._services,
                repositories,
                command.actor,
                command.session_id,
                action=IMPORT,
                recorder=recorder,
                occurred_at=now,
            )
            previous = session.state
            session = await repositories.import_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "import_session", previous, ImportSessionState.ABANDONED
                    ),
                    decided_at=now,
                    decided_by=actor_id,
                    rejection_reason=command.reason,
                )
            )
            mappings = await repositories.column_mappings.list_for_session(session.id)
            await recorder.audit(
                action="import_session.abandoned",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="import_session",
                resource_id=session.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                previous_state=previous.value,
                new_state=session.state.value,
                reason=command.reason,
            )
            await recorder.event(
                event_type=EventType.IMPORT_SESSION_ABANDONED,
                aggregate_type="import_session",
                aggregate_id=session.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
            )
        return ImportSessionView(session=session, mappings=mappings)


# --------------------------------------------------------------------------- #
# Executing the import (job handler)                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ExecuteImportCommand:
    import_session_id: str
    request: RequestContext


class ExecuteImport:
    """Validate the declared structure against the file and record the outcome.

    Structural only, over a bounded prefix, and the run says so in its summary.
    The checks are: do the mapped columns still exist with the same names, and are
    the required concepts actually populated in the sampled records — with
    "populated" judged by explicit value semantics, so an ``NA`` or an empty
    string is never counted as a value and a ``0`` never counted as absent.

    A passing import does **not** accept the version. Acceptance is an explicit
    human decision, made afterwards against this recorded outcome.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: ExecuteImportCommand) -> ValidationRun:
        started = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            session = await repositories.import_sessions.get(command.import_session_id)
            if session is None:
                raise NotFoundError("import_session", command.import_session_id)
            if session.state is not ImportSessionState.SUBMITTED:
                existing = await repositories.validation_runs.latest_for_subject(
                    subject_type="import_session", subject_id=session.id
                )
                if existing is not None:
                    return existing
                raise ConflictError(
                    "this import is not awaiting execution",
                    details={"state": session.state.value},
                )
            if session.file_artifact_id is None:  # pragma: no cover
                raise ConflictError("this import has no source artifact")
            artifact = await repositories.file_artifacts.get(session.file_artifact_id)
            if artifact is None:  # pragma: no cover
                raise NotFoundError("file_artifact", session.file_artifact_id)
            dataset = await repositories.datasets.get(session.dataset_id or "")
            if dataset is None:  # pragma: no cover
                raise NotFoundError("dataset", session.dataset_id or "")
            mappings = await repositories.column_mappings.list_for_session(session.id)
            session = await repositories.import_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "import_session", session.state, ImportSessionState.VALIDATING
                    ),
                )
            )
            run = await repositories.validation_runs.add(
                ValidationRun(
                    id=new_id("vrn"),
                    state=ValidationRunState.RUNNING,
                    validator_name=STRUCTURE_VALIDATOR_NAME,
                    validator_version=STRUCTURE_VALIDATOR_VERSION,
                    import_session_id=session.id,
                    dataset_version_id=session.dataset_version_id,
                    file_artifact_id=artifact.id,
                    requested_by=session.initiated_by,
                    correlation_id=command.request.correlation_id,
                    started_at=started,
                )
            )

        inspection = await self._services.inspector.inspect(
            artifact.storage_key, declared_filename=artifact.filename
        )
        issues: list[ValidationIssue] = []

        def add(
            severity: ValidationSeverity,
            category: ValidationCategory,
            code: str,
            message: str,
            *,
            semantics: ValueSemantics = ValueSemantics.PRESENT,
            observed: str | None = None,
            details: dict | None = None,
        ) -> None:
            issues.append(
                ValidationIssue(
                    id=new_id("vis"),
                    validation_run_id=run.id,
                    severity=severity,
                    category=category,
                    code=code,
                    message=message,
                    value_semantics=semantics,
                    observed_value=observed,
                    locator={"import_session_id": session.id},
                    details=details or {},
                )
            )

        columns_by_index = {column.index: column for column in inspection.columns}
        if inspection.detected_format is not session.detected_format:
            add(
                ValidationSeverity.BLOCKING,
                ValidationCategory.FILE_FORMAT,
                "source_changed_since_mapping",
                "the source no longer matches the format the mapping was built against",
                details={
                    "mapped_format": session.detected_format.value,
                    "detected_format": inspection.detected_format.value,
                },
            )
        for mapping in mappings:
            column = columns_by_index.get(mapping.source_column_index)
            if column is None:
                add(
                    ValidationSeverity.BLOCKING,
                    ValidationCategory.IMPORT_CONFIGURATION,
                    "mapped_column_missing",
                    "a mapped column is no longer present in the source",
                    semantics=ValueSemantics.MISSING,
                    observed=mapping.source_column_name[:64],
                    details={"column_index": mapping.source_column_index},
                )
                continue
            if column.name != mapping.source_column_name:
                add(
                    ValidationSeverity.BLOCKING,
                    ValidationCategory.IMPORT_CONFIGURATION,
                    "mapped_column_renamed",
                    "a mapped column has a different name in the source",
                    observed=column.name[:64],
                    details={
                        "column_index": mapping.source_column_index,
                        "mapped_name": mapping.source_column_name,
                    },
                )
                continue
            # "Usable" is decided by explicit value semantics, not by whether a
            # cell contained characters: ``NA``, ``unknown`` and ``-`` are absent
            # markers, while ``0`` and ``false`` are real values.
            usable_sample_count = sum(
                1 for value in column.sampled_values if not is_absent(classify(value))
            )
            if (
                mapping.status is MappingStatus.MAPPED
                and mapping.target_concept is not FieldConcept.PASSTHROUGH
                and inspection.sampled_record_count
                and (
                    column.non_empty_sample_count == 0
                    or (column.sampled_values and usable_sample_count == 0)
                )
            ):
                add(
                    ValidationSeverity.ERROR,
                    ValidationCategory.TABULAR_SCHEMA,
                    "required_concept_column_empty",
                    (
                        "a column mapped to a platform concept had no usable value in "
                        "any sampled record; absent is not treated as zero or false"
                    ),
                    semantics=ValueSemantics.MISSING,
                    observed=column.name[:64],
                    details={"target_concept": mapping.target_concept.value},
                )
        if not inspection.sampled_record_count:
            add(
                ValidationSeverity.ERROR,
                ValidationCategory.STRUCTURE,
                "no_records_in_sample",
                "no data records were found in the sampled prefix of the source",
            )
        for problem in inspection.problems:
            add(
                ValidationSeverity.ERROR,
                ValidationCategory.STRUCTURE,
                problem,
                "the source structure could not be read",
            )

        blocking = sum(1 for i in issues if i.severity is ValidationSeverity.BLOCKING)
        errors = sum(1 for i in issues if i.severity is ValidationSeverity.ERROR)
        warnings = sum(1 for i in issues if i.severity is ValidationSeverity.WARNING)
        infos = sum(1 for i in issues if i.severity is ValidationSeverity.INFO)
        outcome = outcome_for(blocking=blocking, errors=errors, warnings=warnings)
        completed = self._services.clock.now()

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            stored = await repositories.validation_runs.get(run.id)
            run = stored or run
            run = await repositories.validation_runs.save(
                replace(
                    run,
                    state=require_transition("validation_run", run.state, outcome),
                    completed_at=completed,
                    blocking_issue_count=blocking,
                    error_issue_count=errors,
                    warning_issue_count=warnings,
                    info_issue_count=infos,
                    summary={
                        "importer": f"{IMPORTER_NAME}:{IMPORTER_VERSION}",
                        "coverage": (
                            "bounded_prefix" if inspection.truncated else "complete_object"
                        ),
                        "sampled_record_count": inspection.sampled_record_count,
                        "mapped_column_count": sum(
                            1 for m in mappings if m.status is MappingStatus.MAPPED
                        ),
                        "detected_format": inspection.detected_format.value,
                    },
                )
            )
            await repositories.validation_issues.add_many(tuple(issues))

            current = await repositories.import_sessions.get(session.id)
            session = current or session
            passed = not (blocking or errors)
            session = await repositories.import_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "import_session",
                        session.state,
                        ImportSessionState.ACCEPTED if passed else ImportSessionState.REJECTED,
                    ),
                    decided_at=completed,
                    rejection_reason=(
                        None if passed else "structural validation refused this import"
                    ),
                    import_provenance={
                        **session.import_provenance,
                        "validation_run_id": run.id,
                        "outcome": outcome.value,
                    },
                )
            )
            version = await repositories.dataset_versions.get(session.dataset_version_id or "")
            if passed and version is not None:
                # Lineage is recorded whether or not this import is what moves
                # the version to ``validated``: the run that examined the input is
                # provenance either way.
                validating = version.state is DatasetVersionState.VALIDATING
                await repositories.dataset_versions.save(
                    replace(
                        version,
                        state=(
                            require_transition(
                                "dataset_version",
                                version.state,
                                DatasetVersionState.VALIDATED,
                            )
                            if validating
                            else version.state
                        ),
                        validated_at=completed if validating else version.validated_at,
                        processing_lineage={
                            **version.processing_lineage,
                            "import_session_id": session.id,
                            "importer": f"{IMPORTER_NAME}:{IMPORTER_VERSION}",
                            "structure_validator": (
                                f"{STRUCTURE_VALIDATOR_NAME}:{STRUCTURE_VALIDATOR_VERSION}"
                            ),
                            "validation_run_id": run.id,
                        },
                    )
                )
            await recorder.audit(
                action="import_session.executed",
                outcome=AuditOutcome.SUCCESS if passed else AuditOutcome.FAILURE,
                occurred_at=completed,
                actor_label="import-executor",
                resource_type="import_session",
                resource_id=session.id,
                workspace_id=session.workspace_id,
                project_id=session.project_id,
                new_state=session.state.value,
                detail={
                    "validation_run_id": run.id,
                    "outcome": outcome.value,
                    "blocking": blocking,
                    "errors": errors,
                },
            )
            await recorder.event(
                event_type=(
                    EventType.IMPORT_SESSION_ACCEPTED
                    if passed
                    else EventType.IMPORT_SESSION_REJECTED
                ),
                aggregate_type="import_session",
                aggregate_id=session.id,
                occurred_at=completed,
                workspace_id=session.workspace_id,
                idempotency_suffix=outcome.value,
            )
            await recorder.event(
                event_type=EventType.VALIDATION_RUN_COMPLETED,
                aggregate_type="validation_run",
                aggregate_id=run.id,
                occurred_at=completed,
                workspace_id=session.workspace_id,
                payload={"outcome": outcome.value, "import_session_id": session.id},
                idempotency_suffix=outcome.value,
            )
        return run


def require_supported_import_format(detected: InputFormat) -> InputFormat:
    """Guard used by the API before an import screen is opened."""
    if detected in TABULAR_FORMATS or detected is InputFormat.VCF:
        return detected
    raise ValidationError(
        "column mapping is only available for tabular and VCF sources",
        details={"detected_format": detected.value},
    )


__all__ = [
    "IMPORTER_NAME",
    "IMPORTER_VERSION",
    "STRUCTURE_VALIDATOR_NAME",
    "STRUCTURE_VALIDATOR_VERSION",
    "AbandonImportSession",
    "AbandonImportSessionCommand",
    "ColumnMappingRequest",
    "ConfirmColumnMapping",
    "ConfirmColumnMappingCommand",
    "ExecuteImport",
    "ExecuteImportCommand",
    "GetImportSession",
    "GetImportSessionQuery",
    "ImportSessionView",
    "ListImportSessions",
    "ListImportSessionsQuery",
    "OpenImportSession",
    "OpenImportSessionCommand",
    "SubmitImport",
    "SubmitImportCommand",
    "require_supported_import_format",
]
