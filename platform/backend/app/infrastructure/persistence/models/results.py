"""Result sets, filter definitions, ranking configurations and saved views.

Filtering and ranking are separate concepts with separate tables and separate
scopes (personal / project / organization / platform). A result set points at the
analytical (Parquet/DuckDB) location of the large result matrix — the rows
themselves are never copied into PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    ConfigurationScope,
    DeletionState,
    ResultSetState,
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


class ResultSet(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """An analysis execution's result surface. Immutable content, tracked state."""

    __tablename__ = "result_sets"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        UniqueConstraint("analysis_execution_id", "result_key",
                         name="uq_result_sets_analysis_execution_id_result_key"),
        state_check("state", ResultSetState, "state_valid"),
        Index("ix_result_sets_workspace_id_state", "workspace_id", "state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    analysis_execution_id: Mapped[str] = fk_column("app.analysis_executions.id")
    result_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ResultSetState.PENDING.value
    )
    #: Analytical layer location (Parquet dataset root / partition expression).
    analytical_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    scientific_artifact_id: Mapped[str | None] = fk_column(
        "app.scientific_artifacts.id", nullable=True
    )
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Column contract of the analytical dataset, used by the filtering engine.
    column_schema: Mapped[dict | None] = json_column()
    #: Denormalized provenance so a result set can be read on its own.
    provenance_manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class FilterDefinition(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """A saved, versioned filter definition. Distinct from ranking."""

    __tablename__ = "filter_definitions"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        UniqueConstraint("scope", "scope_id", "name",
                         name="uq_filter_definitions_scope_scope_id_name"),
        state_check("scope", ConfigurationScope, "scope_valid"),
        Index("ix_filter_definitions_scope_scope_id", "scope", "scope_id"),
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Owning user / project / organization; null for platform scope.
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False,
                                                        server_default="1")
    #: Nested AND/OR predicate tree, validated server-side against the schema.
    predicate_tree: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class FilterDefinitionVersion(Base, TimestampMixin):
    __tablename__ = "filter_definition_versions"
    __table_args__ = (
        UniqueConstraint("filter_definition_id", "version_number",
                         name="uq_filter_definition_versions_definition_id_version_number"),
    )

    id: Mapped[str] = id_column()
    filter_definition_id: Mapped[str] = fk_column("app.filter_definitions.id",
                                                  ondelete="CASCADE")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    predicate_tree: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class RankingConfiguration(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """A ranking method configuration. Ranking never mutates filtering."""

    __tablename__ = "ranking_configurations"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        UniqueConstraint("scope", "scope_id", "name",
                         name="uq_ranking_configurations_scope_scope_id_name"),
        state_check("scope", ConfigurationScope, "scope_valid"),
        Index("ix_ranking_configurations_scope_scope_id", "scope", "scope_id"),
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: Method identity is a scientific concern; only its identity is stored.
    method_key: Mapped[str] = mapped_column(String(128), nullable=False)
    method_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    method_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False,
                                                        server_default="1")
    weights: Mapped[dict | None] = json_column()
    parameters: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class RankingConfigurationVersion(Base, TimestampMixin):
    __tablename__ = "ranking_configuration_versions"
    __table_args__ = (
        UniqueConstraint("ranking_configuration_id", "version_number",
                         name="uq_ranking_configuration_versions_configuration_id_version"),
    )

    id: Mapped[str] = id_column()
    ranking_configuration_id: Mapped[str] = fk_column("app.ranking_configurations.id",
                                                      ondelete="CASCADE")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    method_key: Mapped[str] = mapped_column(String(128), nullable=False)
    method_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    weights: Mapped[dict | None] = json_column()
    parameters: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class SavedView(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """A saved presentation view: column selection, sort, filter + ranking refs."""

    __tablename__ = "saved_views"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        UniqueConstraint("scope", "scope_id", "name",
                         name="uq_saved_views_scope_scope_id_name"),
        state_check("scope", ConfigurationScope, "scope_valid"),
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filter_definition_id: Mapped[str | None] = fk_column(
        "app.filter_definitions.id", nullable=True
    )
    ranking_configuration_id: Mapped[str | None] = fk_column(
        "app.ranking_configurations.id", nullable=True
    )
    column_layout: Mapped[dict | None] = json_column()
    sort_specification: Mapped[dict | None] = json_column()
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
