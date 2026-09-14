"""Analysis definition, versioned configuration and immutable execution records.

Four separate concepts, four separate tables:

``analyses`` (what a user defined) → ``analysis_configurations`` (a versioned,
snapshot-capable parameter set) → ``analysis_executions`` (an immutable record of
one run) → ``jobs`` (durable work, see ``jobs.py``) → ``scientific_executions``
(the independent compute subsystem's run, see ``scientific.py``).

Re-running an analysis creates a new execution row; the historical execution
context is never overwritten.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    AnalysisKind,
    AnalysisState,
    ConfigurationValidationState,
    DeletionState,
    ExecutionState,
    JobQueue,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    RetentionMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Analysis(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """Analysis *definition* — no execution state whatsoever."""

    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_analyses_project_id_name"),
        state_check("kind", AnalysisKind, "kind_valid"),
        state_check("state", AnalysisState, "state_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        Index("ix_analyses_workspace_id_state", "workspace_id", "state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Capability identity requested from the scientific subsystem.
    capability_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=AnalysisState.DRAFT.value
    )
    created_by: Mapped[str] = fk_column("app.users.id")
    owner_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    #: Current configuration; every configuration version stays queryable.
    current_configuration_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Queue/priority/retry/timeout defaults for executions of this definition.
    #: Operational only — never scientific parameters.
    execution_defaults: Mapped[dict | None] = json_column()
    metadata_json: Mapped[dict | None] = json_column()


class AnalysisConfiguration(Base, TimestampMixin):
    """Versioned, immutable, snapshot-capable analysis configuration.

    Each scientific concern keeps its own column so a configuration can be
    inspected and compared without parsing one opaque blob, while remaining
    forward-compatible: the *content* of each section is defined by the
    scientific contract, not by this schema.
    """

    __tablename__ = "analysis_configurations"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "version_number", name="uq_analysis_configurations_analysis_id_version"
        ),
        state_check("validation_state", ConfigurationValidationState, "validation_state_valid"),
        Index("ix_analysis_configurations_content_hash", "content_hash"),
    )

    id: Mapped[str] = id_column()
    analysis_id: Mapped[str] = fk_column("app.analyses.id")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = fk_column("app.users.id")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Recorded outcome of validating *this* version. Written once; a corrected
    #: configuration is a new version, never an edit of this one.
    validation_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ConfigurationValidationState.UNVALIDATED.value
    )
    validation_findings: Mapped[dict | None] = json_column()
    #: Digest over the scientific sections; identifies parameter-identical
    #: versions without ever replacing one.
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    filtering_configuration: Mapped[dict | None] = json_column()
    ranking_configuration: Mapped[dict | None] = json_column()
    annotation_configuration: Mapped[dict | None] = json_column()
    evidence_configuration: Mapped[dict | None] = json_column()
    interpretation_configuration: Mapped[dict | None] = json_column()
    reporting_configuration: Mapped[dict | None] = json_column()
    execution_parameters: Mapped[dict | None] = json_column()
    #: Scientific resource registry references (pipeline/engine/genome/ruleset).
    pipeline_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    reference_genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    ruleset_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    execution_profile_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    #: Full snapshot captured when an execution is created.
    snapshot: Mapped[dict | None] = json_column()


class AnalysisConfigurationInput(Base, TimestampMixin):
    """Input dataset versions declared by a configuration."""

    __tablename__ = "analysis_configuration_inputs"
    __table_args__ = (
        UniqueConstraint(
            "analysis_configuration_id",
            "dataset_version_id",
            "role",
            name="uq_analysis_configuration_inputs_configuration_version_role",
        ),
    )

    id: Mapped[str] = id_column()
    analysis_configuration_id: Mapped[str] = fk_column(
        "app.analysis_configurations.id", ondelete="CASCADE"
    )
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    #: e.g. ``primary``, ``control``, ``manifest``.
    role: Mapped[str] = mapped_column(String(64), nullable=False)


class AnalysisExecution(Base, TimestampMixin):
    """Immutable record of one analysis run.

    No ``ConcurrencyMixin``: an execution is append-only. Progress is expressed
    by status/timestamp transitions written by the owning job, and a re-run
    always creates a new row.
    """

    __tablename__ = "analysis_executions"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "attempt_sequence", name="uq_analysis_executions_analysis_id_attempt"
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_analysis_executions_idempotency_key"
        ),
        state_check("state", ExecutionState, "state_valid"),
        state_check("queue", JobQueue, "queue_valid"),
        Index("ix_analysis_executions_workspace_id_state", "workspace_id", "state"),
        Index("ix_analysis_executions_project_id_requested_at", "project_id", "requested_at"),
        Index("ix_analysis_executions_schedule_id", "schedule_id"),
        Index("ix_analysis_executions_correlation_id", "correlation_id"),
        Index("ix_analysis_executions_requested_at", "requested_at"),
    )

    id: Mapped[str] = id_column()
    analysis_id: Mapped[str] = fk_column("app.analyses.id")
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    analysis_configuration_id: Mapped[str] = fk_column("app.analysis_configurations.id")
    #: Configuration frozen at request time; later edits cannot rewrite history.
    configuration_snapshot: Mapped[dict | None] = json_column()
    attempt_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ExecutionState.REQUESTED.value
    )
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Resolved scientific context, denormalized for reproducibility.
    execution_environment: Mapped[dict | None] = json_column()
    resource_profile: Mapped[dict | None] = json_column()
    scientific_versions: Mapped[dict | None] = json_column()
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_details: Mapped[dict | None] = json_column()
    scheduled_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Requested scientific capability identity, resolved at request time.
    capability_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capability_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Scheduling inputs. Priority is a bounded hint, never an authorization.
    queue: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=JobQueue.DEFAULT.value
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    resource_requirements: Mapped[dict | None] = json_column()
    #: Makes a retried *request* idempotent: the same key returns the same run
    #: instead of launching a duplicate computation.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Recurring origin, when this run came from a schedule firing.
    schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scientific_execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compute_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A cancellation *request* is a distinct fact from work having stopped.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnalysisExecutionInput(Base, TimestampMixin):
    """The exact dataset versions an execution consumed."""

    __tablename__ = "analysis_execution_inputs"
    __table_args__ = (
        UniqueConstraint(
            "analysis_execution_id",
            "dataset_version_id",
            "role",
            name="uq_analysis_execution_inputs_execution_version_role",
        ),
    )

    id: Mapped[str] = id_column()
    analysis_execution_id: Mapped[str] = fk_column("app.analysis_executions.id")
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    role: Mapped[str] = mapped_column(String(64), nullable=False)
