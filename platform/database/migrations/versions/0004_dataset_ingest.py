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

This revision is **self-contained**: every statement is literal SQL frozen at
this point in the schema history. It deliberately does not import the current
SQLAlchemy models, ``Base.metadata`` or the domain vocabularies — a migration
must describe the schema as it was, so evolving the ORM can never rewrite
history.

This revision is **self-contained**: every statement is literal SQL frozen at
this point in the schema history. It deliberately does not import the current
SQLAlchemy models, ``Base.metadata`` or the domain vocabularies — a migration
must describe the schema as it was, so evolving the ORM can never rewrite
history.
"""

from __future__ import annotations

from alembic import op

revision = "0004_dataset_ingest"
down_revision = "0003_identity_sessions"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.upload_sessions",
    "app.dataset_column_mappings",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE app.datasets ADD COLUMN reference_build_declared VARCHAR(64) NOT NULL DEFAULT
    'unspecified'
    """,
    """
    ALTER TABLE app.datasets ADD CONSTRAINT ck_datasets_reference_build_valid CHECK
    (reference_build_declared IN ('grch37', 'grch38', 't2t_chm13', 'unspecified'))
    """,
    """
    ALTER TABLE app.dataset_versions ADD COLUMN declared_format VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.dataset_versions ADD CONSTRAINT ck_dataset_versions_declared_format_valid
    CHECK (declared_format IN ('csv', 'tsv', 'vcf', 'bcf', 'text', 'json', 'unknown'))
    """,
    """
    ALTER TABLE app.dataset_versions ADD COLUMN detected_format VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.dataset_versions ADD CONSTRAINT ck_dataset_versions_detected_format_valid
    CHECK (detected_format IN ('csv', 'tsv', 'vcf', 'bcf', 'text', 'json', 'unknown'))
    """,
    """
    ALTER TABLE app.dataset_versions ADD COLUMN compression VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.dataset_versions ADD CONSTRAINT ck_dataset_versions_compression_valid CHECK
    (compression IN ('none', 'gzip', 'bgzf', 'zip', 'unknown'))
    """,
    """
    ALTER TABLE app.dataset_versions ADD COLUMN reference_build_declared VARCHAR(64) NOT NULL
    DEFAULT 'unspecified'
    """,
    """
    ALTER TABLE app.dataset_versions ADD CONSTRAINT ck_dataset_versions_reference_build_valid
    CHECK (reference_build_declared IN ('grch37', 'grch38', 't2t_chm13', 'unspecified'))
    """,
    """
    ALTER TABLE app.file_artifacts ADD COLUMN scan_state VARCHAR(64) NOT NULL DEFAULT
    'not_scanned'
    """,
    """
    ALTER TABLE app.file_artifacts ADD CONSTRAINT ck_file_artifacts_scan_state_valid CHECK
    (scan_state IN ('not_scanned', 'scanning', 'clean', 'infected', 'unavailable', 'failed'))
    """,
    """
    ALTER TABLE app.file_artifacts ADD COLUMN scan_detail TEXT
    """,
    """
    ALTER TABLE app.file_artifacts ADD COLUMN original_filename VARCHAR(512)
    """,
    """
    ALTER TABLE app.file_artifacts ADD COLUMN declared_format VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.file_artifacts ADD CONSTRAINT ck_file_artifacts_declared_format_valid CHECK
    (declared_format IN ('csv', 'tsv', 'vcf', 'bcf', 'text', 'json', 'unknown'))
    """,
    """
    ALTER TABLE app.file_artifacts ADD COLUMN detected_format VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.file_artifacts ADD CONSTRAINT ck_file_artifacts_detected_format_valid CHECK
    (detected_format IN ('csv', 'tsv', 'vcf', 'bcf', 'text', 'json', 'unknown'))
    """,
    """
    ALTER TABLE app.file_artifacts ADD COLUMN compression VARCHAR(64) NOT NULL DEFAULT 'unknown'
    """,
    """
    ALTER TABLE app.file_artifacts ADD CONSTRAINT ck_file_artifacts_compression_valid CHECK
    (compression IN ('none', 'gzip', 'bgzf', 'zip', 'unknown'))
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN file_artifact_id VARCHAR(64) REFERENCES
    app.file_artifacts(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_import_sessions_file_artifact_id ON app.import_sessions (file_artifact_id)
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN declared_format VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.import_sessions ADD CONSTRAINT ck_import_sessions_declared_format_valid
    CHECK (declared_format IN ('csv', 'tsv', 'vcf', 'bcf', 'text', 'json', 'unknown'))
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN detected_format VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE app.import_sessions ADD CONSTRAINT ck_import_sessions_detected_format_valid
    CHECK (detected_format IN ('csv', 'tsv', 'vcf', 'bcf', 'text', 'json', 'unknown'))
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN reference_build_declared VARCHAR(64) NOT NULL
    DEFAULT 'unspecified'
    """,
    """
    ALTER TABLE app.import_sessions ADD CONSTRAINT ck_import_sessions_reference_build_valid
    CHECK (reference_build_declared IN ('grch37', 'grch38', 't2t_chm13', 'unspecified'))
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN importer_version VARCHAR(64)
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN idempotency_key VARCHAR(255)
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN correlation_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.import_sessions ADD COLUMN mapping_confirmed_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.import_sessions ADD CONSTRAINT uq_import_sessions_idempotency_key UNIQUE
    (idempotency_key)
    """,
    """
    CREATE INDEX ix_import_sessions_correlation_id ON app.import_sessions (correlation_id)
    """,
    """
    ALTER TABLE app.validation_runs ADD COLUMN validator_name VARCHAR(128) NOT NULL DEFAULT
    'platform.input_validator'
    """,
    """
    ALTER TABLE app.validation_runs ADD COLUMN validator_version VARCHAR(64) NOT NULL DEFAULT
    '1'
    """,
    """
    ALTER TABLE app.validation_issues ADD COLUMN category VARCHAR(64) NOT NULL DEFAULT
    'structure'
    """,
    """
    ALTER TABLE app.validation_issues ADD CONSTRAINT ck_validation_issues_category_valid CHECK
    (category IN ('transfer_integrity', 'security', 'file_format', 'structure',
    'tabular_schema', 'metadata', 'genomic_suitability', 'import_configuration'))
    """,
    """
    ALTER TABLE app.validation_issues ADD COLUMN code VARCHAR(128) NOT NULL DEFAULT
    'unspecified'
    """,
    """
    ALTER TABLE app.validation_issues DROP CONSTRAINT ck_validation_issues_value_semantics_valid
    """,
    """
    ALTER TABLE app.validation_issues ADD CONSTRAINT ck_validation_issues_value_semantics_valid
    CHECK (value_semantics IN ('present', 'missing', 'null', 'empty', 'na', 'unknown',
    'not_applicable', 'zero', 'false'))
    """,
    """
    CREATE TABLE app.upload_sessions ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, project_id VARCHAR(64), dataset_id VARCHAR(64) NOT NULL, dataset_version_id
    VARCHAR(64) NOT NULL, file_artifact_id VARCHAR(64) NOT NULL, state VARCHAR(64) DEFAULT
    'created' NOT NULL, initiated_by VARCHAR(64) NOT NULL, storage_key TEXT NOT NULL,
    declared_filename VARCHAR(512) NOT NULL, declared_size_bytes BIGINT NOT NULL,
    declared_format VARCHAR(64) DEFAULT 'unknown' NOT NULL, declared_checksum_algorithm
    VARCHAR(64) DEFAULT 'sha256' NOT NULL, declared_checksum_value VARCHAR(256), expires_at
    TIMESTAMP WITH TIME ZONE, completed_at TIMESTAMP WITH TIME ZONE, failure_reason TEXT,
    duplicate_relation VARCHAR(64) DEFAULT 'none' NOT NULL, duplicate_of_file_artifact_id
    VARCHAR(64), correlation_id VARCHAR(64), detail JSONB, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version
    INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_upload_sessions PRIMARY KEY (id), CONSTRAINT
    ck_upload_sessions_checksum_algorithm_valid CHECK (declared_checksum_algorithm IN ('sha256',
    'sha512', 'md5', 'crc32c')), CONSTRAINT fk_upload_sessions_initiated_by FOREIGN
    KEY(initiated_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_upload_sessions_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT fk_upload_sessions_project_id
    FOREIGN KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    ck_upload_sessions_declared_format_valid CHECK (declared_format IN ('csv', 'tsv', 'vcf',
    'bcf', 'text', 'json', 'unknown')), CONSTRAINT ck_upload_sessions_state_valid CHECK (state
    IN ('created', 'uploading', 'uploaded', 'scanning', 'quarantined', 'validating', 'accepted',
    'rejected', 'expired', 'cancelled', 'failed')), CONSTRAINT uq_upload_sessions_storage_key
    UNIQUE (storage_key), CONSTRAINT ck_upload_sessions_duplicate_relation_valid CHECK
    (duplicate_relation IN ('none', 'same_checksum_in_scope', 'same_name_in_scope')), CONSTRAINT
    fk_upload_sessions_duplicate_of_file_artifact_id FOREIGN KEY(duplicate_of_file_artifact_id)
    REFERENCES app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT
    fk_upload_sessions_file_artifact_id FOREIGN KEY(file_artifact_id) REFERENCES
    app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT fk_upload_sessions_dataset_id FOREIGN
    KEY(dataset_id) REFERENCES app.datasets (id) ON DELETE RESTRICT, CONSTRAINT
    fk_upload_sessions_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON
    DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_upload_sessions_correlation_id ON app.upload_sessions (correlation_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_dataset_id ON app.upload_sessions (dataset_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_dataset_version_id ON app.upload_sessions
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_duplicate_of_file_artifact_id ON app.upload_sessions
    (duplicate_of_file_artifact_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_expires_at ON app.upload_sessions (expires_at)
    """,
    """
    CREATE INDEX ix_upload_sessions_file_artifact_id ON app.upload_sessions (file_artifact_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_initiated_by ON app.upload_sessions (initiated_by)
    """,
    """
    CREATE INDEX ix_upload_sessions_project_id ON app.upload_sessions (project_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_workspace_id ON app.upload_sessions (workspace_id)
    """,
    """
    CREATE INDEX ix_upload_sessions_workspace_id_state ON app.upload_sessions (workspace_id,
    state)
    """,
    """
    CREATE TABLE app.dataset_column_mappings ( id VARCHAR(64) NOT NULL, import_session_id
    VARCHAR(64) NOT NULL, source_column_name VARCHAR(512) NOT NULL, source_column_index INTEGER
    NOT NULL, status VARCHAR(64) DEFAULT 'unmapped' NOT NULL, origin VARCHAR(64) DEFAULT
    'system_suggested' NOT NULL, target_concept VARCHAR(64) DEFAULT 'ignored' NOT NULL,
    declared_unit VARCHAR(64), sample_value_semantics VARCHAR(64) DEFAULT 'present' NOT NULL,
    notes TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_dataset_column_mappings PRIMARY KEY
    (id), CONSTRAINT fk_dataset_column_mappings_import_session_id FOREIGN KEY(import_session_id)
    REFERENCES app.import_sessions (id) ON DELETE RESTRICT, CONSTRAINT
    ck_dataset_column_mappings_target_concept_valid CHECK (target_concept IN ('chromosome',
    'position', 'reference_allele', 'alternate_allele', 'variant_identifier', 'gene_symbol',
    'transcript_identifier', 'consequence', 'sample_identifier', 'genotype', 'zygosity',
    'read_depth', 'allele_frequency', 'quality', 'filter_status', 'phenotype_term',
    'passthrough', 'ignored')), CONSTRAINT uq_dataset_column_mappings_session_column_index
    UNIQUE (import_session_id, source_column_index), CONSTRAINT
    ck_dataset_column_mappings_value_semantics_valid CHECK (sample_value_semantics IN
    ('present', 'missing', 'null', 'empty', 'na', 'unknown', 'not_applicable', 'zero',
    'false')), CONSTRAINT ck_dataset_column_mappings_status_valid CHECK (status IN ('mapped',
    'unmapped', 'ambiguous', 'ignored')), CONSTRAINT ck_dataset_column_mappings_origin_valid
    CHECK (origin IN ('user_selected', 'system_suggested', 'template_applied')) )
    """,
    """
    CREATE INDEX ix_dataset_column_mappings_import_session_id ON app.dataset_column_mappings
    (import_session_id)
    """,
    """
    CREATE INDEX ix_dataset_column_mappings_import_session_id_status ON
    app.dataset_column_mappings (import_session_id, status)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP TABLE app.dataset_column_mappings
    """,
    """
    DROP TABLE app.upload_sessions
    """,
    """
    ALTER TABLE app.validation_issues DROP CONSTRAINT ck_validation_issues_value_semantics_valid
    """,
    """
    ALTER TABLE app.validation_issues ADD CONSTRAINT ck_validation_issues_value_semantics_valid
    CHECK (value_semantics IN ('present', 'missing', 'unknown', 'not_applicable', 'zero',
    'false'))
    """,
    """
    ALTER TABLE app.validation_issues DROP COLUMN code
    """,
    """
    ALTER TABLE app.validation_issues DROP COLUMN category
    """,
    """
    ALTER TABLE app.validation_runs DROP COLUMN validator_version
    """,
    """
    ALTER TABLE app.validation_runs DROP COLUMN validator_name
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN mapping_confirmed_at
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN correlation_id
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN idempotency_key
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN importer_version
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN reference_build_declared
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN detected_format
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN declared_format
    """,
    """
    ALTER TABLE app.import_sessions DROP COLUMN file_artifact_id
    """,
    """
    ALTER TABLE app.file_artifacts DROP COLUMN compression
    """,
    """
    ALTER TABLE app.file_artifacts DROP COLUMN detected_format
    """,
    """
    ALTER TABLE app.file_artifacts DROP COLUMN declared_format
    """,
    """
    ALTER TABLE app.file_artifacts DROP COLUMN original_filename
    """,
    """
    ALTER TABLE app.file_artifacts DROP COLUMN scan_detail
    """,
    """
    ALTER TABLE app.file_artifacts DROP COLUMN scan_state
    """,
    """
    ALTER TABLE app.dataset_versions DROP COLUMN reference_build_declared
    """,
    """
    ALTER TABLE app.dataset_versions DROP COLUMN compression
    """,
    """
    ALTER TABLE app.dataset_versions DROP COLUMN detected_format
    """,
    """
    ALTER TABLE app.dataset_versions DROP COLUMN declared_format
    """,
    """
    ALTER TABLE app.datasets DROP COLUMN reference_build_declared
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
