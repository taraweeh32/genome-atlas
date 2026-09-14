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

This revision is **self-contained**: every statement is literal SQL frozen at
this point in the schema history. It deliberately does not import the current
SQLAlchemy models, ``Base.metadata`` or the domain vocabularies — a migration
must describe the schema as it was, so evolving the ORM can never rewrite
history.
"""

from __future__ import annotations

from alembic import op

revision = "0007_filtering_ranking"
down_revision = "0006_variant_results"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.filter_presets",
    "app.filter_preset_versions",
    "app.ranking_presets",
    "app.ranking_preset_versions",
    "app.filter_executions",
    "app.ranking_executions",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app.filter_presets ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL,
    description TEXT, scope VARCHAR(64) NOT NULL, state VARCHAR(64) DEFAULT 'draft' NOT NULL,
    scope_id VARCHAR(64), owner_user_id VARCHAR(64), workspace_id VARCHAR(64), project_id
    VARCHAR(64), organization_id VARCHAR(64), latest_version_number INTEGER DEFAULT '0' NOT
    NULL, is_referenced BOOLEAN DEFAULT 'false' NOT NULL, applicable_contexts JSONB,
    metadata_json JSONB, created_by VARCHAR(64), updated_by VARCHAR(64), created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT
    NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at
    TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH
    TIME ZONE, CONSTRAINT pk_filter_presets PRIMARY KEY (id), CONSTRAINT
    fk_filter_presets_updated_by FOREIGN KEY(updated_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_filter_presets_organization_id FOREIGN KEY(organization_id)
    REFERENCES app.organizations (id) ON DELETE RESTRICT, CONSTRAINT
    uq_filter_presets_scope_scope_id_name UNIQUE (scope, scope_id, name), CONSTRAINT
    fk_filter_presets_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON
    DELETE RESTRICT, CONSTRAINT ck_filter_presets_scope_valid CHECK (scope IN ('personal',
    'project', 'organization', 'platform')), CONSTRAINT fk_filter_presets_owner_user_id FOREIGN
    KEY(owner_user_id) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_filter_presets_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_filter_presets_project_id FOREIGN KEY(project_id) REFERENCES
    app.projects (id) ON DELETE RESTRICT, CONSTRAINT ck_filter_presets_state_valid CHECK (state
    IN ('draft', 'published', 'archived')), CONSTRAINT ck_filter_presets_deletion_state_valid
    CHECK (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')) )
    """,
    """
    CREATE INDEX ix_filter_presets_created_by ON app.filter_presets (created_by)
    """,
    """
    CREATE INDEX ix_filter_presets_organization_id ON app.filter_presets (organization_id)
    """,
    """
    CREATE INDEX ix_filter_presets_owner_user_id ON app.filter_presets (owner_user_id)
    """,
    """
    CREATE INDEX ix_filter_presets_project_id ON app.filter_presets (project_id)
    """,
    """
    CREATE INDEX ix_filter_presets_scope_state ON app.filter_presets (scope, state)
    """,
    """
    CREATE INDEX ix_filter_presets_updated_by ON app.filter_presets (updated_by)
    """,
    """
    CREATE INDEX ix_filter_presets_workspace_id ON app.filter_presets (workspace_id)
    """,
    """
    CREATE TABLE app.ranking_presets ( method_id VARCHAR(128) NOT NULL, id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL, description TEXT, scope VARCHAR(64) NOT NULL, state VARCHAR(64)
    DEFAULT 'draft' NOT NULL, scope_id VARCHAR(64), owner_user_id VARCHAR(64), workspace_id
    VARCHAR(64), project_id VARCHAR(64), organization_id VARCHAR(64), latest_version_number
    INTEGER DEFAULT '0' NOT NULL, is_referenced BOOLEAN DEFAULT 'false' NOT NULL,
    applicable_contexts JSONB, metadata_json JSONB, created_by VARCHAR(64), updated_by
    VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL,
    deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE,
    deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason
    TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_ranking_presets PRIMARY
    KEY (id), CONSTRAINT fk_ranking_presets_updated_by FOREIGN KEY(updated_by) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_ranking_presets_organization_id FOREIGN
    KEY(organization_id) REFERENCES app.organizations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_presets_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON
    DELETE RESTRICT, CONSTRAINT ck_ranking_presets_state_valid CHECK (state IN ('draft',
    'published', 'archived')), CONSTRAINT fk_ranking_presets_owner_user_id FOREIGN
    KEY(owner_user_id) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_presets_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT ck_ranking_presets_scope_valid CHECK (scope IN ('personal', 'project',
    'organization', 'platform')), CONSTRAINT fk_ranking_presets_project_id FOREIGN
    KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    uq_ranking_presets_scope_scope_id_name UNIQUE (scope, scope_id, name), CONSTRAINT
    ck_ranking_presets_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')) )
    """,
    """
    CREATE INDEX ix_ranking_presets_created_by ON app.ranking_presets (created_by)
    """,
    """
    CREATE INDEX ix_ranking_presets_organization_id ON app.ranking_presets (organization_id)
    """,
    """
    CREATE INDEX ix_ranking_presets_owner_user_id ON app.ranking_presets (owner_user_id)
    """,
    """
    CREATE INDEX ix_ranking_presets_project_id ON app.ranking_presets (project_id)
    """,
    """
    CREATE INDEX ix_ranking_presets_scope_state ON app.ranking_presets (scope, state)
    """,
    """
    CREATE INDEX ix_ranking_presets_updated_by ON app.ranking_presets (updated_by)
    """,
    """
    CREATE INDEX ix_ranking_presets_workspace_id ON app.ranking_presets (workspace_id)
    """,
    """
    CREATE TABLE app.filter_preset_versions ( filter_preset_id VARCHAR(64) NOT NULL,
    condition_count INTEGER DEFAULT '0' NOT NULL, depth INTEGER DEFAULT '1' NOT NULL, id
    VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, canonical JSONB, canonical_hash
    VARCHAR(128) NOT NULL, field_dictionary_version VARCHAR(64) NOT NULL, required_field_ids
    JSONB, change_note TEXT, is_referenced BOOLEAN DEFAULT 'false' NOT NULL, metadata_json
    JSONB, created_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_filter_preset_versions PRIMARY KEY (id), CONSTRAINT fk_filter_preset_versions_created_by
    FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_filter_preset_versions_preset_version UNIQUE (filter_preset_id, version_number),
    CONSTRAINT fk_filter_preset_versions_filter_preset_id FOREIGN KEY(filter_preset_id)
    REFERENCES app.filter_presets (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_filter_preset_versions_created_by ON app.filter_preset_versions (created_by)
    """,
    """
    CREATE INDEX ix_filter_preset_versions_filter_preset_id ON app.filter_preset_versions
    (filter_preset_id)
    """,
    """
    CREATE TABLE app.ranking_preset_versions ( ranking_preset_id VARCHAR(64) NOT NULL, method_id
    VARCHAR(128) NOT NULL, method_version VARCHAR(64) NOT NULL, component_count INTEGER DEFAULT
    '0' NOT NULL, id VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, canonical JSONB,
    canonical_hash VARCHAR(128) NOT NULL, field_dictionary_version VARCHAR(64) NOT NULL,
    required_field_ids JSONB, change_note TEXT, is_referenced BOOLEAN DEFAULT 'false' NOT NULL,
    metadata_json JSONB, created_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_ranking_preset_versions PRIMARY KEY (id), CONSTRAINT
    fk_ranking_preset_versions_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT uq_ranking_preset_versions_preset_version UNIQUE
    (ranking_preset_id, version_number), CONSTRAINT fk_ranking_preset_versions_ranking_preset_id
    FOREIGN KEY(ranking_preset_id) REFERENCES app.ranking_presets (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_ranking_preset_versions_created_by ON app.ranking_preset_versions
    (created_by)
    """,
    """
    CREATE INDEX ix_ranking_preset_versions_ranking_preset_id ON app.ranking_preset_versions
    (ranking_preset_id)
    """,
    """
    CREATE TABLE app.filter_executions ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, project_id VARCHAR(64), executed_by VARCHAR(64) NOT NULL, executed_at TIMESTAMP WITH
    TIME ZONE NOT NULL, result_set_id VARCHAR(64) NOT NULL, dataset_version_id VARCHAR(64),
    analysis_execution_id VARCHAR(64), effective_canonical JSONB, effective_hash VARCHAR(128)
    NOT NULL, field_dictionary_version VARCHAR(64) NOT NULL, outcome VARCHAR(64) NOT NULL,
    filter_definition_id VARCHAR(64), filter_version_id VARCHAR(64), filter_version_number
    INTEGER, filter_preset_id VARCHAR(64), filter_preset_version_id VARCHAR(64),
    filter_preset_version_number INTEGER, custom_canonical JSONB, returned_count INTEGER DEFAULT
    '0' NOT NULL, total_count BIGINT, page_size INTEGER DEFAULT '0' NOT NULL, cursor TEXT,
    next_cursor TEXT, duration_ms INTEGER, step_counts JSONB, software_version VARCHAR(64),
    correlation_id VARCHAR(64), failure_reason TEXT, metadata_json JSONB, created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, CONSTRAINT pk_filter_executions PRIMARY KEY (id), CONSTRAINT
    fk_filter_executions_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT, CONSTRAINT ck_filter_executions_outcome_valid CHECK (outcome IN
    ('completed', 'limit_exceeded', 'timed_out', 'cancelled', 'failed')), CONSTRAINT
    fk_filter_executions_filter_preset_id FOREIGN KEY(filter_preset_id) REFERENCES
    app.filter_presets (id) ON DELETE RESTRICT, CONSTRAINT
    fk_filter_executions_filter_definition_id FOREIGN KEY(filter_definition_id) REFERENCES
    app.filter_definitions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_filter_executions_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT fk_filter_executions_executed_by
    FOREIGN KEY(executed_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_filter_executions_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id)
    ON DELETE RESTRICT, CONSTRAINT fk_filter_executions_filter_preset_version_id FOREIGN
    KEY(filter_preset_version_id) REFERENCES app.filter_preset_versions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_filter_executions_filter_version_id FOREIGN KEY(filter_version_id) REFERENCES
    app.filter_definition_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_filter_executions_analysis_execution_id FOREIGN KEY(analysis_execution_id) REFERENCES
    app.analysis_executions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_filter_executions_result_set_id FOREIGN KEY(result_set_id) REFERENCES app.result_sets
    (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_filter_executions_analysis_execution_id ON app.filter_executions
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_filter_executions_dataset_version_id ON app.filter_executions
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_filter_executions_executed_by ON app.filter_executions (executed_by)
    """,
    """
    CREATE INDEX ix_filter_executions_filter_definition_id ON app.filter_executions
    (filter_definition_id)
    """,
    """
    CREATE INDEX ix_filter_executions_filter_preset_id ON app.filter_executions
    (filter_preset_id)
    """,
    """
    CREATE INDEX ix_filter_executions_filter_preset_version_id ON app.filter_executions
    (filter_preset_version_id)
    """,
    """
    CREATE INDEX ix_filter_executions_filter_version_id ON app.filter_executions
    (filter_version_id)
    """,
    """
    CREATE INDEX ix_filter_executions_project_id ON app.filter_executions (project_id)
    """,
    """
    CREATE INDEX ix_filter_executions_result_set_id ON app.filter_executions (result_set_id)
    """,
    """
    CREATE INDEX ix_filter_executions_workspace_id ON app.filter_executions (workspace_id)
    """,
    """
    CREATE INDEX ix_filter_executions_workspace_id_executed_at ON app.filter_executions
    (workspace_id, executed_at)
    """,
    """
    CREATE TABLE app.ranking_executions ( id VARCHAR(64) NOT NULL, filter_execution_id
    VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL, project_id VARCHAR(64), executed_by
    VARCHAR(64) NOT NULL, executed_at TIMESTAMP WITH TIME ZONE NOT NULL, method_id VARCHAR(128)
    NOT NULL, method_version VARCHAR(64) NOT NULL, method_implementation_id VARCHAR(255) NOT
    NULL, effective_canonical JSONB, effective_hash VARCHAR(128) NOT NULL,
    field_dictionary_version VARCHAR(64) NOT NULL, direction VARCHAR(32) NOT NULL, tie_breakers
    JSONB, outcome VARCHAR(64) DEFAULT 'completed' NOT NULL, ranking_definition_id VARCHAR(64),
    ranking_version_id VARCHAR(64), ranking_version_number INTEGER, ranking_preset_id
    VARCHAR(64), ranking_preset_version_id VARCHAR(64), ranking_preset_version_number INTEGER,
    analysis_execution_id VARCHAR(64), scored_count INTEGER DEFAULT '0' NOT NULL, unscored_count
    INTEGER DEFAULT '0' NOT NULL, duration_ms INTEGER, software_version VARCHAR(64),
    correlation_id VARCHAR(64), failure_reason TEXT, metadata_json JSONB, created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, CONSTRAINT pk_ranking_executions PRIMARY KEY (id), CONSTRAINT
    fk_ranking_executions_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT, CONSTRAINT fk_ranking_executions_filter_execution_id FOREIGN
    KEY(filter_execution_id) REFERENCES app.filter_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_ranking_executions_ranking_preset_id FOREIGN KEY(ranking_preset_id) REFERENCES
    app.ranking_presets (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_executions_ranking_preset_version_id FOREIGN KEY(ranking_preset_version_id)
    REFERENCES app.ranking_preset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_executions_ranking_version_id FOREIGN KEY(ranking_version_id) REFERENCES
    app.ranking_configuration_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_executions_executed_by FOREIGN KEY(executed_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT ck_ranking_executions_outcome_valid CHECK (outcome IN
    ('completed', 'limit_exceeded', 'timed_out', 'cancelled', 'failed')), CONSTRAINT
    fk_ranking_executions_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id)
    ON DELETE RESTRICT, CONSTRAINT fk_ranking_executions_analysis_execution_id FOREIGN
    KEY(analysis_execution_id) REFERENCES app.analysis_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_ranking_executions_ranking_definition_id FOREIGN KEY(ranking_definition_id)
    REFERENCES app.ranking_configurations (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_ranking_executions_analysis_execution_id ON app.ranking_executions
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_executed_by ON app.ranking_executions (executed_by)
    """,
    """
    CREATE INDEX ix_ranking_executions_filter_execution_id ON app.ranking_executions
    (filter_execution_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_project_id ON app.ranking_executions (project_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_ranking_definition_id ON app.ranking_executions
    (ranking_definition_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_ranking_preset_id ON app.ranking_executions
    (ranking_preset_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_ranking_preset_version_id ON app.ranking_executions
    (ranking_preset_version_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_ranking_version_id ON app.ranking_executions
    (ranking_version_id)
    """,
    """
    CREATE INDEX ix_ranking_executions_workspace_id ON app.ranking_executions (workspace_id)
    """,
    """
    ALTER TABLE app.filter_definitions DROP CONSTRAINT ck_filter_definitions_scope_valid
    """,
    """
    ALTER TABLE app.filter_definitions ADD CONSTRAINT ck_filter_definitions_scope_valid CHECK
    (scope IN ('personal', 'project', 'organization', 'platform'))
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN state VARCHAR(64) NOT NULL DEFAULT 'draft'
    """,
    """
    ALTER TABLE app.filter_definitions ADD CONSTRAINT ck_filter_definitions_state_valid CHECK
    (state IN ('draft', 'published', 'archived'))
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN latest_version_number INTEGER NOT NULL DEFAULT
    0
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN is_referenced BOOLEAN NOT NULL DEFAULT false
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN metadata_json JSONB
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN owner_user_id VARCHAR(64) REFERENCES
    app.users(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_filter_definitions_owner_user_id ON app.filter_definitions (owner_user_id)
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN workspace_id VARCHAR(64) REFERENCES
    app.workspaces(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_filter_definitions_workspace_id ON app.filter_definitions (workspace_id)
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN project_id VARCHAR(64) REFERENCES
    app.projects(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_filter_definitions_project_id ON app.filter_definitions (project_id)
    """,
    """
    ALTER TABLE app.filter_definitions ADD COLUMN organization_id VARCHAR(64) REFERENCES
    app.organizations(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_filter_definitions_organization_id ON app.filter_definitions
    (organization_id)
    """,
    """
    ALTER TABLE app.ranking_configurations DROP CONSTRAINT ck_ranking_configurations_scope_valid
    """,
    """
    ALTER TABLE app.ranking_configurations ADD CONSTRAINT ck_ranking_configurations_scope_valid
    CHECK (scope IN ('personal', 'project', 'organization', 'platform'))
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN state VARCHAR(64) NOT NULL DEFAULT 'draft'
    """,
    """
    ALTER TABLE app.ranking_configurations ADD CONSTRAINT ck_ranking_configurations_state_valid
    CHECK (state IN ('draft', 'published', 'archived'))
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN latest_version_number INTEGER NOT NULL
    DEFAULT 0
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN is_referenced BOOLEAN NOT NULL DEFAULT
    false
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN metadata_json JSONB
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN owner_user_id VARCHAR(64) REFERENCES
    app.users(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_ranking_configurations_owner_user_id ON app.ranking_configurations
    (owner_user_id)
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN workspace_id VARCHAR(64) REFERENCES
    app.workspaces(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_ranking_configurations_workspace_id ON app.ranking_configurations
    (workspace_id)
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN project_id VARCHAR(64) REFERENCES
    app.projects(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_ranking_configurations_project_id ON app.ranking_configurations (project_id)
    """,
    """
    ALTER TABLE app.ranking_configurations ADD COLUMN organization_id VARCHAR(64) REFERENCES
    app.organizations(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_ranking_configurations_organization_id ON app.ranking_configurations
    (organization_id)
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN canonical_hash VARCHAR(128)
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN field_dictionary_version VARCHAR(64)
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN required_field_ids JSONB
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN change_note TEXT
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN is_referenced BOOLEAN NOT NULL DEFAULT
    false
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN metadata_json JSONB
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN canonical_hash VARCHAR(128)
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN field_dictionary_version
    VARCHAR(64)
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN required_field_ids JSONB
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN change_note TEXT
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN is_referenced BOOLEAN NOT NULL
    DEFAULT false
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN metadata_json JSONB
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN condition_count INTEGER NOT NULL
    DEFAULT 0
    """,
    """
    ALTER TABLE app.filter_definition_versions ADD COLUMN depth INTEGER NOT NULL DEFAULT 1
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN component_count INTEGER NOT NULL
    DEFAULT 0
    """,
    """
    ALTER TABLE app.ranking_configuration_versions ADD COLUMN canonical JSONB
    """,
    """
    ALTER TABLE app.saved_views DROP CONSTRAINT ck_saved_views_scope_valid
    """,
    """
    ALTER TABLE app.saved_views ADD CONSTRAINT ck_saved_views_scope_valid CHECK (scope IN
    ('personal', 'project', 'organization', 'platform'))
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN description TEXT
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN page_size INTEGER NOT NULL DEFAULT 50
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN metadata_json JSONB
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN filter_preset_id VARCHAR(64) REFERENCES
    app.filter_presets(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_saved_views_filter_preset_id ON app.saved_views (filter_preset_id)
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN ranking_preset_id VARCHAR(64) REFERENCES
    app.ranking_presets(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_saved_views_ranking_preset_id ON app.saved_views (ranking_preset_id)
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN owner_user_id VARCHAR(64) REFERENCES app.users(id) ON
    DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_saved_views_owner_user_id ON app.saved_views (owner_user_id)
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN workspace_id VARCHAR(64) REFERENCES
    app.workspaces(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_saved_views_workspace_id ON app.saved_views (workspace_id)
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN project_id VARCHAR(64) REFERENCES app.projects(id) ON
    DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_saved_views_project_id ON app.saved_views (project_id)
    """,
    """
    ALTER TABLE app.saved_views ADD COLUMN organization_id VARCHAR(64) REFERENCES
    app.organizations(id) ON DELETE RESTRICT
    """,
    """
    CREATE INDEX ix_saved_views_organization_id ON app.saved_views (organization_id)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP INDEX app.ix_saved_views_organization_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN organization_id
    """,
    """
    DROP INDEX app.ix_saved_views_project_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN project_id
    """,
    """
    DROP INDEX app.ix_saved_views_workspace_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN workspace_id
    """,
    """
    DROP INDEX app.ix_saved_views_owner_user_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN owner_user_id
    """,
    """
    DROP INDEX app.ix_saved_views_ranking_preset_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN ranking_preset_id
    """,
    """
    DROP INDEX app.ix_saved_views_filter_preset_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN filter_preset_id
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN metadata_json
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN page_size
    """,
    """
    ALTER TABLE app.saved_views DROP COLUMN description
    """,
    """
    ALTER TABLE app.saved_views DROP CONSTRAINT ck_saved_views_scope_valid
    """,
    """
    ALTER TABLE app.saved_views ADD CONSTRAINT ck_saved_views_scope_valid CHECK (scope IN
    ('personal', 'project', 'organization', 'platform'))
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN canonical
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN component_count
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN depth
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN condition_count
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN metadata_json
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN is_referenced
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN change_note
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN required_field_ids
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN field_dictionary_version
    """,
    """
    ALTER TABLE app.filter_definition_versions DROP COLUMN canonical_hash
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN metadata_json
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN is_referenced
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN change_note
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN required_field_ids
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN field_dictionary_version
    """,
    """
    ALTER TABLE app.ranking_configuration_versions DROP COLUMN canonical_hash
    """,
    """
    DROP INDEX app.ix_filter_definitions_organization_id
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN organization_id
    """,
    """
    DROP INDEX app.ix_filter_definitions_project_id
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN project_id
    """,
    """
    DROP INDEX app.ix_filter_definitions_workspace_id
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN workspace_id
    """,
    """
    DROP INDEX app.ix_filter_definitions_owner_user_id
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN owner_user_id
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN metadata_json
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN is_referenced
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN latest_version_number
    """,
    """
    ALTER TABLE app.filter_definitions DROP CONSTRAINT ck_filter_definitions_state_valid
    """,
    """
    ALTER TABLE app.filter_definitions DROP COLUMN state
    """,
    """
    ALTER TABLE app.filter_definitions DROP CONSTRAINT ck_filter_definitions_scope_valid
    """,
    """
    ALTER TABLE app.filter_definitions ADD CONSTRAINT ck_filter_definitions_scope_valid CHECK
    (scope IN ('personal', 'project', 'organization', 'platform'))
    """,
    """
    DROP INDEX app.ix_ranking_configurations_organization_id
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN organization_id
    """,
    """
    DROP INDEX app.ix_ranking_configurations_project_id
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN project_id
    """,
    """
    DROP INDEX app.ix_ranking_configurations_workspace_id
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN workspace_id
    """,
    """
    DROP INDEX app.ix_ranking_configurations_owner_user_id
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN owner_user_id
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN metadata_json
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN is_referenced
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN latest_version_number
    """,
    """
    ALTER TABLE app.ranking_configurations DROP CONSTRAINT ck_ranking_configurations_state_valid
    """,
    """
    ALTER TABLE app.ranking_configurations DROP COLUMN state
    """,
    """
    ALTER TABLE app.ranking_configurations DROP CONSTRAINT ck_ranking_configurations_scope_valid
    """,
    """
    ALTER TABLE app.ranking_configurations ADD CONSTRAINT ck_ranking_configurations_scope_valid
    CHECK (scope IN ('personal', 'project', 'organization', 'platform'))
    """,
    """
    DROP TABLE app.ranking_executions
    """,
    """
    DROP TABLE app.filter_executions
    """,
    """
    DROP TABLE app.ranking_preset_versions
    """,
    """
    DROP TABLE app.filter_preset_versions
    """,
    """
    DROP TABLE app.ranking_presets
    """,
    """
    DROP TABLE app.filter_presets
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
