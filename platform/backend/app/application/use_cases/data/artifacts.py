"""Artifact verification: integrity, security, format and structure.

This is the work ``CompleteUpload`` queues. It runs in a worker with no user
actor: authorization was decided when the transfer grant was issued, and nothing
here is reachable from a request. What it produces is a **validation run** —
an append-only record of what was checked, what was found, and by which validator
version — plus the artifact/session state that follows from it.

Design rules:

* Every gate fails closed. A scan that could not run is ``unavailable``, not
  clean; a format that could not be recognised is an error, not a guess.
* Findings are categorised (transfer integrity, security, file format, structure)
  and never merged into one opaque "invalid".
* Warnings are a distinct outcome from a clean pass, so a declared/detected
  format mismatch is visible instead of being resolved silently.
* Nothing here interprets scientific content. It reports that a file is a
  tab-separated table whose header names look like coordinates; deciding whether
  those coordinates are valid for a reference build happens behind the scientific
  integration contract.
* An infected artifact is moved to a quarantine prefix and its row is marked
  quarantined, which is terminal. It is never promoted later — only replaced by a
  fresh upload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.ports import ScanVerdict
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.data.dependencies import DataServices
from app.domain.data.entities import ValidationIssue, ValidationRun, outcome_for
from app.domain.data.formats import ACCEPTED_FORMATS
from app.domain.data.storage import quarantine_key
from app.domain.errors import NotFoundError
from app.domain.events import EventType
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    AuditOutcome,
    DatasetVersionState,
    FileValidationState,
    InputFormat,
    MalwareScanState,
    UploadSessionState,
    ValidationCategory,
    ValidationRunState,
    ValidationSeverity,
    ValueSemantics,
)
from app.infrastructure.persistence.repositories.base import new_id

VALIDATOR_NAME = "platform-file-verifier"
VALIDATOR_VERSION = "1"

#: Checksum verification streams the whole object. Above this size the platform
#: records that it did not verify the digest instead of quietly skipping it.
CHECKSUM_LIMIT_BYTES = 5 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _Finding:
    severity: ValidationSeverity
    category: ValidationCategory
    code: str
    message: str
    value_semantics: ValueSemantics = ValueSemantics.PRESENT
    observed_value: str | None = None
    details: dict | None = None


@dataclass(frozen=True, slots=True)
class VerifyArtifactCommand:
    """Invoked by the worker, from a queued job payload."""

    upload_session_id: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    validation_run: ValidationRun
    session_state: UploadSessionState
    artifact_validation_state: FileValidationState
    scan_state: MalwareScanState


class VerifyArtifact:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: VerifyArtifactCommand) -> VerificationOutcome:
        started = self._services.clock.now()

        # --- read the subject, and claim it for verification ---------------- #
        async with self._services.unit_of_work.begin() as repositories:
            session = await repositories.upload_sessions.get(command.upload_session_id)
            if session is None:
                raise NotFoundError("upload_session", command.upload_session_id)
            artifact = await repositories.file_artifacts.get(session.file_artifact_id)
            if artifact is None:  # pragma: no cover - foreign key guarantees this
                raise NotFoundError("file_artifact", session.file_artifact_id)
            if session.state is not UploadSessionState.UPLOADED:
                # Already verified, cancelled or quarantined: a retried job must
                # not re-decide a recorded outcome.
                existing = await repositories.validation_runs.latest_for_subject(
                    subject_type="file_artifact", subject_id=artifact.id
                )
                if existing is not None:
                    return VerificationOutcome(
                        validation_run=existing,
                        session_state=session.state,
                        artifact_validation_state=artifact.validation_state,
                        scan_state=artifact.scan_state,
                    )
            dataset = await repositories.datasets.get(session.dataset_id)
            if dataset is None:  # pragma: no cover
                raise NotFoundError("dataset", session.dataset_id)
            session = await repositories.upload_sessions.save(
                replace(
                    session,
                    state=require_transition(
                        "upload_session", session.state, UploadSessionState.SCANNING
                    ),
                )
            )
            artifact = await repositories.file_artifacts.save(
                replace(
                    artifact,
                    scan_state=require_transition(
                        "malware_scan", artifact.scan_state, MalwareScanState.SCANNING
                    ),
                    validation_state=require_transition(
                        "file_validation",
                        artifact.validation_state,
                        FileValidationState.VALIDATING,
                    ),
                )
            )
            run = await repositories.validation_runs.add(
                ValidationRun(
                    id=new_id("vrn"),
                    state=ValidationRunState.RUNNING,
                    validator_name=VALIDATOR_NAME,
                    validator_version=VALIDATOR_VERSION,
                    dataset_version_id=session.dataset_version_id,
                    file_artifact_id=artifact.id,
                    requested_by=session.initiated_by,
                    correlation_id=command.request.correlation_id,
                    started_at=started,
                )
            )
            recorder = ActivityRecorder(repositories, command.request)
            await recorder.event(
                event_type=EventType.VALIDATION_RUN_STARTED,
                aggregate_type="validation_run",
                aggregate_id=run.id,
                occurred_at=started,
                workspace_id=session.workspace_id,
                idempotency_suffix=run.id,
            )

        dataset_kind = dataset.kind
        findings: list[_Finding] = []
        summary: dict[str, object] = {
            "declared_format": session.declared_format.value,
            "declared_size_bytes": session.declared_size_bytes,
            "stored_size_bytes": artifact.size_bytes,
        }

        # --- 1. transfer integrity ----------------------------------------- #
        if artifact.size_bytes != session.declared_size_bytes:
            findings.append(
                _Finding(
                    severity=ValidationSeverity.BLOCKING,
                    category=ValidationCategory.TRANSFER_INTEGRITY,
                    code="size_mismatch",
                    message=(
                        "the stored object size does not match the declared size, so the "
                        "transfer cannot be assumed complete"
                    ),
                    details={
                        "declared_size_bytes": session.declared_size_bytes,
                        "stored_size_bytes": artifact.size_bytes,
                    },
                )
            )

        computed_checksum: str | None = None
        if session.declared_checksum_value:
            size = artifact.size_bytes or 0
            if size > CHECKSUM_LIMIT_BYTES:
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.WARNING,
                        category=ValidationCategory.TRANSFER_INTEGRITY,
                        code="checksum_not_verified",
                        message=(
                            "the object exceeds the inline checksum limit; the declared "
                            "checksum was recorded but not verified"
                        ),
                        details={"limit_bytes": CHECKSUM_LIMIT_BYTES},
                    )
                )
            else:
                computed_checksum = await self._services.checksums.checksum(
                    artifact.storage_key,
                    algorithm=session.declared_checksum_algorithm.value,
                )
                summary["computed_checksum"] = computed_checksum
                if computed_checksum.lower() != session.declared_checksum_value.lower():
                    findings.append(
                        _Finding(
                            severity=ValidationSeverity.BLOCKING,
                            category=ValidationCategory.TRANSFER_INTEGRITY,
                            code="checksum_mismatch",
                            message=(
                                "the computed checksum does not match the declared "
                                "checksum; the stored bytes are not what was submitted"
                            ),
                            details={
                                "algorithm": session.declared_checksum_algorithm.value
                            },
                        )
                    )

        # --- 2. security ---------------------------------------------------- #
        scan = await self._services.scanner.scan(artifact.storage_key)
        summary["scanner_name"] = scan.scanner_name
        summary["scanner_version"] = scan.scanner_version
        scan_state = {
            ScanVerdict.CLEAN: MalwareScanState.CLEAN,
            ScanVerdict.INFECTED: MalwareScanState.INFECTED,
            ScanVerdict.UNAVAILABLE: MalwareScanState.UNAVAILABLE,
            ScanVerdict.FAILED: MalwareScanState.FAILED,
        }[scan.verdict]
        if scan.verdict is ScanVerdict.INFECTED:
            findings.append(
                _Finding(
                    severity=ValidationSeverity.BLOCKING,
                    category=ValidationCategory.SECURITY,
                    code="malware_detected",
                    message="the uploaded object was refused by the malware scanner",
                    details={"scanner": scan.scanner_name, "detail": scan.detail},
                )
            )
        elif scan.verdict is not ScanVerdict.CLEAN:
            findings.append(
                _Finding(
                    severity=ValidationSeverity.BLOCKING,
                    category=ValidationCategory.SECURITY,
                    code="scan_not_available",
                    message=(
                        "the object could not be scanned, so it may not be used; an "
                        "unscanned upload is never treated as clean"
                    ),
                    details={"verdict": scan.verdict.value, "detail": scan.detail},
                )
            )

        inspection = None
        if scan.verdict is not ScanVerdict.INFECTED:
            # --- 3. format and structure ----------------------------------- #
            inspection = await self._services.inspector.inspect(
                artifact.storage_key, declared_filename=artifact.filename
            )
            summary["detected_format"] = inspection.detected_format.value
            summary["compression"] = inspection.compression.value
            summary["column_count"] = len(inspection.columns)
            summary["sampled_record_count"] = inspection.sampled_record_count
            # Stated explicitly so nobody reads this run as a whole-file parse.
            summary["coverage"] = (
                "bounded_prefix" if inspection.truncated else "complete_object"
            )
            summary["inspector_version"] = self._services.inspector.version

            if inspection.detected_format is InputFormat.UNKNOWN:
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.FILE_FORMAT,
                        code="format_not_recognised",
                        message="the container format of the stored object was not recognised",
                    )
                )
            elif inspection.detected_format is not session.declared_format:
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.WARNING,
                        category=ValidationCategory.FILE_FORMAT,
                        code="declared_format_mismatch",
                        message=(
                            "the detected format differs from the declared format; both "
                            "are retained and neither was overwritten"
                        ),
                        details={
                            "declared_format": session.declared_format.value,
                            "detected_format": inspection.detected_format.value,
                        },
                    )
                )
            accepted = ACCEPTED_FORMATS.get(dataset_kind, frozenset())
            if (
                inspection.detected_format is not InputFormat.UNKNOWN
                and inspection.detected_format not in accepted
            ):
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.FILE_FORMAT,
                        code="format_not_accepted_for_kind",
                        message="the detected format is not accepted for this dataset kind",
                        details={
                            "dataset_kind": dataset_kind.value,
                            "detected_format": inspection.detected_format.value,
                            "accepted_formats": sorted(f.value for f in accepted),
                        },
                    )
                )
            for problem in inspection.problems:
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.STRUCTURE,
                        code=problem,
                        message="the structure of the stored object could not be read",
                    )
                )
            if not inspection.columns and inspection.detected_format not in (
                InputFormat.JSON,
                InputFormat.TEXT,
                InputFormat.BCF,
                InputFormat.UNKNOWN,
            ):
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.STRUCTURE,
                        code="no_columns_detected",
                        message="no header columns were found in the sampled prefix",
                    )
                )
            for column in inspection.columns:
                if not column.name:
                    findings.append(
                        _Finding(
                            severity=ValidationSeverity.ERROR,
                            category=ValidationCategory.TABULAR_SCHEMA,
                            code="empty_column_name",
                            message="a header column has no name",
                            value_semantics=ValueSemantics.EMPTY,
                            details={"column_index": column.index},
                        )
                    )
                elif column.non_empty_sample_count == 0 and inspection.sampled_record_count:
                    findings.append(
                        _Finding(
                            severity=ValidationSeverity.INFO,
                            category=ValidationCategory.TABULAR_SCHEMA,
                            code="column_empty_in_sample",
                            message=(
                                "no value was present for this column in the sampled "
                                "records; this is reported, not treated as zero"
                            ),
                            value_semantics=ValueSemantics.MISSING,
                            observed_value=column.name[:64],
                            details={"column_index": column.index},
                        )
                    )
            duplicates = {
                name
                for name in (column.name for column in inspection.columns)
                if [c.name for c in inspection.columns].count(name) > 1
            }
            for name in sorted(duplicates):
                findings.append(
                    _Finding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.TABULAR_SCHEMA,
                        code="duplicate_column_name",
                        message="the same header name appears more than once",
                        observed_value=name[:64],
                    )
                )

        # --- 4. record the outcome ----------------------------------------- #
        blocking = sum(1 for f in findings if f.severity is ValidationSeverity.BLOCKING)
        errors = sum(1 for f in findings if f.severity is ValidationSeverity.ERROR)
        warnings = sum(1 for f in findings if f.severity is ValidationSeverity.WARNING)
        infos = sum(1 for f in findings if f.severity is ValidationSeverity.INFO)
        outcome = outcome_for(blocking=blocking, errors=errors, warnings=warnings)
        completed = self._services.clock.now()

        quarantined = scan.verdict is ScanVerdict.INFECTED
        if quarantined:
            # The bytes are moved out of the working prefix before the row is
            # marked, so a quarantined object is not reachable at its old key.
            await self._services.storage.move_object(
                artifact.storage_key,
                quarantine_key(
                    workspace_id=artifact.workspace_id, file_artifact_id=artifact.id
                ),
            )

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            stored_run = await repositories.validation_runs.get(run.id)
            run = stored_run or run
            run = await repositories.validation_runs.save(
                replace(
                    run,
                    state=require_transition("validation_run", run.state, outcome),
                    completed_at=completed,
                    blocking_issue_count=blocking,
                    error_issue_count=errors,
                    warning_issue_count=warnings,
                    info_issue_count=infos,
                    summary=summary,
                )
            )
            await repositories.validation_issues.add_many(
                tuple(
                    ValidationIssue(
                        id=new_id("vis"),
                        validation_run_id=run.id,
                        severity=finding.severity,
                        category=finding.category,
                        code=finding.code,
                        message=finding.message,
                        value_semantics=finding.value_semantics,
                        observed_value=finding.observed_value,
                        locator={"file_artifact_id": artifact.id},
                        details=finding.details or {},
                    )
                    for finding in findings
                )
            )

            current_artifact = await repositories.file_artifacts.get(artifact.id)
            artifact = current_artifact or artifact
            if quarantined:
                artifact_validation = require_transition(
                    "file_validation",
                    artifact.validation_state,
                    FileValidationState.QUARANTINED,
                )
            elif blocking or errors:
                artifact_validation = require_transition(
                    "file_validation", artifact.validation_state, FileValidationState.INVALID
                )
            else:
                artifact_validation = require_transition(
                    "file_validation", artifact.validation_state, FileValidationState.VALID
                )
            artifact = await repositories.file_artifacts.save(
                replace(
                    artifact,
                    scan_state=require_transition(
                        "malware_scan", artifact.scan_state, scan_state
                    ),
                    scan_detail=scan.detail,
                    validation_state=artifact_validation,
                    checksum_value=computed_checksum or artifact.checksum_value,
                    detected_format=(
                        inspection.detected_format if inspection else artifact.detected_format
                    ),
                    compression=(inspection.compression if inspection else artifact.compression),
                    quarantined_at=completed if quarantined else artifact.quarantined_at,
                    quarantine_reason=scan.detail if quarantined else artifact.quarantine_reason,
                    metadata_json={
                        **artifact.metadata_json,
                        "verification_run_id": run.id,
                        "inspection_truncated": (
                            inspection.truncated if inspection else None
                        ),
                    },
                )
            )

            current_session = await repositories.upload_sessions.get(session.id)
            session = current_session or session
            if quarantined:
                session_state = UploadSessionState.QUARANTINED
            elif blocking or errors:
                session_state = UploadSessionState.REJECTED
            else:
                session_state = UploadSessionState.ACCEPTED
            if session_state is UploadSessionState.ACCEPTED:
                session = await repositories.upload_sessions.save(
                    replace(
                        session,
                        state=require_transition(
                            "upload_session", session.state, UploadSessionState.VALIDATING
                        ),
                    )
                )
            session = await repositories.upload_sessions.save(
                replace(
                    session,
                    state=require_transition("upload_session", session.state, session_state),
                    failure_reason=(
                        None
                        if session_state is UploadSessionState.ACCEPTED
                        else "verification refused this upload"
                    ),
                )
            )

            # The version follows the artifacts: it becomes validated only when
            # every artifact it holds carries a non-blocking outcome. Acceptance
            # itself stays a separate, human decision.
            version = await repositories.dataset_versions.get(session.dataset_version_id)
            if version is not None and version.state is DatasetVersionState.VALIDATING:
                artifacts = await repositories.file_artifacts.list_for_version(version.id)
                if artifacts and all(
                    item.validation_state is FileValidationState.VALID for item in artifacts
                ):
                    await repositories.dataset_versions.save(
                        replace(
                            version,
                            state=require_transition(
                                "dataset_version",
                                version.state,
                                DatasetVersionState.VALIDATED,
                            ),
                            validated_at=completed,
                            detected_format=(
                                inspection.detected_format
                                if inspection
                                else version.detected_format
                            ),
                            compression=(
                                inspection.compression if inspection else version.compression
                            ),
                            checksum_value=computed_checksum or version.checksum_value,
                            source_representation={
                                **version.source_representation,
                                "artifacts": [
                                    {
                                        "file_artifact_id": item.id,
                                        "filename": item.filename,
                                        "original_filename": item.original_filename,
                                        "declared_format": item.declared_format.value,
                                        "detected_format": item.detected_format.value,
                                        "compression": item.compression.value,
                                        "size_bytes": item.size_bytes,
                                        "checksum_algorithm": item.checksum_algorithm.value,
                                        "checksum_value": item.checksum_value,
                                    }
                                    for item in artifacts
                                ],
                            },
                        )
                    )

            await recorder.audit(
                action="file_artifact.verified",
                outcome=(
                    AuditOutcome.SUCCESS
                    if session_state is UploadSessionState.ACCEPTED
                    else AuditOutcome.FAILURE
                ),
                occurred_at=completed,
                actor_label="artifact-verifier",
                resource_type="file_artifact",
                resource_id=artifact.id,
                workspace_id=artifact.workspace_id,
                project_id=session.project_id,
                new_state=artifact.validation_state.value,
                detail={
                    "validation_run_id": run.id,
                    "outcome": outcome.value,
                    "scan_state": scan_state.value,
                    "blocking": blocking,
                    "errors": errors,
                    "warnings": warnings,
                },
            )
            await recorder.event(
                event_type=EventType.VALIDATION_RUN_COMPLETED,
                aggregate_type="validation_run",
                aggregate_id=run.id,
                occurred_at=completed,
                workspace_id=artifact.workspace_id,
                payload={"outcome": outcome.value, "file_artifact_id": artifact.id},
                idempotency_suffix=outcome.value,
            )
            if quarantined:
                await recorder.event(
                    event_type=EventType.FILE_ARTIFACT_QUARANTINED,
                    aggregate_type="file_artifact",
                    aggregate_id=artifact.id,
                    occurred_at=completed,
                    workspace_id=artifact.workspace_id,
                )
            elif session_state is UploadSessionState.REJECTED:
                await recorder.event(
                    event_type=EventType.UPLOAD_SESSION_REJECTED,
                    aggregate_type="upload_session",
                    aggregate_id=session.id,
                    occurred_at=completed,
                    workspace_id=artifact.workspace_id,
                )

        return VerificationOutcome(
            validation_run=run,
            session_state=session.state,
            artifact_validation_state=artifact.validation_state,
            scan_state=artifact.scan_state,
        )


__all__ = [
    "CHECKSUM_LIMIT_BYTES",
    "VALIDATOR_NAME",
    "VALIDATOR_VERSION",
    "VerificationOutcome",
    "VerifyArtifact",
    "VerifyArtifactCommand",
]
