"""Reports and exports.

Reports and exports are distinct concepts and neither is the interactive result
surface. A finalized report version stores its own immutable snapshot plus the
interpretation version identities it was built from, so later reclassification
can never mutate a historical report. Exports are asynchronous, authorized,
expiring artifacts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    DeletionState,
    ExportFormat,
    ExportState,
    ReportState,
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


class ReportTemplate(Base, TimestampMixin, ConcurrencyMixin):
    """A versioned report template definition."""

    __tablename__ = "report_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "version_number",
                         name="uq_report_templates_template_key_version_number"),
    )

    id: Mapped[str] = id_column()
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Owning scope; platform templates leave the owner columns null.
    organization_id: Mapped[str | None] = fk_column("app.organizations.id", nullable=True)
    definition: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class Report(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    __tablename__ = "reports"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check("state", ReportState, "state_valid"),
        Index("ix_reports_workspace_id_state", "workspace_id", "state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    report_template_id: Mapped[str | None] = fk_column("app.report_templates.id", nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ReportState.DRAFT.value
    )
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False,
                                                        server_default="0")
    created_by: Mapped[str] = fk_column("app.users.id")


class ReportVersion(Base, TimestampMixin):
    """Immutable report version. Never rewritten when interpretations change."""

    __tablename__ = "report_versions"
    __table_args__ = (
        UniqueConstraint("report_id", "version_number",
                         name="uq_report_versions_report_id_version_number"),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
    )

    id: Mapped[str] = id_column()
    report_id: Mapped[str] = fk_column("app.reports.id")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    report_template_id: Mapped[str | None] = fk_column("app.report_templates.id", nullable=True)
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    result_set_id: Mapped[str | None] = fk_column("app.result_sets.id", nullable=True)
    #: Rendered content snapshot; the authoritative historical record.
    content_snapshot: Mapped[dict | None] = json_column()
    provenance_manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rendered_file_artifact_id: Mapped[str | None] = fk_column(
        "app.file_artifacts.id", nullable=True
    )
    checksum_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    authored_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    approved_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    finalized_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ReportVersionInterpretation(Base, TimestampMixin):
    """The exact interpretation versions a report version included."""

    __tablename__ = "report_version_interpretations"
    __table_args__ = (
        UniqueConstraint("report_version_id", "interpretation_version_id",
                         name="uq_report_version_interpretations_version_interpretation"),
    )

    id: Mapped[str] = id_column()
    report_version_id: Mapped[str] = fk_column("app.report_versions.id")
    interpretation_version_id: Mapped[str] = fk_column("app.interpretation_versions.id")
    #: Presentation ordering / section placement inside the report.
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_key: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ExportRequest(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """An asynchronous, authorized, expiring export."""

    __tablename__ = "export_requests"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check("state", ExportState, "state_valid"),
        state_check("export_format", ExportFormat, "export_format_valid"),
        Index("ix_export_requests_workspace_id_state", "workspace_id", "state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    #: What is being exported: result set, report version or dataset version.
    result_set_id: Mapped[str | None] = fk_column("app.result_sets.id", nullable=True)
    report_version_id: Mapped[str | None] = fk_column("app.report_versions.id", nullable=True)
    dataset_version_id: Mapped[str | None] = fk_column("app.dataset_versions.id", nullable=True)
    export_format: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ExportState.REQUESTED.value
    )
    #: Filter/ranking/column selection applied at request time.
    export_specification: Mapped[dict | None] = json_column()
    filter_definition_id: Mapped[str | None] = fk_column(
        "app.filter_definitions.id", nullable=True
    )
    ranking_configuration_id: Mapped[str | None] = fk_column(
        "app.ranking_configurations.id", nullable=True
    )
    requested_by: Mapped[str] = fk_column("app.users.id")
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_artifact_id: Mapped[str | None] = fk_column("app.file_artifacts.id", nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
