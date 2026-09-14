"""Annotation resource fields, annotation profiles, runs, results and findings.

Additive revision on top of Packages 2-7.

Deliberately *not* created here:

* an annotation resource table — a registered annotation resource version is a
  row in the existing ``app.scientific_resources`` registry (kind
  ``annotation_resource``), so it inherits the platform's resource lifecycle;
* an annotation value table — annotation values are ``app.variant_annotations``
  rows from Package 6, and a second annotation-row model would split the data.

New tables:

* ``app.annotation_resource_fields`` — the fields a resource version declares it
  produces. This is the schema ingestion validates against and the source of the
  filterable annotation fields Package 7 consumes, which is why a new annotation
  field is a row and never a migration.
* ``app.annotation_profiles`` / ``app.annotation_profile_versions`` — immutable
  configuration: pinned resource versions, reference context, capability,
  parameters and configuration digest.
* ``app.annotation_runs`` — the application's workflow record for one run, with
  the configuration frozen at request time and the identities the compute
  subsystem reported.
* ``app.annotation_result_versions`` — the versioned annotation result. Unique per
  (run, resource key, version number), so an updated resource version adds a
  version and nothing is overwritten; a superseded version stays readable.
* ``app.annotation_validation_findings`` — recorded validation observations, so a
  rejected record stays explainable after the request is gone.

The ``platform.jobs.kind`` and ``platform.scheduled_jobs.job_kind`` check
constraints are re-issued against the extended ``JobKind`` vocabulary, which now
includes the two annotation job kinds. Existing rows are unaffected: the value set
only grows.

Revision ID: 0008_annotation_resources
Revises: 0007_filtering_ranking

This revision is **self-contained**: every statement is literal SQL frozen at
this point in the schema history. It deliberately does not import the current
SQLAlchemy models, ``Base.metadata`` or the domain vocabularies — a migration
must describe the schema as it was, so evolving the ORM can never rewrite
history.
"""

from __future__ import annotations

from alembic import op

revision = "0008_annotation_resources"
down_revision = "0007_filtering_ranking"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.annotation_resource_fields",
    "app.annotation_profiles",
    "app.annotation_profile_versions",
    "app.annotation_runs",
    "app.annotation_result_versions",
    "app.annotation_validation_findings",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app.annotation_profiles ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL,
    description TEXT, state VARCHAR(64) DEFAULT 'draft' NOT NULL, latest_version_number INTEGER
    DEFAULT '0' NOT NULL, is_referenced BOOLEAN DEFAULT 'false' NOT NULL, metadata_json JSONB,
    created_by VARCHAR(64), updated_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER
    DEFAULT '1' NOT NULL, CONSTRAINT pk_annotation_profiles PRIMARY KEY (id), CONSTRAINT
    fk_annotation_profiles_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT uq_annotation_profiles_name UNIQUE (name), CONSTRAINT
    fk_annotation_profiles_updated_by FOREIGN KEY(updated_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT ck_annotation_profiles_state_valid CHECK (state IN ('draft',
    'published', 'archived')) )
    """,
    """
    CREATE INDEX ix_annotation_profiles_created_by ON app.annotation_profiles (created_by)
    """,
    """
    CREATE INDEX ix_annotation_profiles_updated_by ON app.annotation_profiles (updated_by)
    """,
    """
    CREATE TABLE app.annotation_profile_versions ( id VARCHAR(64) NOT NULL, profile_id
    VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, capability_id VARCHAR(128) NOT NULL,
    capability_version VARCHAR(128), engine_resource_id VARCHAR(64), engine_version
    VARCHAR(128), genome_assembly VARCHAR(64), reference_genome_resource_id VARCHAR(64),
    resources JSONB, required_inputs JSONB, output_field_keys JSONB, parameters JSONB,
    provenance_requirements JSONB, configuration_digest VARCHAR(128) NOT NULL, schema_version
    VARCHAR(128), change_note TEXT, is_referenced BOOLEAN DEFAULT 'false' NOT NULL,
    metadata_json JSONB, created_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_annotation_profile_versions PRIMARY KEY (id), CONSTRAINT
    fk_annotation_profile_versions_reference_genome_resource_id FOREIGN
    KEY(reference_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_annotation_profile_versions_profile_id FOREIGN KEY(profile_id)
    REFERENCES app.annotation_profiles (id) ON DELETE CASCADE, CONSTRAINT
    fk_annotation_profile_versions_created_by FOREIGN KEY(created_by) REFERENCES app.users (id)
    ON DELETE RESTRICT, CONSTRAINT fk_annotation_profile_versions_engine_resource_id FOREIGN
    KEY(engine_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT uq_annotation_profile_versions_profile_id_version_number UNIQUE (profile_id,
    version_number) )
    """,
    """
    CREATE INDEX ix_annotation_profile_versions_created_by ON app.annotation_profile_versions
    (created_by)
    """,
    """
    CREATE INDEX ix_annotation_profile_versions_engine_resource_id ON
    app.annotation_profile_versions (engine_resource_id)
    """,
    """
    CREATE INDEX ix_annotation_profile_versions_profile_id ON app.annotation_profile_versions
    (profile_id)
    """,
    """
    CREATE INDEX ix_annotation_profile_versions_reference_genome_resource_id ON
    app.annotation_profile_versions (reference_genome_resource_id)
    """,
    """
    CREATE TABLE app.annotation_resource_fields ( id VARCHAR(64) NOT NULL,
    scientific_resource_id VARCHAR(64) NOT NULL, field_key VARCHAR(255) NOT NULL, label
    VARCHAR(255) NOT NULL, value_type VARCHAR(64) NOT NULL, description TEXT, column_name
    VARCHAR(255), unit VARCHAR(64), scientific_category VARCHAR(128), missing_semantics JSONB,
    allowed_values JSONB, high_cardinality BOOLEAN DEFAULT 'false' NOT NULL, filterable BOOLEAN
    DEFAULT 'true' NOT NULL, sortable BOOLEAN DEFAULT 'true' NOT NULL, metadata_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_annotation_resource_fields PRIMARY KEY (id),
    CONSTRAINT fk_annotation_resource_fields_scientific_resource_id FOREIGN
    KEY(scientific_resource_id) REFERENCES app.scientific_resources (id) ON DELETE CASCADE,
    CONSTRAINT ck_annotation_resource_fields_value_type_valid CHECK (value_type IN ('string',
    'integer', 'number', 'boolean', 'date', 'json')), CONSTRAINT
    uq_annotation_resource_fields_resource_field_key UNIQUE (scientific_resource_id, field_key)
    )
    """,
    """
    CREATE INDEX ix_annotation_resource_fields_field_key ON app.annotation_resource_fields
    (field_key)
    """,
    """
    CREATE INDEX ix_annotation_resource_fields_scientific_resource_id ON
    app.annotation_resource_fields (scientific_resource_id)
    """,
    """
    CREATE TABLE app.annotation_runs ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, project_id VARCHAR(64), profile_id VARCHAR(64) NOT NULL, profile_version_id
    VARCHAR(64) NOT NULL, profile_version_number INTEGER NOT NULL, result_set_id VARCHAR(64),
    dataset_version_id VARCHAR(64), state VARCHAR(64) DEFAULT 'requested' NOT NULL, requested_by
    VARCHAR(64), requested_at TIMESTAMP WITH TIME ZONE, submitted_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE, job_id VARCHAR(64), scientific_execution_id
    VARCHAR(64), external_execution_id VARCHAR(255), capability_id VARCHAR(128),
    capability_version VARCHAR(128), engine_resource_id VARCHAR(64), engine_version
    VARCHAR(128), environment_version VARCHAR(128), container_image_digest VARCHAR(255),
    node_identity VARCHAR(255), genome_assembly VARCHAR(64), configuration_snapshot JSONB,
    configuration_digest VARCHAR(128), correlation_id VARCHAR(64), idempotency_key VARCHAR(255),
    failure_code VARCHAR(128), failure_message TEXT, record_count BIGINT, metadata_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_annotation_runs PRIMARY KEY (id), CONSTRAINT fk_annotation_runs_scientific_execution_id
    FOREIGN KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE
    RESTRICT, CONSTRAINT fk_annotation_runs_dataset_version_id FOREIGN KEY(dataset_version_id)
    REFERENCES app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_runs_profile_version_id FOREIGN KEY(profile_version_id) REFERENCES
    app.annotation_profile_versions (id) ON DELETE RESTRICT, CONSTRAINT
    ck_annotation_runs_state_valid CHECK (state IN ('requested', 'submitted', 'running',
    'ingesting', 'completed', 'failed', 'cancelled', 'rejected')), CONSTRAINT
    fk_annotation_runs_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON DELETE
    RESTRICT, CONSTRAINT uq_annotation_runs_workspace_id_idempotency_key UNIQUE (workspace_id,
    idempotency_key), CONSTRAINT fk_annotation_runs_engine_resource_id FOREIGN
    KEY(engine_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT fk_annotation_runs_requested_by FOREIGN KEY(requested_by) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT fk_annotation_runs_result_set_id FOREIGN
    KEY(result_set_id) REFERENCES app.result_sets (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_runs_profile_id FOREIGN KEY(profile_id) REFERENCES app.annotation_profiles
    (id) ON DELETE RESTRICT, CONSTRAINT fk_annotation_runs_workspace_id FOREIGN
    KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_annotation_runs_correlation_id ON app.annotation_runs (correlation_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_dataset_version_id ON app.annotation_runs
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_engine_resource_id ON app.annotation_runs
    (engine_resource_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_profile_id ON app.annotation_runs (profile_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_profile_version_id ON app.annotation_runs
    (profile_version_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_project_id ON app.annotation_runs (project_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_requested_by ON app.annotation_runs (requested_by)
    """,
    """
    CREATE INDEX ix_annotation_runs_result_set_id ON app.annotation_runs (result_set_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_scientific_execution_id ON app.annotation_runs
    (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_workspace_id ON app.annotation_runs (workspace_id)
    """,
    """
    CREATE INDEX ix_annotation_runs_workspace_id_state ON app.annotation_runs (workspace_id,
    state)
    """,
    """
    CREATE TABLE app.annotation_result_versions ( id VARCHAR(64) NOT NULL, annotation_run_id
    VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL, project_id VARCHAR(64), resource_id
    VARCHAR(64) NOT NULL, resource_key VARCHAR(255) NOT NULL, resource_version VARCHAR(128) NOT
    NULL, version_number INTEGER NOT NULL, state VARCHAR(64) DEFAULT 'registered' NOT NULL,
    result_set_id VARCHAR(64), dataset_version_id VARCHAR(64), profile_version_id VARCHAR(64),
    scientific_execution_id VARCHAR(64), engine_resource_id VARCHAR(64), engine_version
    VARCHAR(128), environment_version VARCHAR(128), container_image_digest VARCHAR(255),
    node_identity VARCHAR(255), genome_assembly VARCHAR(64), analytical_location TEXT,
    storage_uri TEXT, checksum_algorithm VARCHAR(64), checksum_value VARCHAR(256), row_count
    BIGINT, stored_record_count BIGINT DEFAULT '0' NOT NULL, declared_record_count BIGINT,
    rejected_record_count BIGINT DEFAULT '0' NOT NULL, field_keys JSONB, contract_version
    VARCHAR(32), payload_digest VARCHAR(128), parameters_digest VARCHAR(128), completeness
    VARCHAR(64), is_development_payload BOOLEAN DEFAULT 'false' NOT NULL, supersedes_id
    VARCHAR(64), superseded_by_id VARCHAR(64), provenance JSONB, metadata_json JSONB,
    ingested_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT
    '1' NOT NULL, CONSTRAINT pk_annotation_result_versions PRIMARY KEY (id), CONSTRAINT
    fk_annotation_result_versions_engine_resource_id FOREIGN KEY(engine_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    uq_annotation_result_versions_run_resource_version UNIQUE (annotation_run_id, resource_key,
    version_number), CONSTRAINT fk_annotation_result_versions_profile_version_id FOREIGN
    KEY(profile_version_id) REFERENCES app.annotation_profile_versions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_annotation_result_versions_result_set_id FOREIGN KEY(result_set_id) REFERENCES
    app.result_sets (id) ON DELETE RESTRICT, CONSTRAINT fk_annotation_result_versions_project_id
    FOREIGN KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_result_versions_annotation_run_id FOREIGN KEY(annotation_run_id) REFERENCES
    app.annotation_runs (id) ON DELETE RESTRICT, CONSTRAINT
    uq_annotation_result_versions_run_payload_digest UNIQUE (annotation_run_id, payload_digest),
    CONSTRAINT ck_annotation_result_versions_state_valid CHECK (state IN ('registered',
    'validated', 'available', 'rejected', 'superseded')), CONSTRAINT
    fk_annotation_result_versions_supersedes_id FOREIGN KEY(supersedes_id) REFERENCES
    app.annotation_result_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_result_versions_scientific_execution_id FOREIGN KEY(scientific_execution_id)
    REFERENCES app.scientific_executions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_result_versions_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_result_versions_resource_id FOREIGN KEY(resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_annotation_result_versions_workspace_id FOREIGN KEY(workspace_id) REFERENCES
    app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    ck_annotation_result_versions_checksum_algorithm_valid CHECK (checksum_algorithm IN
    ('sha256', 'sha512', 'md5', 'crc32c')), CONSTRAINT
    fk_annotation_result_versions_superseded_by_id FOREIGN KEY(superseded_by_id) REFERENCES
    app.annotation_result_versions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_annotation_result_versions_annotation_run_id ON
    app.annotation_result_versions (annotation_run_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_dataset_version_id ON
    app.annotation_result_versions (dataset_version_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_engine_resource_id ON
    app.annotation_result_versions (engine_resource_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_profile_version_id ON
    app.annotation_result_versions (profile_version_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_project_id ON app.annotation_result_versions
    (project_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_resource_id ON app.annotation_result_versions
    (resource_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_result_set_id ON app.annotation_result_versions
    (result_set_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_result_set_id_resource_key ON
    app.annotation_result_versions (result_set_id, resource_key)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_scientific_execution_id ON
    app.annotation_result_versions (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_superseded_by_id ON
    app.annotation_result_versions (superseded_by_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_supersedes_id ON app.annotation_result_versions
    (supersedes_id)
    """,
    """
    CREATE INDEX ix_annotation_result_versions_workspace_id ON app.annotation_result_versions
    (workspace_id)
    """,
    """
    CREATE TABLE app.annotation_validation_findings ( id VARCHAR(64) NOT NULL, annotation_run_id
    VARCHAR(64) NOT NULL, annotation_result_version_id VARCHAR(64), code VARCHAR(128) NOT NULL,
    message TEXT NOT NULL, severity VARCHAR(64) DEFAULT 'error' NOT NULL, field_key
    VARCHAR(255), variant_id VARCHAR(64), record_index INTEGER, detail JSONB, created_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, CONSTRAINT pk_annotation_validation_findings PRIMARY KEY (id), CONSTRAINT
    ck_annotation_validation_findings_severity_valid CHECK (severity IN ('info', 'warning',
    'error', 'blocking')), CONSTRAINT
    fk_annotation_validation_findings_annotation_result_version_id FOREIGN
    KEY(annotation_result_version_id) REFERENCES app.annotation_result_versions (id) ON DELETE
    RESTRICT, CONSTRAINT fk_annotation_validation_findings_annotation_run_id FOREIGN
    KEY(annotation_run_id) REFERENCES app.annotation_runs (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_annotation_validation_findings_annotation_result_version_id ON
    app.annotation_validation_findings (annotation_result_version_id)
    """,
    """
    CREATE INDEX ix_annotation_validation_findings_annotation_run_id ON
    app.annotation_validation_findings (annotation_run_id)
    """,
    """
    CREATE INDEX ix_annotation_validation_findings_code ON app.annotation_validation_findings
    (code)
    """,
    """
    CREATE INDEX ix_annotation_validation_findings_run_id ON app.annotation_validation_findings
    (annotation_run_id)
    """,
    """
    ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_kind_valid
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_kind_valid CHECK (kind IN
    ('analysis_execution', 'dataset_import', 'dataset_validation', 'scientific_execution',
    'export', 'report_generation', 'notification_delivery', 'retention', 'maintenance',
    'schedule_trigger', 'stale_recovery', 'result_ingestion', 'variant_query',
    'annotation_execution', 'annotation_ingestion', 'classification_evaluation',
    'classification_ingestion'))
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP CONSTRAINT ck_scheduled_jobs_job_kind_valid
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD CONSTRAINT ck_scheduled_jobs_job_kind_valid CHECK
    (job_kind IN ('analysis_execution', 'dataset_import', 'dataset_validation',
    'scientific_execution', 'export', 'report_generation', 'notification_delivery', 'retention',
    'maintenance', 'schedule_trigger', 'stale_recovery', 'result_ingestion', 'variant_query',
    'annotation_execution', 'annotation_ingestion', 'classification_evaluation',
    'classification_ingestion'))
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP TABLE app.annotation_validation_findings
    """,
    """
    DROP TABLE app.annotation_result_versions
    """,
    """
    DROP TABLE app.annotation_runs
    """,
    """
    DROP TABLE app.annotation_resource_fields
    """,
    """
    DROP TABLE app.annotation_profile_versions
    """,
    """
    DROP TABLE app.annotation_profiles
    """,
    """
    ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_kind_valid
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_kind_valid CHECK (kind IN
    ('analysis_execution', 'dataset_import', 'dataset_validation', 'scientific_execution',
    'export', 'report_generation', 'notification_delivery', 'retention', 'maintenance',
    'schedule_trigger', 'stale_recovery', 'result_ingestion', 'variant_query',
    'annotation_execution', 'annotation_ingestion', 'classification_evaluation',
    'classification_ingestion'))
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP CONSTRAINT ck_scheduled_jobs_job_kind_valid
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD CONSTRAINT ck_scheduled_jobs_job_kind_valid CHECK
    (job_kind IN ('analysis_execution', 'dataset_import', 'dataset_validation',
    'scientific_execution', 'export', 'report_generation', 'notification_delivery', 'retention',
    'maintenance', 'schedule_trigger', 'stale_recovery', 'result_ingestion', 'variant_query',
    'annotation_execution', 'annotation_ingestion', 'classification_evaluation',
    'classification_ingestion'))
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
