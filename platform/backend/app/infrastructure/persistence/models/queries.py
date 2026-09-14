"""Filter presets, ranking presets and query execution records.

Package 2 already gave the schema a saved filter, a saved ranking configuration
and a saved view, each with a version child table. Package 7 keeps those tables
and extends them (see ``results.py`` and migration ``0007``) rather than
introducing a parallel set — a second filter table would be a second filtering
architecture.

What genuinely did not exist yet lives here:

* **Presets.** A preset holds the same canonical expression a saved filter holds,
  but it is governed differently: who may publish one, and to whom it is offered.
  Governance is a different lifecycle, not a different engine, so presets get
  their own tables while sharing the expression representation exactly.
* **Executions.** What was actually run, frozen at the moment it ran. This is the
  reproducibility record: it stores the *effective* canonical expression together
  with the identity and version of everything that produced it, so publishing a
  new preset version tomorrow cannot change what a query returned today.

Filtering and ranking executions are two tables, not one with nullable ranking
columns, because a query with no ranking must be distinguishable from a query
ranked by nothing. The ranking row simply does not exist in the first case.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DeletionState,
    QueryDefinitionState,
    QueryExecutionOutcome,
    QueryScope,
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


class _PresetColumns:
    """Columns shared by the filter and ranking preset tables."""

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=QueryDefinitionState.DRAFT.value
    )
    #: The scope's context identifier (workspace / project / organization / user).
    #: Null for platform scope, which has no tenant.
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    organization_id: Mapped[str | None] = fk_column("app.organizations.id", nullable=True)
    #: Highest version number issued. Never decreases, so a withdrawn version's
    #: number is never handed out again.
    latest_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    #: Set once any version was referenced by an analysis execution. From then on
    #: the metadata may still change, but no existing version may.
    is_referenced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    applicable_contexts: Mapped[dict | None] = json_column()
    metadata_json: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class _PresetVersionColumns:
    """Columns shared by the filter and ranking preset version tables.

    Append-only: no ``version`` column, because there is nothing to overwrite.
    """

    id: Mapped[str] = id_column()
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Canonical, validated content plus its hash. Stored canonically so two
    #: configurations that mean the same thing hash identically.
    canonical: Mapped[dict | None] = json_column()
    canonical_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    field_dictionary_version: Mapped[str] = mapped_column(String(64), nullable=False)
    required_field_ids: Mapped[dict | None] = json_column()
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_referenced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    metadata_json: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class FilterPreset(Base, _PresetColumns, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """A curated filter offered within a scope."""

    __tablename__ = "filter_presets"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check("scope", QueryScope, "scope_valid"),
        state_check("state", QueryDefinitionState, "state_valid"),
        UniqueConstraint("scope", "scope_id", "name", name="uq_filter_presets_scope_scope_id_name"),
        Index("ix_filter_presets_scope_state", "scope", "state"),
    )


class FilterPresetVersion(Base, _PresetVersionColumns, TimestampMixin):
    """One immutable published preset expression."""

    __tablename__ = "filter_preset_versions"
    __table_args__ = (
        UniqueConstraint(
            "filter_preset_id", "version_number", name="uq_filter_preset_versions_preset_version"
        ),
    )

    filter_preset_id: Mapped[str] = fk_column("app.filter_presets.id", ondelete="CASCADE")
    condition_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class RankingPreset(Base, _PresetColumns, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """A curated ranking configuration offered within a scope."""

    __tablename__ = "ranking_presets"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check("scope", QueryScope, "scope_valid"),
        state_check("state", QueryDefinitionState, "state_valid"),
        UniqueConstraint(
            "scope", "scope_id", "name", name="uq_ranking_presets_scope_scope_id_name"
        ),
        Index("ix_ranking_presets_scope_state", "scope", "state"),
    )

    method_id: Mapped[str] = mapped_column(String(128), nullable=False)


class RankingPresetVersion(Base, _PresetVersionColumns, TimestampMixin):
    """One immutable published ranking preset configuration."""

    __tablename__ = "ranking_preset_versions"
    __table_args__ = (
        UniqueConstraint(
            "ranking_preset_id", "version_number", name="uq_ranking_preset_versions_preset_version"
        ),
    )

    ranking_preset_id: Mapped[str] = fk_column("app.ranking_presets.id", ondelete="CASCADE")
    method_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    component_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class FilterExecution(Base, TimestampMixin):
    """What a filtered query actually executed. Append-only.

    Every identity here is resolved *before* the query runs and never revisited,
    which is what makes an execution reproducible after the definitions it came
    from have moved on.
    """

    __tablename__ = "filter_executions"
    __table_args__ = (
        state_check("outcome", QueryExecutionOutcome, "outcome_valid"),
        Index("ix_filter_executions_workspace_id_executed_at", "workspace_id", "executed_at"),
        Index("ix_filter_executions_result_set_id", "result_set_id"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    executed_by: Mapped[str] = fk_column("app.users.id")
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_set_id: Mapped[str] = fk_column("app.result_sets.id")
    dataset_version_id: Mapped[str | None] = fk_column("app.dataset_versions.id", nullable=True)
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    #: The combined expression that ran, canonical, plus its hash.
    effective_canonical: Mapped[dict | None] = json_column()
    effective_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    field_dictionary_version: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    filter_definition_id: Mapped[str | None] = fk_column(
        "app.filter_definitions.id", nullable=True
    )
    filter_version_id: Mapped[str | None] = fk_column(
        "app.filter_definition_versions.id", nullable=True
    )
    filter_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filter_preset_id: Mapped[str | None] = fk_column("app.filter_presets.id", nullable=True)
    filter_preset_version_id: Mapped[str | None] = fk_column(
        "app.filter_preset_versions.id", nullable=True
    )
    filter_preset_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The caller's own conditions, kept separable from the preset's so a preset's
    #: identity stays resolvable in the combined expression.
    custom_canonical: Mapped[dict | None] = json_column()
    returned_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: Null means "not computed" — never zero. A total is only stored when it was
    #: actually counted.
    total_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Per-condition surviving counts, present only when requested and computed.
    step_counts: Mapped[dict | None] = json_column()
    software_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class RankingExecution(Base, TimestampMixin):
    """The ranking half of an execution. Append-only, and separate on purpose."""

    __tablename__ = "ranking_executions"
    __table_args__ = (
        state_check("outcome", QueryExecutionOutcome, "outcome_valid"),
        Index("ix_ranking_executions_filter_execution_id", "filter_execution_id"),
    )

    id: Mapped[str] = id_column()
    filter_execution_id: Mapped[str] = fk_column("app.filter_executions.id")
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    executed_by: Mapped[str] = fk_column("app.users.id")
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The exact implementation the score came from, so a rerun is verifiable.
    method_implementation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_canonical: Mapped[dict | None] = json_column()
    effective_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    field_dictionary_version: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    tie_breakers: Mapped[dict | None] = json_column()
    outcome: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=QueryExecutionOutcome.COMPLETED.value
    )
    ranking_definition_id: Mapped[str | None] = fk_column(
        "app.ranking_configurations.id", nullable=True
    )
    ranking_version_id: Mapped[str | None] = fk_column(
        "app.ranking_configuration_versions.id", nullable=True
    )
    ranking_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ranking_preset_id: Mapped[str | None] = fk_column("app.ranking_presets.id", nullable=True)
    ranking_preset_version_id: Mapped[str | None] = fk_column(
        "app.ranking_preset_versions.id", nullable=True
    )
    ranking_preset_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    scored_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: Rows no component could score. Surfaced because an unscored variant is a
    #: data-completeness fact, not a low-priority variant.
    unscored_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


__all__ = [
    "FilterExecution",
    "FilterPreset",
    "FilterPresetVersion",
    "RankingExecution",
    "RankingPreset",
    "RankingPresetVersion",
]
