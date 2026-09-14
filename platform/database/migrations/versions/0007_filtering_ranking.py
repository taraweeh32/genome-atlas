"""Filtering, ranking, presets, saved views and execution records.

Additive revision on top of Packages 2-6. Package 2 already declared a saved
filter, a saved ranking configuration and a saved view, each with a version child
table. Those tables are **extended, never rewritten**: a second filter table
would be a second filtering architecture, and existing rows would lose their
meaning.

Extended tables:

* ``app.filter_definitions`` / ``app.ranking_configurations`` gain the definition
  lifecycle (``state``), explicit tenancy (owner / workspace / project /
  organization instead of only an opaque ``scope_id``), the highest issued
  version number and the "already referenced by an execution" flag that makes a
  version immutable.
* ``app.filter_definition_versions`` / ``app.ranking_configuration_versions``
  gain the canonical hash, the field-dictionary version they were validated
  against, their required fields and their size metrics. Without the dictionary
  version a historical expression cannot be re-read with its original meaning.
* ``app.saved_views`` gains explicit tenancy, page size, description and preset
  references. Presentation state only.

New tables:

* ``app.filter_presets`` / ``app.filter_preset_versions`` and
  ``app.ranking_presets`` / ``app.ranking_preset_versions`` — the same expression
  representation as a saved filter, under a different governance lifecycle.
* ``app.filter_executions`` / ``app.ranking_executions`` — append-only records of
  what actually ran, with every identity frozen at execution time. Two tables,
  not one: a query with no ranking must not look like a query ranked by nothing.

The ``scope`` check constraints are re-issued against the ``QueryScope``
vocabulary. The value set is unchanged, so no existing row is affected; the
constraint simply now derives from the vocabulary that owns the concept.

Every added column is nullable or carries a server default, so existing rows keep
exactly the meaning they had.

Revision ID: 0007_filtering_ranking
Revises: 0006_variant_results
"""

from __future__ import annotations

from alembic import op

from app.domain.value_objects.enums import QueryDefinitionState, QueryScope
from app.infrastructure.persistence.models import Base

revision = "0007_filtering_ranking"
down_revision = "0006_variant_results"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.filter_presets",
    "app.filter_preset_versions",
    "app.ranking_presets",
    "app.ranking_preset_versions",
    "app.filter_executions",
    "app.ranking_executions",
)

_APP = "app"

#: Definition tables gain the same lifecycle and tenancy columns, because a saved
#: filter and a saved ranking are governed identically even though they mean
#: entirely different things.
_DEFINITION_TABLES: tuple[str, ...] = ("filter_definitions", "ranking_configurations")

_DEFINITION_COLUMNS: tuple[str, ...] = (
    "ADD COLUMN latest_version_number INTEGER NOT NULL DEFAULT 0",
    "ADD COLUMN is_referenced BOOLEAN NOT NULL DEFAULT false",
    "ADD COLUMN metadata_json JSONB",
)

_DEFINITION_REFERENCES: tuple[tuple[str, str], ...] = (
    ("owner_user_id", "app.users(id)"),
    ("workspace_id", "app.workspaces(id)"),
    ("project_id", "app.projects(id)"),
    ("organization_id", "app.organizations(id)"),
)

#: Version tables gain the reproducibility metadata. ``canonical_hash`` and
#: ``field_dictionary_version`` are nullable because rows written before this
#: revision were never validated against a dictionary, and pretending otherwise
#: would fabricate provenance.
_VERSION_COLUMNS: tuple[str, ...] = (
    "ADD COLUMN canonical_hash VARCHAR(128)",
    "ADD COLUMN field_dictionary_version VARCHAR(64)",
    "ADD COLUMN required_field_ids JSONB",
    "ADD COLUMN change_note TEXT",
    "ADD COLUMN is_referenced BOOLEAN NOT NULL DEFAULT false",
    "ADD COLUMN metadata_json JSONB",
)

_SAVED_VIEW_COLUMNS: tuple[str, ...] = (
    "ADD COLUMN description TEXT",
    "ADD COLUMN page_size INTEGER NOT NULL DEFAULT 50",
    "ADD COLUMN metadata_json JSONB",
)

_SAVED_VIEW_REFERENCES: tuple[tuple[str, str], ...] = (
    ("filter_preset_id", "app.filter_presets(id)"),
    ("ranking_preset_id", "app.ranking_presets(id)"),
    ("owner_user_id", "app.users(id)"),
    ("workspace_id", "app.workspaces(id)"),
    ("project_id", "app.projects(id)"),
    ("organization_id", "app.organizations(id)"),
)


def _vocabulary(vocabulary) -> str:  # noqa: ANN001 - StrEnum subclass
    return ", ".join(f"'{member.value}'" for member in vocabulary)


def _replace_check(table: str, column: str, constraint: str, vocabulary) -> None:  # noqa: ANN001
    op.execute(f"ALTER TABLE {_APP}.{table} DROP CONSTRAINT ck_{table}_{constraint}")
    op.execute(
        f"ALTER TABLE {_APP}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
        f"CHECK ({column} IN ({_vocabulary(vocabulary)}))"
    )


def _add_state_column(table: str, default: str) -> None:
    op.execute(
        f"ALTER TABLE {_APP}.{table} "
        f"ADD COLUMN state VARCHAR(64) NOT NULL DEFAULT '{default}'"
    )
    op.execute(
        f"ALTER TABLE {_APP}.{table} ADD CONSTRAINT ck_{table}_state_valid "
        f"CHECK (state IN ({_vocabulary(QueryDefinitionState)}))"
    )


def _reference(table: str, column: str, target: str) -> None:
    op.execute(
        f"ALTER TABLE {_APP}.{table} ADD COLUMN {column} VARCHAR(64) "
        f"REFERENCES {target} ON DELETE RESTRICT"
    )
    op.execute(f"CREATE INDEX ix_{table}_{column} ON {_APP}.{table} ({column})")


def upgrade() -> None:
    connection = op.get_bind()

    # --- new tables first: saved_views references the preset tables --------- #
    owned = set(TABLES)
    tables = [
        table
        for table in Base.metadata.sorted_tables
        if f"{table.schema or _APP}.{table.name}" in owned
    ]
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=False)

    # --- saved filters and saved rankings ---------------------------------- #
    for table in _DEFINITION_TABLES:
        _replace_check(table, "scope", "scope_valid", QueryScope)
        _add_state_column(table, QueryDefinitionState.DRAFT.value)
        for statement in _DEFINITION_COLUMNS:
            op.execute(f"ALTER TABLE {_APP}.{table} {statement}")
        for column, target in _DEFINITION_REFERENCES:
            _reference(table, column, target)

    # --- version history --------------------------------------------------- #
    for table in ("filter_definition_versions", "ranking_configuration_versions"):
        for statement in _VERSION_COLUMNS:
            op.execute(f"ALTER TABLE {_APP}.{table} {statement}")
    op.execute(
        "ALTER TABLE app.filter_definition_versions "
        "ADD COLUMN condition_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE app.filter_definition_versions ADD COLUMN depth INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE app.ranking_configuration_versions "
        "ADD COLUMN component_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE app.ranking_configuration_versions ADD COLUMN canonical JSONB")

    # --- saved views ------------------------------------------------------- #
    _replace_check("saved_views", "scope", "scope_valid", QueryScope)
    for statement in _SAVED_VIEW_COLUMNS:
        op.execute(f"ALTER TABLE {_APP}.saved_views {statement}")
    for column, target in _SAVED_VIEW_REFERENCES:
        _reference("saved_views", column, target)


def downgrade() -> None:
    connection = op.get_bind()

    for column, _ in reversed(_SAVED_VIEW_REFERENCES):
        op.execute(f"DROP INDEX {_APP}.ix_saved_views_{column}")
        op.execute(f"ALTER TABLE {_APP}.saved_views DROP COLUMN {column}")
    for statement in reversed(_SAVED_VIEW_COLUMNS):
        op.execute(f"ALTER TABLE {_APP}.saved_views DROP COLUMN {statement.split()[2]}")
    _replace_check("saved_views", "scope", "scope_valid", QueryScope)

    op.execute("ALTER TABLE app.ranking_configuration_versions DROP COLUMN canonical")
    op.execute("ALTER TABLE app.ranking_configuration_versions DROP COLUMN component_count")
    op.execute("ALTER TABLE app.filter_definition_versions DROP COLUMN depth")
    op.execute("ALTER TABLE app.filter_definition_versions DROP COLUMN condition_count")
    for table in ("filter_definition_versions", "ranking_configuration_versions"):
        for statement in reversed(_VERSION_COLUMNS):
            op.execute(f"ALTER TABLE {_APP}.{table} DROP COLUMN {statement.split()[2]}")

    for table in _DEFINITION_TABLES:
        for column, _ in reversed(_DEFINITION_REFERENCES):
            op.execute(f"DROP INDEX {_APP}.ix_{table}_{column}")
            op.execute(f"ALTER TABLE {_APP}.{table} DROP COLUMN {column}")
        for statement in reversed(_DEFINITION_COLUMNS):
            op.execute(f"ALTER TABLE {_APP}.{table} DROP COLUMN {statement.split()[2]}")
        op.execute(f"ALTER TABLE {_APP}.{table} DROP CONSTRAINT ck_{table}_state_valid")
        op.execute(f"ALTER TABLE {_APP}.{table} DROP COLUMN state")
        _replace_check(table, "scope", "scope_valid", QueryScope)

    owned = set(TABLES)
    tables = [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if f"{table.schema or _APP}.{table.name}" in owned
    ]
    Base.metadata.drop_all(bind=connection, tables=tables, checkfirst=False)
