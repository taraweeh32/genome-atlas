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

revision = "0006_variant_results"
down_revision = "0005_analysis_jobs"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.variant_representations",
    "app.dataset_version_variants",
    "app.result_artifacts",
    "app.result_ingestion_requests",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE app.variants DROP CONSTRAINT ck_variants_normalization_state_valid
    """,
    """
    ALTER TABLE app.variants ADD CONSTRAINT ck_variants_normalization_state_valid CHECK
    (normalization_state IN ('not_normalized', 'normalized', 'normalization_failed',
    'normalization_unavailable'))
    """,
    """
    ALTER TABLE app.variants ADD COLUMN origin VARCHAR(64) NOT NULL DEFAULT 'generated'
    """,
    """
    ALTER TABLE app.variants ADD CONSTRAINT ck_variants_origin_valid CHECK (origin IN
    ('imported', 'retrieved', 'generated', 'machine_generated', 'human_entered',
    'human_evaluated'))
    """,
    """
    ALTER TABLE app.variants ADD COLUMN scientific_execution_id VARCHAR(64) REFERENCES
    app.scientific_executions(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.variant_source_representations DROP CONSTRAINT
    ck_variant_source_representations_normalization_state_valid
    """,
    """
    ALTER TABLE app.variant_source_representations ADD CONSTRAINT
    ck_variant_source_representations_normalization_state_valid CHECK (normalization_state IN
    ('not_normalized', 'normalized', 'normalization_failed', 'normalization_unavailable'))
    """,
    """
    ALTER TABLE app.population_frequency_observations ADD COLUMN subset_key VARCHAR(128)
    """,
    """
    ALTER TABLE app.population_frequency_observations ADD COLUMN scientific_execution_id
    VARCHAR(64) REFERENCES app.scientific_executions(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.clinical_assertions ADD COLUMN condition_namespace VARCHAR(64)
    """,
    """
    ALTER TABLE app.clinical_assertions ADD COLUMN assertion_method VARCHAR(255)
    """,
    """
    ALTER TABLE app.clinical_assertions ADD COLUMN asserted_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.clinical_assertions ADD COLUMN last_evaluated_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.clinical_assertions ADD COLUMN value_semantics VARCHAR(64) NOT NULL DEFAULT
    'present'
    """,
    """
    ALTER TABLE app.clinical_assertions ADD CONSTRAINT
    ck_clinical_assertions_value_semantics_valid CHECK (value_semantics IN ('present',
    'missing', 'null', 'empty', 'na', 'unknown', 'not_applicable', 'zero', 'false'))
    """,
    """
    ALTER TABLE app.clinical_assertions ADD COLUMN scientific_execution_id VARCHAR(64)
    REFERENCES app.scientific_executions(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_state_valid
    """,
    """
    ALTER TABLE app.result_sets ADD CONSTRAINT ck_result_sets_state_valid CHECK (state IN
    ('pending', 'generating', 'validated', 'available', 'failed', 'superseded', 'invalidated',
    'expired'))
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN engine_version VARCHAR(128)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN environment_version VARCHAR(128)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN container_image_digest VARCHAR(255)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN node_identity VARCHAR(255)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN resource_identities JSONB
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN parameters_digest VARCHAR(128)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN superseded_by_result_set_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN invalidation_reason TEXT
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN failure_code VARCHAR(128)
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN failure_message TEXT
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN available_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN scientific_execution_id VARCHAR(64) REFERENCES
    app.scientific_executions(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN analysis_configuration_id VARCHAR(64) REFERENCES
    app.analysis_configurations(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN engine_resource_id VARCHAR(64) REFERENCES
    app.scientific_resources(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN reference_genome_resource_id VARCHAR(64) REFERENCES
    app.scientific_resources(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN completeness VARCHAR(64) NOT NULL DEFAULT 'unknown'
    """,
    """
    ALTER TABLE app.result_sets ADD CONSTRAINT ck_result_sets_completeness_valid CHECK
    (completeness IN ('complete', 'partial', 'empty', 'unknown'))
    """,
    """
    ALTER TABLE app.result_sets ADD COLUMN origin VARCHAR(64) NOT NULL DEFAULT 'generated'
    """,
    """
    ALTER TABLE app.result_sets ADD CONSTRAINT ck_result_sets_origin_valid CHECK (origin IN
    ('imported', 'retrieved', 'generated', 'machine_generated', 'human_entered',
    'human_evaluated'))
    """,
    """
    CREATE INDEX ix_result_sets_project_id ON app.result_sets (project_id)
    """,
    """
    CREATE TABLE app.dataset_version_variants ( id VARCHAR(64) NOT NULL, dataset_version_id
    VARCHAR(64) NOT NULL, variant_id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
    source_representation_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_dataset_version_variants PRIMARY KEY (id), CONSTRAINT
    fk_dataset_version_variants_source_representation_id FOREIGN KEY(source_representation_id)
    REFERENCES app.variant_source_representations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_dataset_version_variants_variant_id FOREIGN KEY(variant_id) REFERENCES app.variants (id)
    ON DELETE RESTRICT, CONSTRAINT uq_dataset_version_variants_dataset_version_id_variant_id
    UNIQUE (dataset_version_id, variant_id), CONSTRAINT fk_dataset_version_variants_workspace_id
    FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    fk_dataset_version_variants_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_dataset_version_variants_dataset_version_id ON app.dataset_version_variants
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_dataset_version_variants_source_representation_id ON
    app.dataset_version_variants (source_representation_id)
    """,
    """
    CREATE INDEX ix_dataset_version_variants_variant_id ON app.dataset_version_variants
    (variant_id)
    """,
    """
    CREATE INDEX ix_dataset_version_variants_workspace_id ON app.dataset_version_variants
    (workspace_id)
    """,
    """
    CREATE TABLE app.result_artifacts ( id VARCHAR(64) NOT NULL, result_set_id VARCHAR(64) NOT
    NULL, artifact_key VARCHAR(255) NOT NULL, kind VARCHAR(64) NOT NULL, artifact_format
    VARCHAR(64) NOT NULL, state VARCHAR(64) DEFAULT 'registered' NOT NULL, storage_uri TEXT,
    file_artifact_id VARCHAR(64), analytical_location TEXT, scientific_artifact_id VARCHAR(64),
    media_type VARCHAR(255), size_bytes BIGINT, checksum_algorithm VARCHAR(64), checksum_value
    VARCHAR(256), row_count BIGINT, column_schema JSONB, failure_code VARCHAR(128),
    failure_message TEXT, metadata_json JSONB, verified_at TIMESTAMP WITH TIME ZONE, created_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_result_artifacts PRIMARY
    KEY (id), CONSTRAINT ck_result_artifacts_checksum_algorithm_valid CHECK (checksum_algorithm
    IN ('sha256', 'sha512', 'md5', 'crc32c')), CONSTRAINT
    uq_result_artifacts_result_set_id_artifact_key UNIQUE (result_set_id, artifact_key),
    CONSTRAINT ck_result_artifacts_state_valid CHECK (state IN ('registered', 'verifying',
    'accepted', 'rejected', 'superseded', 'missing')), CONSTRAINT
    fk_result_artifacts_file_artifact_id FOREIGN KEY(file_artifact_id) REFERENCES
    app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT
    ck_result_artifacts_artifact_format_valid CHECK (artifact_format IN ('parquet', 'json',
    'jsonl', 'csv', 'tsv', 'vcf', 'binary', 'other')), CONSTRAINT ck_result_artifacts_kind_valid
    CHECK (kind IN ('variant_table', 'annotation_table', 'frequency_table', 'summary',
    'manifest', 'log', 'other')), CONSTRAINT fk_result_artifacts_scientific_artifact_id FOREIGN
    KEY(scientific_artifact_id) REFERENCES app.scientific_artifacts (id) ON DELETE RESTRICT,
    CONSTRAINT fk_result_artifacts_result_set_id FOREIGN KEY(result_set_id) REFERENCES
    app.result_sets (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_result_artifacts_file_artifact_id ON app.result_artifacts (file_artifact_id)
    """,
    """
    CREATE INDEX ix_result_artifacts_result_set_id ON app.result_artifacts (result_set_id)
    """,
    """
    CREATE INDEX ix_result_artifacts_scientific_artifact_id ON app.result_artifacts
    (scientific_artifact_id)
    """,
    """
    CREATE INDEX ix_result_artifacts_state ON app.result_artifacts (state)
    """,
    """
    CREATE TABLE app.result_ingestion_requests ( id VARCHAR(64) NOT NULL, workspace_id
    VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT NULL, analysis_execution_id VARCHAR(64) NOT
    NULL, scientific_execution_id VARCHAR(64), result_set_id VARCHAR(64), result_key
    VARCHAR(128) NOT NULL, idempotency_key VARCHAR(255) NOT NULL, payload_digest VARCHAR(128)
    NOT NULL, state VARCHAR(64) DEFAULT 'received' NOT NULL, declared_completeness VARCHAR(64)
    DEFAULT 'unknown' NOT NULL, declared_row_count BIGINT, artifact_count INTEGER DEFAULT '0'
    NOT NULL, engine_resource_id VARCHAR(64), engine_version VARCHAR(128), submitted_by
    VARCHAR(64), service_account_id VARCHAR(64), job_id VARCHAR(64), correlation_id VARCHAR(64),
    is_development_payload BOOLEAN DEFAULT 'false' NOT NULL, findings JSONB, rejection_code
    VARCHAR(128), rejection_message TEXT, failure_code VARCHAR(128), failure_message TEXT,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL, completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_result_ingestion_requests PRIMARY KEY (id), CONSTRAINT
    ck_result_ingestion_requests_state_valid CHECK (state IN ('received', 'validating',
    'validated', 'materializing', 'accepted', 'rejected', 'failed')), CONSTRAINT
    fk_result_ingestion_requests_service_account_id FOREIGN KEY(service_account_id) REFERENCES
    app.service_accounts (id) ON DELETE RESTRICT, CONSTRAINT
    fk_result_ingestion_requests_result_set_id FOREIGN KEY(result_set_id) REFERENCES
    app.result_sets (id) ON DELETE RESTRICT, CONSTRAINT
    ck_result_ingestion_requests_declared_completeness_valid CHECK (declared_completeness IN
    ('complete', 'partial', 'empty', 'unknown')), CONSTRAINT
    fk_result_ingestion_requests_analysis_execution_id FOREIGN KEY(analysis_execution_id)
    REFERENCES app.analysis_executions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_result_ingestion_requests_workspace_id FOREIGN KEY(workspace_id) REFERENCES
    app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    fk_result_ingestion_requests_engine_resource_id FOREIGN KEY(engine_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_result_ingestion_requests_scientific_execution_id FOREIGN KEY(scientific_execution_id)
    REFERENCES app.scientific_executions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_result_ingestion_requests_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id)
    ON DELETE RESTRICT, CONSTRAINT uq_result_ingestion_requests_idempotency_key UNIQUE
    (idempotency_key) )
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_analysis_execution_id ON
    app.result_ingestion_requests (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_correlation_id ON app.result_ingestion_requests
    (correlation_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_engine_resource_id ON
    app.result_ingestion_requests (engine_resource_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_project_id ON app.result_ingestion_requests
    (project_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_result_set_id ON app.result_ingestion_requests
    (result_set_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_scientific_execution_id ON
    app.result_ingestion_requests (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_service_account_id ON
    app.result_ingestion_requests (service_account_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_workspace_id ON app.result_ingestion_requests
    (workspace_id)
    """,
    """
    CREATE INDEX ix_result_ingestion_requests_workspace_id_state ON
    app.result_ingestion_requests (workspace_id, state)
    """,
    """
    CREATE TABLE app.variant_representations ( id VARCHAR(64) NOT NULL, variant_id VARCHAR(64),
    source_representation_id VARCHAR(64), reference_genome_resource_id VARCHAR(64) NOT NULL,
    contig VARCHAR(64) NOT NULL, source_contig VARCHAR(64), position BIGINT, end_position
    BIGINT, reference_allele TEXT, alternate_allele TEXT, normalization_state VARCHAR(64) NOT
    NULL, normalization_version VARCHAR(128) NOT NULL, normalization_engine_resource_id
    VARCHAR(64), scientific_execution_id VARCHAR(64), origin VARCHAR(64) DEFAULT 'generated' NOT
    NULL, failure_code VARCHAR(128), failure_message TEXT, details JSONB, recorded_at TIMESTAMP
    WITH TIME ZONE NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_variant_representations PRIMARY KEY (id), CONSTRAINT
    fk_variant_representations_normalization_engine_resource_id FOREIGN
    KEY(normalization_engine_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_variant_representations_source_representation_id FOREIGN
    KEY(source_representation_id) REFERENCES app.variant_source_representations (id) ON DELETE
    RESTRICT, CONSTRAINT ck_variant_representations_normalization_state_valid CHECK
    (normalization_state IN ('not_normalized', 'normalized', 'normalization_failed',
    'normalization_unavailable')), CONSTRAINT fk_variant_representations_scientific_execution_id
    FOREIGN KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE
    RESTRICT, CONSTRAINT ck_variant_representations_origin_valid CHECK (origin IN ('imported',
    'retrieved', 'generated', 'machine_generated', 'human_entered', 'human_evaluated')),
    CONSTRAINT fk_variant_representations_reference_genome_resource_id FOREIGN
    KEY(reference_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_variant_representations_variant_id FOREIGN KEY(variant_id)
    REFERENCES app.variants (id) ON DELETE RESTRICT, CONSTRAINT
    uq_variant_representations_source_representation_id_version UNIQUE
    (source_representation_id, normalization_version) )
    """,
    """
    CREATE INDEX ix_variant_representations_normalization_engine_resource_id ON
    app.variant_representations (normalization_engine_resource_id)
    """,
    """
    CREATE INDEX ix_variant_representations_reference_genome_resource_id ON
    app.variant_representations (reference_genome_resource_id)
    """,
    """
    CREATE INDEX ix_variant_representations_scientific_execution_id ON
    app.variant_representations (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_variant_representations_source_representation_id ON
    app.variant_representations (source_representation_id)
    """,
    """
    CREATE INDEX ix_variant_representations_variant_id ON app.variant_representations
    (variant_id)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP TABLE app.variant_representations
    """,
    """
    DROP TABLE app.result_ingestion_requests
    """,
    """
    DROP TABLE app.result_artifacts
    """,
    """
    DROP TABLE app.dataset_version_variants
    """,
    """
    DROP INDEX app.ix_result_sets_project_id
    """,
    """
    ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_origin_valid
    """,
    """
    ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_completeness_valid
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN reference_genome_resource_id
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN engine_resource_id
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN analysis_configuration_id
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN scientific_execution_id
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN available_at
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN failure_message
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN failure_code
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN invalidation_reason
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN superseded_by_result_set_id
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN parameters_digest
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN resource_identities
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN node_identity
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN container_image_digest
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN environment_version
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN engine_version
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN completeness
    """,
    """
    ALTER TABLE app.result_sets DROP COLUMN origin
    """,
    """
    ALTER TABLE app.result_sets DROP CONSTRAINT ck_result_sets_state_valid
    """,
    """
    ALTER TABLE app.result_sets ADD CONSTRAINT ck_result_sets_state_valid CHECK (state IN
    ('pending', 'generating', 'available', 'invalidated', 'expired'))
    """,
    """
    ALTER TABLE app.clinical_assertions DROP COLUMN scientific_execution_id
    """,
    """
    ALTER TABLE app.clinical_assertions DROP CONSTRAINT
    ck_clinical_assertions_value_semantics_valid
    """,
    """
    ALTER TABLE app.clinical_assertions DROP COLUMN value_semantics
    """,
    """
    ALTER TABLE app.clinical_assertions DROP COLUMN last_evaluated_at
    """,
    """
    ALTER TABLE app.clinical_assertions DROP COLUMN asserted_at
    """,
    """
    ALTER TABLE app.clinical_assertions DROP COLUMN assertion_method
    """,
    """
    ALTER TABLE app.clinical_assertions DROP COLUMN condition_namespace
    """,
    """
    ALTER TABLE app.population_frequency_observations DROP COLUMN scientific_execution_id
    """,
    """
    ALTER TABLE app.population_frequency_observations DROP COLUMN subset_key
    """,
    """
    ALTER TABLE app.variants DROP COLUMN scientific_execution_id
    """,
    """
    ALTER TABLE app.variants DROP CONSTRAINT ck_variants_origin_valid
    """,
    """
    ALTER TABLE app.variants DROP COLUMN origin
    """,
    """
    ALTER TABLE app.variants DROP CONSTRAINT ck_variants_normalization_state_valid
    """,
    """
    ALTER TABLE app.variants ADD CONSTRAINT ck_variants_normalization_state_valid CHECK
    (normalization_state IN ('not_normalized', 'normalized', 'normalization_failed'))
    """,
    """
    ALTER TABLE app.variant_source_representations DROP CONSTRAINT
    ck_variant_source_representations_normalization_state_valid
    """,
    """
    ALTER TABLE app.variant_source_representations ADD CONSTRAINT
    ck_variant_source_representations_normalization_state_valid CHECK (normalization_state IN
    ('not_normalized', 'normalized', 'normalization_failed'))
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
