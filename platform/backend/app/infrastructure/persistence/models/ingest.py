"""Import session and validation history persistence.

Import history is preserved: a rejected import and the reason for rejection stay
queryable. Validation issues carry an explicit severity
(``info``/``warning``/``error``/``blocking``) and an explicit value-semantics
field so ``missing``, ``unknown``, ``na``, ``zero`` and ``false`` are never
conflated at the database layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    ImportSessionState,
    ValidationRunState,
    ValidationSeverity,
    ValueSemantics,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class ImportSession(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "import_sessions"
    __table_args__ = (
        state_check("state", ImportSessionState, "state_valid"),
        Index("ix_import_sessions_workspace_id_state", "workspace_id", "state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    dataset_id: Mapped[str | None] = fk_column("app.datasets.id", nullable=True)
    dataset_version_id: Mapped[str | None] = fk_column("app.dataset_versions.id", nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ImportSessionState.OPEN.value
    )
    initiated_by: Mapped[str] = fk_column("app.users.id")
    #: Column/field mapping chosen for this import; part of import provenance.
    mapping_metadata: Mapped[dict | None] = json_column()
    import_provenance: Mapped[dict | None] = json_column()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ValidationRule(Base, TimestampMixin):
    """Registry of validation rules referenced by issues."""

    __tablename__ = "validation_rules"
    __table_args__ = (
        UniqueConstraint("rule_key", "rule_version", name="uq_validation_rules_rule_key_version"),
        state_check("default_severity", ValidationSeverity, "default_severity_valid"),
    )

    id: Mapped[str] = id_column()
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    default_severity: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict | None] = json_column()


class ValidationRun(Base, TimestampMixin):
    """One validation pass over an import session / dataset version."""

    __tablename__ = "validation_runs"
    __table_args__ = (
        state_check("state", ValidationRunState, "state_valid"),
        Index("ix_validation_runs_dataset_version_id_state", "dataset_version_id", "state"),
        Index("ix_validation_runs_correlation_id", "correlation_id"),
    )

    id: Mapped[str] = id_column()
    import_session_id: Mapped[str | None] = fk_column("app.import_sessions.id", nullable=True)
    dataset_version_id: Mapped[str | None] = fk_column("app.dataset_versions.id", nullable=True)
    file_artifact_id: Mapped[str | None] = fk_column("app.file_artifacts.id", nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValidationRunState.PENDING.value
    )
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocking_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    warning_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    info_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    summary: Mapped[dict | None] = json_column()


class ValidationIssue(Base, TimestampMixin):
    __tablename__ = "validation_issues"
    __table_args__ = (
        state_check("severity", ValidationSeverity, "severity_valid"),
        state_check("value_semantics", ValueSemantics, "value_semantics_valid"),
        Index("ix_validation_issues_validation_run_id_severity", "validation_run_id", "severity"),
    )

    id: Mapped[str] = id_column()
    validation_run_id: Mapped[str] = fk_column("app.validation_runs.id", ondelete="CASCADE")
    validation_rule_id: Mapped[str | None] = fk_column("app.validation_rules.id", nullable=True)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    #: Where the issue was found: file line/record/field locator.
    locator: Mapped[dict | None] = json_column()
    #: Explicit semantics of the offending value, never normalized away.
    value_semantics: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValueSemantics.PRESENT.value
    )
    observed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = json_column()
