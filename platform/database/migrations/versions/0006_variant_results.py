"""Variant representation history, membership, result artifacts and ingestion.

Additive revision on top of Packages 2-5. It owns four new tables:

* ``app.variant_representations`` — the normalization *history*. Package 2 gave a
  variant one canonical form; a scientific data layer needs every attempt,
  including the ones that failed and the ones that could not be tried, so an
  absent canonical form is explainable from the database.
* ``app.dataset_version_variants`` — membership of a canonical variant in an
  immutable dataset version, carrying its own ``workspace_id`` because canonical
  variants are shared reference data with no tenant of their own.
* ``app.result_artifacts`` — the stored objects a result set is made of, with
  checksum and column contract. Result *rows* never enter PostgreSQL; they live
  in object storage as Parquet and are read through DuckDB.
* ``app.result_ingestion_requests`` — the ingestion workflow, kept separate from
  the result surface it produces, with the idempotency key that makes engine
  redelivery safe rather than duplicating a scientific result.

Existing tables are extended, never rewritten:

* ``app.variants`` gains ``origin`` and ``scientific_execution_id`` so an
  imported canonical form and an engine-generated one stay distinguishable.
* ``app.result_sets`` gains declared completeness, the full provenance tuple
  (engine, engine version, environment, container digest, node identity,
  reference genome, resource identities, parameters digest), a supersession
  pointer and failure/withdrawal fields.
* ``app.population_frequency_observations`` gains ``subset_key`` and
  ``scientific_execution_id``.
* ``app.clinical_assertions`` gains condition namespace, assertion method,
  assertion/evaluation timestamps, ``value_semantics`` and
  ``scientific_execution_id``.

The widened vocabularies (``normalization_state``, ``result_set_state``) are
persisted as ``VARCHAR + CHECK``, so widening is an ordinary transactional
constraint replacement. Every added column is nullable or carries a server
default: existing rows keep exactly the meaning they had.

Revision ID: 0006_variant_results
Revises: 0005_analysis_jobs
"""

from __future__ import annotations

from alembic import op

from app.domain.value_objects.enums import (
    DataOrigin,
    NormalizationState,
    ResultCompleteness,
    ResultSetState,
    ValueSemantics,
)
from app.infrastructure.persistence.models import Base

revision = "0006_variant_results"
down_revision = "0005_analysis_jobs"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.variant_representations",
    "app.dataset_version_variants",
    "app.result_artifacts",
    "app.result_ingestion_requests",
)

_APP = "app"


def _vocabulary(vocabulary) -> str:  # noqa: ANN001 - StrEnum subclass
    return ", ".join(f"'{member.value}'" for member in vocabulary)


def _replace_check(table: str, column: str, constraint: str, vocabulary) -> None:  # noqa: ANN001
    op.execute(f"ALTER TABLE {_APP}.{table} DROP CONSTRAINT ck_{table}_{constraint}")
    op.execute(
        f"ALTER TABLE {_APP}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
        f"CHECK ({column} IN ({_vocabulary(vocabulary)}))"
    )


def _add_state_column(
    table: str,
    column: str,
    vocabulary,  # noqa: ANN001 - StrEnum subclass
    default: str,
    constraint: str,
) -> None:
    op.execute(
        f"ALTER TABLE {_APP}.{table} "
        f"ADD COLUMN {column} VARCHAR(64) NOT NULL DEFAULT '{default}'"
    )
    op.execute(
        f"ALTER TABLE {_APP}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
        f"CHECK ({column} IN ({_vocabulary(vocabulary)}))"
    )


#: Columns added to ``app.result_sets``: everything needed to answer "under what
#: scientific context was this produced?" without consulting another table.
_RESULT_SET_COLUMNS: tuple[str, ...] = (
    "ADD COLUMN engine_version VARCHAR(128)",
    "ADD COLUMN environment_version VARCHAR(128)",
    "ADD COLUMN container_image_digest VARCHAR(255)",
    "ADD COLUMN node_identity VARCHAR(255)",
    "ADD COLUMN resource_identities JSONB",
    "ADD COLUMN parameters_digest VARCHAR(128)",
    "ADD COLUMN superseded_by_result_set_id VARCHAR(64)",
    "ADD COLUMN invalidation_reason TEXT",
    "ADD COLUMN failure_code VARCHAR(128)",
    "ADD COLUMN failure_message TEXT",
    "ADD COLUMN available_at TIMESTAMP WITH TIME ZONE",
)

_RESULT_SET_REFERENCES: tuple[tuple[str, str], ...] = (
    ("scientific_execution_id", "app.scientific_executions(id)"),
    ("analysis_configuration_id", "app.analysis_configurations(id)"),
    ("engine_resource_id", "app.scientific_resources(id)"),
    ("reference_genome_resource_id", "app.scientific_resources(id)"),
)


def upgrade() -> None:
    connection = op.get_bind()

    # --- variants ---------------------------------------------------------- #
    # A canonical form that could not be normalized is now expressible, so the
    # absence of normalization stops looking like a scientific statement.
    _replace_check("variants", "normalization_state", "normalization_state_valid", NormalizationState)
    _add_state_column(
        "variants", "origin", DataOrigin, DataOrigin.GENERATED.value, "origin_valid"
    )
    op.execute(
        "ALTER TABLE app.variants ADD COLUMN scientific_execution_id VARCHAR(64) "
        "REFERENCES app.scientific_executions(id) ON DELETE RESTRICT"
    )

    # --- variant_source_representations ------------------------------------ #
    _replace_check(
        "variant_source_representations",
        "normalization_state",
        "normalization_state_valid",
        NormalizationState,
    )

    # --- population_frequency_observations --------------------------------- #
    op.execute(
        "ALTER TABLE app.population_frequency_observations ADD COLUMN subset_key VARCHAR(128)"
    )
    op.execute(
        "ALTER TABLE app.population_frequency_observations "
        "ADD COLUMN scientific_execution_id VARCHAR(64) "
        "REFERENCES app.scientific_executions(id) ON DELETE RESTRICT"
    )

    # --- clinical_assertions ----------------------------------------------- #
    for statement in (
        "ADD COLUMN condition_namespace VARCHAR(64)",
        "ADD COLUMN assertion_method VARCHAR(255)",
        "ADD COLUMN asserted_at TIMESTAMP WITH TIME ZONE",
        "ADD COLUMN last_evaluated_at TIMESTAMP WITH TIME ZONE",
    ):
        op.execute(f"ALTER TABLE app.clinical_assertions {statement}")
    _add_state_column(
        "clinical_assertions",
        "value_semantics",
        ValueSemantics,
        ValueSemantics.PRESENT.value,
        "value_semantics_valid",
    )
    op.execute(
        "ALTER TABLE app.clinical_assertions ADD COLUMN scientific_execution_id VARCHAR(64) "
        "REFERENCES app.scientific_executions(id) ON DELETE RESTRICT"
    )

    # --- result_sets ------------------------------------------------------- #
    # VALIDATED / FAILED / SUPERSEDED join the vocabulary. Content immutability
    # remains a separate property: a corrected run produces a *new* result set.
    _replace_check("result_sets", "state", "state_valid", ResultSetState)
    for statement in _RESULT_SET_COLUMNS:
        op.execute(f"ALTER TABLE app.result_sets {statement}")
    for column, target in _RESULT_SET_REFERENCES:
        op.execute(
            f"ALTER TABLE app.result_sets ADD COLUMN {column} VARCHAR(64) "
            f"REFERENCES {target} ON DELETE RESTRICT"
        )
    _add_state_column(
        "result_sets",
        "completeness",
        ResultCompleteness,
        ResultCompleteness.UNKNOWN.value,
        "completeness_valid",
    )
    _add_state_column(
        "result_sets", "origin", DataOrigin, DataOrigin.GENERATED.value, "origin_valid"
    )
    op.execute("CREATE INDEX ix_result_sets_project_id ON app.result_sets (project_id)")

    # --- new tables -------------------------------------------------------- #
    owned = set(TABLES)
    tables = [
        table
        for table in Base.metadata.sorted_tables
        if f"{table.schema or _APP}.{table.name}" in owned
    ]
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=False)


def downgrade() -> None:
    connection = op.get_bind()
    owned = set(TABLES)
    tables = [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if f"{table.schema or _APP}.{table.name}" in owned
    ]
    Base.metadata.drop_all(bind=connection, tables=tables, checkfirst=False)

    op.execute("DROP INDEX app.ix_result_sets_project_id")
    op.execute("ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_origin_valid")
    op.execute("ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_completeness_valid")
    for column, _ in reversed(_RESULT_SET_REFERENCES):
        op.execute(f"ALTER TABLE app.result_sets DROP COLUMN {column}")
    for statement in reversed(_RESULT_SET_COLUMNS):
        column = statement.split()[2]
        op.execute(f"ALTER TABLE app.result_sets DROP COLUMN {column}")
    op.execute("ALTER TABLE app.result_sets DROP COLUMN completeness")
    op.execute("ALTER TABLE app.result_sets DROP COLUMN origin")
    op.execute("ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_state_valid")
    op.execute(
        "ALTER TABLE app.result_sets ADD CONSTRAINT ck_result_sets_state_valid "
        "CHECK (state IN ('pending', 'generating', 'available', 'invalidated', 'expired'))"
    )

    op.execute("ALTER TABLE app.clinical_assertions DROP COLUMN scientific_execution_id")
    op.execute(
        "ALTER TABLE app.clinical_assertions DROP CONSTRAINT "
        "ck_clinical_assertions_value_semantics_valid"
    )
    for column in (
        "value_semantics",
        "last_evaluated_at",
        "asserted_at",
        "assertion_method",
        "condition_namespace",
    ):
        op.execute(f"ALTER TABLE app.clinical_assertions DROP COLUMN {column}")

    for column in ("scientific_execution_id", "subset_key"):
        op.execute(f"ALTER TABLE app.population_frequency_observations DROP COLUMN {column}")

    op.execute("ALTER TABLE app.variants DROP COLUMN scientific_execution_id")
    op.execute("ALTER TABLE app.variants DROP CONSTRAINT ck_variants_origin_valid")
    op.execute("ALTER TABLE app.variants DROP COLUMN origin")

    _legacy = (
        "CHECK (normalization_state IN ('not_normalized', 'normalized', "
        "'normalization_failed'))"
    )
    for table in ("variants", "variant_source_representations"):
        op.execute(
            f"ALTER TABLE app.{table} DROP CONSTRAINT ck_{table}_normalization_state_valid"
        )
        op.execute(
            f"ALTER TABLE app.{table} ADD CONSTRAINT "
            f"ck_{table}_normalization_state_valid {_legacy}"
        )
