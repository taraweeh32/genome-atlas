"""Dataset ingestion: upload sessions, column mappings and ingest metadata.

Additive revision on top of the Package 2 baseline. It owns two new tables and
extends existing dataset/ingest tables with the columns the upload, import and
validation lifecycle needs:

* ``app.upload_sessions`` — server-issued permission to transfer bytes, and the
  gate deciding whether those bytes may become a scientific input.
* ``app.dataset_column_mappings`` — one row per source column of a tabular
  import, recording the declared meaning and whether a human chose it.

Existing tables gain declared-vs-detected format columns, a malware-scan state,
validator identity on validation runs, and an explicit finding category/code on
validation issues. The ``value_semantics`` vocabulary is widened so ``null``,
``empty`` and ``na`` are no longer collapsed into ``missing``; because state
vocabularies are persisted as ``VARCHAR + CHECK`` (never as a PostgreSQL enum),
widening is an ordinary transactional constraint replacement.

Nothing here drops or rewrites data: every added column is nullable or carries a
server default, so existing rows keep their meaning.

Revision ID: 0004_dataset_ingest
Revises: 0003_identity_sessions
"""

from __future__ import annotations

from alembic import op

from app.domain.value_objects.enums import (
    CompressionKind,
    InputFormat,
    MalwareScanState,
    ReferenceBuildDeclaration,
    ValidationCategory,
    ValueSemantics,
)
from app.infrastructure.persistence.models import Base

revision = "0004_dataset_ingest"
down_revision = "0003_identity_sessions"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.upload_sessions",
    "app.dataset_column_mappings",
)

_SCHEMA = "app"


def _vocabulary(vocabulary) -> str:  # noqa: ANN001 - StrEnum subclass
    values = ", ".join(f"'{member.value}'" for member in vocabulary)
    return values


def _add_state_column(
    table: str,
    column: str,
    vocabulary,  # noqa: ANN001 - StrEnum subclass
    default: str,
    constraint: str,
) -> None:
    """Add a vocabulary-constrained column with a safe default for existing rows."""
    op.execute(
        f"ALTER TABLE {_SCHEMA}.{table} "
        f"ADD COLUMN {column} VARCHAR(64) NOT NULL DEFAULT '{default}'"
    )
    op.execute(
        f"ALTER TABLE {_SCHEMA}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
        f"CHECK ({column} IN ({_vocabulary(vocabulary)}))"
    )


def upgrade() -> None:
    connection = op.get_bind()

    # --- datasets ---------------------------------------------------------- #
    _add_state_column(
        "datasets",
        "reference_build_declared",
        ReferenceBuildDeclaration,
        ReferenceBuildDeclaration.UNSPECIFIED.value,
        "reference_build_valid",
    )

    # --- dataset_versions -------------------------------------------------- #
    for column, vocabulary, default, constraint in (
        ("declared_format", InputFormat, InputFormat.UNKNOWN.value, "declared_format_valid"),
        ("detected_format", InputFormat, InputFormat.UNKNOWN.value, "detected_format_valid"),
        ("compression", CompressionKind, CompressionKind.UNKNOWN.value, "compression_valid"),
        (
            "reference_build_declared",
            ReferenceBuildDeclaration,
            ReferenceBuildDeclaration.UNSPECIFIED.value,
            "reference_build_valid",
        ),
    ):
        _add_state_column("dataset_versions", column, vocabulary, default, constraint)

    # --- file_artifacts ---------------------------------------------------- #
    _add_state_column(
        "file_artifacts",
        "scan_state",
        MalwareScanState,
        MalwareScanState.NOT_SCANNED.value,
        "scan_state_valid",
    )
    op.execute("ALTER TABLE app.file_artifacts ADD COLUMN scan_detail TEXT")
    op.execute("ALTER TABLE app.file_artifacts ADD COLUMN original_filename VARCHAR(512)")
    for column, vocabulary, default, constraint in (
        ("declared_format", InputFormat, InputFormat.UNKNOWN.value, "declared_format_valid"),
        ("detected_format", InputFormat, InputFormat.UNKNOWN.value, "detected_format_valid"),
        ("compression", CompressionKind, CompressionKind.UNKNOWN.value, "compression_valid"),
    ):
        _add_state_column("file_artifacts", column, vocabulary, default, constraint)

    # --- import_sessions --------------------------------------------------- #
    op.execute(
        "ALTER TABLE app.import_sessions ADD COLUMN file_artifact_id VARCHAR(64) "
        "REFERENCES app.file_artifacts(id) ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE INDEX ix_import_sessions_file_artifact_id "
        "ON app.import_sessions (file_artifact_id)"
    )
    for column, vocabulary, default, constraint in (
        ("declared_format", InputFormat, InputFormat.UNKNOWN.value, "declared_format_valid"),
        ("detected_format", InputFormat, InputFormat.UNKNOWN.value, "detected_format_valid"),
        (
            "reference_build_declared",
            ReferenceBuildDeclaration,
            ReferenceBuildDeclaration.UNSPECIFIED.value,
            "reference_build_valid",
        ),
    ):
        _add_state_column("import_sessions", column, vocabulary, default, constraint)
    op.execute("ALTER TABLE app.import_sessions ADD COLUMN importer_version VARCHAR(64)")
    op.execute("ALTER TABLE app.import_sessions ADD COLUMN idempotency_key VARCHAR(255)")
    op.execute("ALTER TABLE app.import_sessions ADD COLUMN correlation_id VARCHAR(64)")
    op.execute(
        "ALTER TABLE app.import_sessions "
        "ADD COLUMN mapping_confirmed_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE app.import_sessions "
        "ADD CONSTRAINT uq_import_sessions_idempotency_key UNIQUE (idempotency_key)"
    )
    op.execute(
        "CREATE INDEX ix_import_sessions_correlation_id "
        "ON app.import_sessions (correlation_id)"
    )

    # --- validation_runs --------------------------------------------------- #
    op.execute(
        "ALTER TABLE app.validation_runs ADD COLUMN validator_name VARCHAR(128) "
        "NOT NULL DEFAULT 'platform.input_validator'"
    )
    op.execute(
        "ALTER TABLE app.validation_runs ADD COLUMN validator_version VARCHAR(64) "
        "NOT NULL DEFAULT '1'"
    )

    # --- validation_issues ------------------------------------------------- #
    _add_state_column(
        "validation_issues",
        "category",
        ValidationCategory,
        ValidationCategory.STRUCTURE.value,
        "category_valid",
    )
    op.execute(
        "ALTER TABLE app.validation_issues ADD COLUMN code VARCHAR(128) "
        "NOT NULL DEFAULT 'unspecified'"
    )
    # Widen the value-semantics vocabulary: null/empty/na become first-class,
    # instead of being flattened into "missing".
    op.execute(
        "ALTER TABLE app.validation_issues "
        "DROP CONSTRAINT ck_validation_issues_value_semantics_valid"
    )
    op.execute(
        "ALTER TABLE app.validation_issues "
        "ADD CONSTRAINT ck_validation_issues_value_semantics_valid "
        f"CHECK (value_semantics IN ({_vocabulary(ValueSemantics)}))"
    )

    # --- new tables -------------------------------------------------------- #
    owned = set(TABLES)
    tables = [
        table
        for table in Base.metadata.sorted_tables
        if f"{table.schema or _SCHEMA}.{table.name}" in owned
    ]
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=False)


def downgrade() -> None:
    connection = op.get_bind()
    owned = set(TABLES)
    tables = [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if f"{table.schema or _SCHEMA}.{table.name}" in owned
    ]
    Base.metadata.drop_all(bind=connection, tables=tables, checkfirst=False)

    op.execute(
        "ALTER TABLE app.validation_issues "
        "DROP CONSTRAINT ck_validation_issues_value_semantics_valid"
    )
    op.execute(
        "ALTER TABLE app.validation_issues "
        "ADD CONSTRAINT ck_validation_issues_value_semantics_valid CHECK (value_semantics IN "
        "('present', 'missing', 'unknown', 'not_applicable', 'zero', 'false'))"
    )
    op.execute("ALTER TABLE app.validation_issues DROP COLUMN code")
    op.execute("ALTER TABLE app.validation_issues DROP COLUMN category")
    op.execute("ALTER TABLE app.validation_runs DROP COLUMN validator_version")
    op.execute("ALTER TABLE app.validation_runs DROP COLUMN validator_name")
    for column in (
        "mapping_confirmed_at",
        "correlation_id",
        "idempotency_key",
        "importer_version",
        "reference_build_declared",
        "detected_format",
        "declared_format",
        "file_artifact_id",
    ):
        op.execute(f"ALTER TABLE app.import_sessions DROP COLUMN {column}")
    for column in (
        "compression",
        "detected_format",
        "declared_format",
        "original_filename",
        "scan_detail",
        "scan_state",
    ):
        op.execute(f"ALTER TABLE app.file_artifacts DROP COLUMN {column}")
    for column in (
        "reference_build_declared",
        "compression",
        "detected_format",
        "declared_format",
    ):
        op.execute(f"ALTER TABLE app.dataset_versions DROP COLUMN {column}")
    op.execute("ALTER TABLE app.datasets DROP COLUMN reference_build_declared")
