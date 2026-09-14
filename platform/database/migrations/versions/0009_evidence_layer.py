"""Evidence ingestion batches, validation findings, and the widened evidence row.

Additive revision on top of Packages 2-8.

Deliberately *not* created here:

* an evidence source table — a registered evidence source version is a row in the
  existing ``app.scientific_resources`` registry (kind ``evidence_resource``), so
  it inherits the platform's resource lifecycle and governance;
* a second evidence record table — evidence records stay ``app.evidence_items``,
  the table Package 2 established. This revision widens it instead of forking the
  evidence model in two.

New tables:

* ``app.evidence_ingestion_batches`` — one validated delivery of evidence,
  unique on ``(source_key, payload_digest)``, which is what makes redelivery
  idempotent rather than duplicating evidence.
* ``app.evidence_validation_findings`` — why individual claims were refused,
  downgraded or flagged, kept so a refusal stays explainable.

``app.evidence_items`` gains source identity (key, version, the source's own
identifier and release time), retrieval time as a fact separate from release time,
gene/condition context, stated applicability, a lifecycle state, method, and the
versioning columns that let a newer delivery from the same source supersede an
older one without rewriting it.

Revision ID: 0009_evidence_layer
Revises: 0008_annotation_resources

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

This revision is **self-contained**: every statement is literal SQL frozen at
this point in the schema history. It deliberately does not import the current
SQLAlchemy models, ``Base.metadata`` or the domain vocabularies — a migration
must describe the schema as it was, so evolving the ORM can never rewrite
history.
"""

from __future__ import annotations

from alembic import op

revision = "0009_evidence_layer"
down_revision = "0008_annotation_resources"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.evidence_ingestion_batches",
    "app.evidence_validation_findings",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app.evidence_ingestion_batches ( id VARCHAR(64) NOT NULL, source_key
    VARCHAR(255) NOT NULL, source_version VARCHAR(128) NOT NULL, source_resource_id VARCHAR(64),
    payload_digest VARCHAR(128) NOT NULL, state VARCHAR(64) DEFAULT 'requested' NOT NULL, origin
    VARCHAR(64) DEFAULT 'retrieved' NOT NULL, workspace_id VARCHAR(64), project_id VARCHAR(64),
    file_artifact_id VARCHAR(64), claimed_record_count INTEGER DEFAULT '0' NOT NULL,
    stored_record_count INTEGER DEFAULT '0' NOT NULL, superseded_record_count INTEGER DEFAULT
    '0' NOT NULL, duplicate_record_count INTEGER DEFAULT '0' NOT NULL, rejected_record_count
    INTEGER DEFAULT '0' NOT NULL, size_bytes BIGINT, retrieved_at TIMESTAMP WITH TIME ZONE,
    source_released_at TIMESTAMP WITH TIME ZONE, requested_by VARCHAR(64), service_account_id
    VARCHAR(64), job_id VARCHAR(64), correlation_id VARCHAR(128), provenance JSONB, failure_code
    VARCHAR(128), failure_message TEXT, completed_at TIMESTAMP WITH TIME ZONE, created_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_evidence_ingestion_batches PRIMARY KEY (id), CONSTRAINT
    ck_evidence_ingestion_batches_origin_valid CHECK (origin IN ('imported', 'retrieved',
    'generated', 'machine_generated', 'human_entered', 'human_evaluated')), CONSTRAINT
    fk_evidence_ingestion_batches_service_account_id FOREIGN KEY(service_account_id) REFERENCES
    app.service_accounts (id) ON DELETE RESTRICT, CONSTRAINT
    fk_evidence_ingestion_batches_file_artifact_id FOREIGN KEY(file_artifact_id) REFERENCES
    app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT
    fk_evidence_ingestion_batches_workspace_id FOREIGN KEY(workspace_id) REFERENCES
    app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    uq_evidence_ingestion_batches_source_key_payload_digest UNIQUE (source_key, payload_digest),
    CONSTRAINT ck_evidence_ingestion_batches_state_valid CHECK (state IN ('requested',
    'validating', 'accepted', 'partially_accepted', 'rejected', 'failed')), CONSTRAINT
    fk_evidence_ingestion_batches_requested_by FOREIGN KEY(requested_by) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT fk_evidence_ingestion_batches_project_id FOREIGN
    KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    fk_evidence_ingestion_batches_source_resource_id FOREIGN KEY(source_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_file_artifact_id ON
    app.evidence_ingestion_batches (file_artifact_id)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_project_id ON app.evidence_ingestion_batches
    (project_id)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_requested_by ON app.evidence_ingestion_batches
    (requested_by)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_service_account_id ON
    app.evidence_ingestion_batches (service_account_id)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_source_key_version ON
    app.evidence_ingestion_batches (source_key, source_version)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_source_resource_id ON
    app.evidence_ingestion_batches (source_resource_id)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_workspace_id ON app.evidence_ingestion_batches
    (workspace_id)
    """,
    """
    CREATE INDEX ix_evidence_ingestion_batches_workspace_id_state ON
    app.evidence_ingestion_batches (workspace_id, state)
    """,
    """
    CREATE TABLE app.evidence_validation_findings ( id VARCHAR(64) NOT NULL, ingestion_batch_id
    VARCHAR(64) NOT NULL, code VARCHAR(128) NOT NULL, message TEXT NOT NULL, severity
    VARCHAR(64) DEFAULT 'error' NOT NULL, evidence_id VARCHAR(64), variant_id VARCHAR(64),
    record_index INTEGER, detail JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_evidence_validation_findings PRIMARY KEY (id), CONSTRAINT
    ck_evidence_validation_findings_severity_valid CHECK (severity IN ('info', 'warning',
    'error', 'blocking')), CONSTRAINT fk_evidence_validation_findings_ingestion_batch_id FOREIGN
    KEY(ingestion_batch_id) REFERENCES app.evidence_ingestion_batches (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_evidence_validation_findings_code ON app.evidence_validation_findings (code)
    """,
    """
    CREATE INDEX ix_evidence_validation_findings_ingestion_batch_id ON
    app.evidence_validation_findings (ingestion_batch_id)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN source_key VARCHAR(255)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN source_version VARCHAR(128)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN source_identifier VARCHAR(255)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN source_released_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN retrieved_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN gene_symbol VARCHAR(128)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN gene_identifier VARCHAR(128)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN transcript_identifier VARCHAR(128)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN condition_identifier VARCHAR(255)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN condition_term TEXT
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN inheritance VARCHAR(128)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN applicability VARCHAR(64) NOT NULL DEFAULT
    'undetermined'
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN state VARCHAR(64) NOT NULL DEFAULT 'recorded'
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN method VARCHAR(255)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN evidence_key VARCHAR(255)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN supersedes_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN superseded_by_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN ingestion_batch_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN payload_digest VARCHAR(128)
    """,
    """
    ALTER TABLE app.evidence_items ADD COLUMN provenance JSONB
    """,
    """
    ALTER TABLE app.evidence_items ADD CONSTRAINT ck_evidence_items_applicability_valid CHECK
    (applicability IN ('applicable', 'context_specific', 'not_applicable', 'undetermined'))
    """,
    """
    ALTER TABLE app.evidence_items ADD CONSTRAINT ck_evidence_items_state_valid CHECK (state IN
    ('recorded', 'available', 'superseded', 'withdrawn', 'rejected'))
    """,
    """
    ALTER TABLE app.evidence_items ADD CONSTRAINT fk_evidence_items_ingestion_batch_id FOREIGN
    KEY (ingestion_batch_id) REFERENCES app.evidence_ingestion_batches (id)
    """,
    """
    CREATE INDEX ix_evidence_items_source_key_source_version ON app.evidence_items (source_key,
    source_version)
    """,
    """
    CREATE INDEX ix_evidence_items_ingestion_batch_id ON app.evidence_items (ingestion_batch_id)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP INDEX app.ix_evidence_items_ingestion_batch_id
    """,
    """
    DROP INDEX app.ix_evidence_items_source_key_source_version
    """,
    """
    ALTER TABLE app.evidence_items DROP CONSTRAINT fk_evidence_items_ingestion_batch_id
    """,
    """
    ALTER TABLE app.evidence_items DROP CONSTRAINT ck_evidence_items_state_valid
    """,
    """
    ALTER TABLE app.evidence_items DROP CONSTRAINT ck_evidence_items_applicability_valid
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN provenance
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN payload_digest
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN ingestion_batch_id
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN superseded_by_id
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN supersedes_id
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN version_number
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN evidence_key
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN method
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN state
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN applicability
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN inheritance
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN condition_term
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN condition_identifier
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN transcript_identifier
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN gene_identifier
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN gene_symbol
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN retrieved_at
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN source_released_at
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN source_identifier
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN source_version
    """,
    """
    ALTER TABLE app.evidence_items DROP COLUMN source_key
    """,
    """
    DROP TABLE app.evidence_validation_findings
    """,
    """
    DROP TABLE app.evidence_ingestion_batches
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
