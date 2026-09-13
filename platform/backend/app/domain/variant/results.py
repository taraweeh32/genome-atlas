"""The result surface of a scientific execution.

Three entities, deliberately not one:

``ResultIngestionRequest``
    The *application workflow*: an engine (or the platform's own execution path
    on its behalf) offers a payload, the platform validates its structure and
    either accepts or rejects it. This is where retries, idempotency and
    rejection reasons live.
``ResultSetRecord``
    The *durable scientific surface* that a successful ingestion produces. Its
    content is immutable: nothing may edit an available result set. A corrected
    run creates a new result set and marks the old one superseded, so a report
    that cited the old numbers still resolves to the numbers it cited.
``ResultArtifactRecord``
    One stored object belonging to a result set — usually a Parquet partition,
    sometimes a manifest or a log. Rows are never copied into PostgreSQL;
    PostgreSQL holds the reference, the checksum and the provenance link.

None of these classes knows what the numbers *mean*. They know who produced
them, from which inputs, in which version, and whether the bytes still verify.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ValidationError
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    DataOrigin,
    DeletionState,
    ResultArtifactFormat,
    ResultArtifactKind,
    ResultArtifactState,
    ResultCompleteness,
    ResultIngestionState,
    ResultSetState,
)


@dataclass(frozen=True, slots=True)
class ResultProvenance:
    """The scientific context a result set was produced in.

    Denormalized onto the result set on purpose. A result read years later must
    resolve its own provenance without depending on mutable configuration rows
    still saying the same thing they said at the time — and without any of those
    rows being rewritable into a different history.
    """

    #: The platform-side execution and the engine-side run it mirrors.
    analysis_execution_id: str
    scientific_execution_id: str | None = None
    analysis_configuration_id: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    reference_genome_resource_id: str | None = None
    #: Every other versioned scientific resource the run consumed, as reported.
    resource_identities: dict[str, Any] = field(default_factory=dict)
    parameters_digest: str | None = None
    provenance_manifest_id: str | None = None

    @property
    def is_attributable(self) -> bool:
        """Whether the run can be traced to a named engine version.

        A result set may exist without this being true — the platform records
        what it was given — but a caller that needs reproducibility must check it
        rather than assume it.
        """
        return bool(self.scientific_execution_id and self.engine_version)


@dataclass(frozen=True, slots=True)
class ResultArtifactRecord:
    """One stored artifact of a result set.

    ``state`` tracks the *bytes*, not the science: ``ACCEPTED`` means the object
    exists and its checksum matched what the engine declared. It says nothing
    about whether the contents are scientifically correct.
    """

    id: str
    result_set_id: str
    artifact_key: str
    kind: ResultArtifactKind
    artifact_format: ResultArtifactFormat
    state: ResultArtifactState
    storage_uri: str | None = None
    file_artifact_id: str | None = None
    #: Parquet dataset root / partition expression for the analytical layer.
    analytical_location: str | None = None
    scientific_artifact_id: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: ChecksumAlgorithm | None = None
    checksum_value: str | None = None
    row_count: int | None = None
    #: Column contract of a tabular artifact, used by the filtering layer later.
    column_schema: dict[str, Any] = field(default_factory=dict)
    failure_code: str | None = None
    failure_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    verified_at: datetime | None = None
    created_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.storage_uri is None and self.analytical_location is None:
            raise ValidationError(
                "a result artifact must be locatable in storage",
                field="storage_uri",
            )

    def _to(self, target: ResultArtifactState, **changes: Any) -> ResultArtifactRecord:
        require_transition("result_artifact", self.state, target)
        return replace(self, state=target, **changes)

    def verifying(self) -> ResultArtifactRecord:
        return self._to(ResultArtifactState.VERIFYING)

    def accepted(
        self,
        *,
        at: datetime,
        size_bytes: int | None = None,
        row_count: int | None = None,
        column_schema: dict[str, Any] | None = None,
    ) -> ResultArtifactRecord:
        return self._to(
            ResultArtifactState.ACCEPTED,
            verified_at=at,
            size_bytes=self.size_bytes if size_bytes is None else size_bytes,
            row_count=self.row_count if row_count is None else row_count,
            column_schema=self.column_schema if column_schema is None else column_schema,
        )

    def rejected(self, *, code: str, message: str) -> ResultArtifactRecord:
        """Recorded, never deleted: a rejected artifact is diagnostic evidence."""
        return self._to(
            ResultArtifactState.REJECTED, failure_code=code, failure_message=message
        )

    def superseded(self) -> ResultArtifactRecord:
        return self._to(ResultArtifactState.SUPERSEDED)

    def missing(self, *, message: str | None = None) -> ResultArtifactRecord:
        return self._to(
            ResultArtifactState.MISSING,
            failure_code="artifact_missing",
            failure_message=message or "the stored object could not be located",
        )

    @property
    def is_readable(self) -> bool:
        return self.state in (ResultArtifactState.ACCEPTED, ResultArtifactState.SUPERSEDED)


@dataclass(frozen=True, slots=True)
class ResultSetRecord:
    """A scientific execution's result surface. Immutable content.

    Tenant-scoped by ``workspace_id``/``project_id`` so that every read can be
    authorized from the row itself, exactly like datasets and analyses. The
    variant records it references are *not* tenant-scoped — canonical variants are
    shared reference data — which is precisely why authorization must hang off
    this row and off observations, never off the variant.
    """

    id: str
    workspace_id: str
    project_id: str
    result_key: str
    state: ResultSetState
    provenance: ResultProvenance
    #: What the engine said about its own output's completeness. Never inferred
    #: from ``row_count``: zero rows is a legitimate complete answer.
    completeness: ResultCompleteness = ResultCompleteness.UNKNOWN
    origin: DataOrigin = DataOrigin.GENERATED
    analytical_location: str | None = None
    scientific_artifact_id: str | None = None
    row_count: int | None = None
    column_schema: dict[str, Any] = field(default_factory=dict)
    #: Set when a newer result set replaced this one for the same result key.
    superseded_by_result_set_id: str | None = None
    invalidation_reason: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    available_at: datetime | None = None
    deletion_state: DeletionState = DeletionState.ACTIVE
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    retention_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1

    def _to(self, target: ResultSetState, **changes: Any) -> ResultSetRecord:
        require_transition("result_set", self.state, target)
        return replace(self, state=target, **changes)

    def generating(self) -> ResultSetRecord:
        return self._to(ResultSetState.GENERATING)

    def validated(self) -> ResultSetRecord:
        """Structure accepted; the analytical materialization has not landed yet."""
        return self._to(ResultSetState.VALIDATED)

    def available(
        self,
        *,
        at: datetime,
        analytical_location: str | None = None,
        row_count: int | None = None,
        column_schema: dict[str, Any] | None = None,
        completeness: ResultCompleteness | None = None,
    ) -> ResultSetRecord:
        return self._to(
            ResultSetState.AVAILABLE,
            available_at=at,
            analytical_location=analytical_location or self.analytical_location,
            row_count=self.row_count if row_count is None else row_count,
            column_schema=self.column_schema if column_schema is None else column_schema,
            completeness=completeness or self.completeness,
        )

    def failed(self, *, code: str, message: str) -> ResultSetRecord:
        """Terminal. A failed surface never later claims to hold results."""
        return self._to(ResultSetState.FAILED, failure_code=code, failure_message=message)

    def superseded_by(self, *, result_set_id: str) -> ResultSetRecord:
        if result_set_id == self.id:
            raise ValidationError(
                "a result set cannot supersede itself", field="result_set_id"
            )
        return self._to(
            ResultSetState.SUPERSEDED, superseded_by_result_set_id=result_set_id
        )

    def invalidated(self, *, reason: str) -> ResultSetRecord:
        """Withdraw the surface without touching a byte of its content.

        Used when an input is withdrawn or a resource is found to be defective.
        The rows stay exactly as they were; what changes is that the platform
        stops presenting them as usable, and says why.
        """
        if not reason.strip():
            raise ValidationError(
                "invalidating a result requires a recorded reason", field="reason"
            )
        return self._to(ResultSetState.INVALIDATED, invalidation_reason=reason)

    def expired(self) -> ResultSetRecord:
        return self._to(ResultSetState.EXPIRED)

    @property
    def is_readable(self) -> bool:
        """Whether the scientific content may be presented as usable.

        ``SUPERSEDED`` stays readable: a historical report must still resolve the
        result set it was built from.
        """
        return self.state in (ResultSetState.AVAILABLE, ResultSetState.SUPERSEDED)


@dataclass(frozen=True, slots=True)
class ResultIngestionRequest:
    """One attempt to bring an engine's output into the platform.

    ``idempotency_key`` makes redelivery safe: an engine, a worker retry or a
    duplicated queue message that offers the same payload twice must produce one
    result set, not two. The key is scoped to the analysis execution plus the
    result key, so a legitimate *re-run* — which has a new execution — is never
    mistaken for a duplicate.

    ``REJECTED`` and ``FAILED`` are different outcomes and stay different:
    rejected means the payload violated the contract, failed means the platform
    could not finish the work. Merging them would make an engine bug and an
    infrastructure incident look identical in the logs.
    """

    id: str
    workspace_id: str
    project_id: str
    analysis_execution_id: str
    result_key: str
    idempotency_key: str
    state: ResultIngestionState
    #: Digest of the received payload, so a redelivery that differs in content is
    #: detectable rather than silently deduplicated.
    payload_digest: str
    declared_completeness: ResultCompleteness = ResultCompleteness.UNKNOWN
    scientific_execution_id: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    submitted_by: str | None = None
    service_account_id: str | None = None
    job_id: str | None = None
    correlation_id: str | None = None
    result_set_id: str | None = None
    declared_row_count: int | None = None
    artifact_count: int = 0
    #: True when the payload came from the marked development/test adapter. Stored
    #: so a development result can never be mistaken for a scientific one.
    is_development_payload: bool = False
    #: Structural findings. Populated on rejection, and also on acceptance when
    #: the payload was accepted with warnings.
    findings: tuple[dict[str, Any], ...] = ()
    rejection_code: str | None = None
    rejection_message: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    received_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    version: int = 1

    def _to(self, target: ResultIngestionState, **changes: Any) -> ResultIngestionRequest:
        require_transition("result_ingestion", self.state, target)
        return replace(self, state=target, **changes)

    def validating(self) -> ResultIngestionRequest:
        return self._to(ResultIngestionState.VALIDATING)

    def validated(
        self, *, findings: tuple[dict[str, Any], ...] = ()
    ) -> ResultIngestionRequest:
        return self._to(ResultIngestionState.VALIDATED, findings=findings)

    def materializing(self, *, result_set_id: str) -> ResultIngestionRequest:
        return self._to(ResultIngestionState.MATERIALIZING, result_set_id=result_set_id)

    def accepted(self, *, at: datetime) -> ResultIngestionRequest:
        if self.result_set_id is None:
            raise ValidationError(
                "an accepted ingestion must reference the result set it produced",
                field="result_set_id",
            )
        return self._to(ResultIngestionState.ACCEPTED, completed_at=at)

    def rejected(
        self,
        *,
        at: datetime,
        code: str,
        message: str,
        findings: tuple[dict[str, Any], ...] = (),
    ) -> ResultIngestionRequest:
        return self._to(
            ResultIngestionState.REJECTED,
            completed_at=at,
            rejection_code=code,
            rejection_message=message,
            findings=findings or self.findings,
        )

    def failed(self, *, at: datetime, code: str, message: str) -> ResultIngestionRequest:
        return self._to(
            ResultIngestionState.FAILED,
            completed_at=at,
            failure_code=code,
            failure_message=message,
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            ResultIngestionState.ACCEPTED,
            ResultIngestionState.REJECTED,
            ResultIngestionState.FAILED,
        )


__all__ = [
    "ResultArtifactRecord",
    "ResultIngestionRequest",
    "ResultProvenance",
    "ResultSetRecord",
]
