"""Domain schema.

Creates the complete Package 2 domain and operational schema: identity,
organizations, workspaces, projects, datasets, files, ingest/validation,
analyses, jobs, scientific resources and executions, variants and observations,
annotation/frequency/clinical assertions, evidence and interpretation, review,
results/filtering/ranking, reporting/exports, notifications, audit, provenance,
domain-event outbox, configuration, retention and resource governance.

Rationale for building this revision from the declarative metadata rather than
hand-written ``op.create_table`` calls: this is the *initial* creation of every
domain table, the table set is large, and duplicating ~79 table definitions in a
second dialect of the same truth is the main source of schema drift in practice.
The revision pins the exact table set it owns in ``TABLES`` and a test asserts
that this list matches ``Base.metadata`` exactly, so drift fails the build rather
than silently reaching production. Subsequent revisions are ordinary explicit
``op.*`` migrations against this baseline.

Revision ID: 0002_domain_schema
Revises: 0001_foundation

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

revision = "0002_domain_schema"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.users",
    "app.user_authentication_metadata",
    "app.user_preferences",
    "app.platform_role_assignments",
    "app.service_accounts",
    "app.organizations",
    "app.organization_settings",
    "app.organization_memberships",
    "app.organization_invitations",
    "app.workspaces",
    "app.projects",
    "app.project_memberships",
    "app.project_invitations",
    "app.resource_assignments",
    "app.discussion_comments",
    "app.datasets",
    "app.dataset_versions",
    "app.file_artifacts",
    "app.import_sessions",
    "app.validation_rules",
    "app.validation_runs",
    "app.validation_issues",
    "app.scientific_resources",
    "app.scientific_resource_compatibility",
    "app.scientific_executions",
    "app.scientific_artifacts",
    "app.analyses",
    "app.analysis_configurations",
    "app.analysis_configuration_inputs",
    "app.analysis_executions",
    "app.analysis_execution_inputs",
    "app.variants",
    "app.variant_source_representations",
    "app.variant_external_identifiers",
    "app.genes",
    "app.transcripts",
    "app.variant_transcript_consequences",
    "app.samples",
    "app.variant_observations",
    "app.variant_annotations",
    "app.populations",
    "app.population_frequency_observations",
    "app.external_assertion_sources",
    "app.clinical_assertions",
    "app.evidence_items",
    "app.criterion_evaluations",
    "app.criterion_evaluation_evidence",
    "app.interpretations",
    "app.interpretation_versions",
    "app.review_assignments",
    "app.review_decisions",
    "app.result_sets",
    "app.filter_definitions",
    "app.filter_definition_versions",
    "app.ranking_configurations",
    "app.ranking_configuration_versions",
    "app.saved_views",
    "app.report_templates",
    "app.reports",
    "app.report_versions",
    "app.report_version_interpretations",
    "app.export_requests",
    "app.notifications",
    "app.notification_deliveries",
    "app.notification_preferences",
    "app.provenance_manifests",
    "app.provenance_entries",
    "platform.jobs",
    "platform.job_attempts",
    "platform.scheduled_jobs",
    "platform.worker_nodes",
    "platform.audit_events",
    "platform.security_events",
    "platform.domain_event_outbox",
    "platform.configuration_settings",
    "platform.configuration_setting_versions",
    "platform.retention_policies",
    "platform.retention_actions",
    "platform.resource_usage_records",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app.users ( id VARCHAR(64) NOT NULL, email VARCHAR(320) NOT NULL,
    email_normalized VARCHAR(320) NOT NULL, display_name VARCHAR(255) NOT NULL, account_state
    VARCHAR(64) DEFAULT 'pending_verification' NOT NULL, email_verification_state VARCHAR(64)
    DEFAULT 'unverified' NOT NULL, email_verified_at TIMESTAMP WITH TIME ZONE, suspended_at
    TIMESTAMP WITH TIME ZONE, suspension_reason TEXT, deactivated_at TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE, personal_workspace_id VARCHAR(64), metadata_json
    JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state
    VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by
    VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT,
    permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT ck_users_email_verification_state_valid CHECK (email_verification_state IN
    ('unverified', 'pending', 'verified', 'failed')), CONSTRAINT uq_users_email_normalized
    UNIQUE (email_normalized), CONSTRAINT ck_users_deletion_state_valid CHECK (deletion_state IN
    ('active', 'soft_deleted', 'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    ck_users_account_state_valid CHECK (account_state IN ('pending_verification', 'active',
    'suspended', 'deactivated', 'locked')) )
    """,
    """
    CREATE INDEX ix_users_account_state_deletion_state ON app.users (account_state,
    deletion_state)
    """,
    """
    CREATE TABLE app.validation_rules ( id VARCHAR(64) NOT NULL, rule_key VARCHAR(128) NOT NULL,
    rule_version VARCHAR(64) NOT NULL, description TEXT NOT NULL, default_severity VARCHAR(64)
    NOT NULL, metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_validation_rules
    PRIMARY KEY (id), CONSTRAINT uq_validation_rules_rule_key_version UNIQUE (rule_key,
    rule_version), CONSTRAINT ck_validation_rules_default_severity_valid CHECK (default_severity
    IN ('info', 'warning', 'error', 'blocking')) )
    """,
    """
    CREATE TABLE platform.resource_usage_records ( id VARCHAR(64) NOT NULL, scope VARCHAR(64)
    NOT NULL, scope_id VARCHAR(64), metric_key VARCHAR(128) NOT NULL, period_start TIMESTAMP
    WITH TIME ZONE NOT NULL, period_end TIMESTAMP WITH TIME ZONE, quantity BIGINT DEFAULT '0'
    NOT NULL, unit VARCHAR(64) NOT NULL, quota_limit BIGINT, detail JSONB, created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, CONSTRAINT pk_resource_usage_records PRIMARY KEY (id), CONSTRAINT
    uq_resource_usage_records_scope_metric_period UNIQUE (scope, scope_id, metric_key,
    period_start), CONSTRAINT ck_resource_usage_records_scope_valid CHECK (scope IN ('platform',
    'organization', 'project', 'personal')) )
    """,
    """
    CREATE INDEX ix_resource_usage_records_period_start ON platform.resource_usage_records
    (period_start)
    """,
    """
    CREATE TABLE platform.worker_nodes ( id VARCHAR(64) NOT NULL, node_key VARCHAR(128) NOT
    NULL, node_class VARCHAR(64) NOT NULL, queues JSONB, capabilities JSONB, resource_profile
    JSONB, heartbeat_at TIMESTAMP WITH TIME ZONE, drained_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_worker_nodes PRIMARY KEY (id), CONSTRAINT uq_worker_nodes_node_key UNIQUE (node_key) )
    """,
    """
    CREATE INDEX ix_worker_nodes_node_class_heartbeat_at ON platform.worker_nodes (node_class,
    heartbeat_at)
    """,
    """
    CREATE TABLE app.notification_preferences ( id VARCHAR(64) NOT NULL, user_id VARCHAR(64) NOT
    NULL, notification_kind VARCHAR(128) NOT NULL, channel VARCHAR(64) NOT NULL, enabled BOOLEAN
    DEFAULT 'true' NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT
    NULL, CONSTRAINT pk_notification_preferences PRIMARY KEY (id), CONSTRAINT
    uq_notification_preferences_user_id_kind_channel UNIQUE (user_id, notification_kind,
    channel), CONSTRAINT ck_notification_preferences_channel_valid CHECK (channel IN ('in_app',
    'email', 'webhook')), CONSTRAINT fk_notification_preferences_user_id FOREIGN KEY(user_id)
    REFERENCES app.users (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_notification_preferences_user_id ON app.notification_preferences (user_id)
    """,
    """
    CREATE TABLE app.organizations ( id VARCHAR(64) NOT NULL, slug VARCHAR(128) NOT NULL, name
    VARCHAR(255) NOT NULL, description TEXT, state VARCHAR(64) DEFAULT 'requested' NOT NULL,
    requested_by VARCHAR(64), requested_at TIMESTAMP WITH TIME ZONE, approval_decided_by
    VARCHAR(64), approval_decided_at TIMESTAMP WITH TIME ZONE, approval_decision_reason TEXT,
    suspended_at TIMESTAMP WITH TIME ZONE, deactivated_at TIMESTAMP WITH TIME ZONE,
    metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL,
    deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE,
    deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason
    TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_organizations PRIMARY
    KEY (id), CONSTRAINT ck_organizations_deletion_state_valid CHECK (deletion_state IN
    ('active', 'soft_deleted', 'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    fk_organizations_requested_by FOREIGN KEY(requested_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT ck_organizations_state_valid CHECK (state IN ('requested', 'pending',
    'approved', 'rejected', 'active', 'suspended', 'deactivated')), CONSTRAINT
    fk_organizations_approval_decided_by FOREIGN KEY(approval_decided_by) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT uq_organizations_slug UNIQUE (slug) )
    """,
    """
    CREATE INDEX ix_organizations_approval_decided_by ON app.organizations (approval_decided_by)
    """,
    """
    CREATE INDEX ix_organizations_requested_by ON app.organizations (requested_by)
    """,
    """
    CREATE INDEX ix_organizations_state_deletion_state ON app.organizations (state,
    deletion_state)
    """,
    """
    CREATE TABLE app.platform_role_assignments ( id VARCHAR(64) NOT NULL, user_id VARCHAR(64)
    NOT NULL, role VARCHAR(64) NOT NULL, granted_by VARCHAR(64), granted_at TIMESTAMP WITH TIME
    ZONE, revoked_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
    NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_platform_role_assignments PRIMARY KEY (id), CONSTRAINT
    uq_platform_role_assignments_user_id_role UNIQUE (user_id, role), CONSTRAINT
    fk_platform_role_assignments_user_id FOREIGN KEY(user_id) REFERENCES app.users (id) ON
    DELETE CASCADE, CONSTRAINT ck_platform_role_assignments_role_valid CHECK (role IN
    ('platform_administrator', 'platform_operator', 'user')), CONSTRAINT
    fk_platform_role_assignments_granted_by FOREIGN KEY(granted_by) REFERENCES app.users (id) ON
    DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_platform_role_assignments_granted_by ON app.platform_role_assignments
    (granted_by)
    """,
    """
    CREATE INDEX ix_platform_role_assignments_user_id ON app.platform_role_assignments (user_id)
    """,
    """
    CREATE TABLE app.scientific_resources ( id VARCHAR(64) NOT NULL, kind VARCHAR(64) NOT NULL,
    resource_key VARCHAR(255) NOT NULL, version VARCHAR(128) NOT NULL, display_name VARCHAR(255)
    NOT NULL, description TEXT, state VARCHAR(64) DEFAULT 'registered' NOT NULL, activated_at
    TIMESTAMP WITH TIME ZONE, deprecated_at TIMESTAMP WITH TIME ZONE, retired_at TIMESTAMP WITH
    TIME ZONE, invalidated_at TIMESTAMP WITH TIME ZONE, invalidation_reason TEXT,
    checksum_algorithm VARCHAR(64), checksum_value VARCHAR(256), size_bytes BIGINT, provenance
    JSONB, licensing JSONB, compatibility JSONB, metadata_json JSONB, registered_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_scientific_resources PRIMARY KEY (id), CONSTRAINT
    ck_scientific_resources_checksum_algorithm_valid CHECK (checksum_algorithm IN ('sha256',
    'sha512', 'md5', 'crc32c')), CONSTRAINT uq_scientific_resources_kind_resource_key_version
    UNIQUE (kind, resource_key, version), CONSTRAINT ck_scientific_resources_state_valid CHECK
    (state IN ('registered', 'validating', 'active', 'deprecated', 'retired', 'invalidated')),
    CONSTRAINT fk_scientific_resources_registered_by FOREIGN KEY(registered_by) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT ck_scientific_resources_kind_valid CHECK (kind
    IN ('reference_genome', 'annotation_resource', 'population_resource', 'clinical_database',
    'evidence_resource', 'ruleset', 'environment', 'engine', 'pipeline', 'execution_profile')) )
    """,
    """
    CREATE INDEX ix_scientific_resources_kind_state ON app.scientific_resources (kind, state)
    """,
    """
    CREATE INDEX ix_scientific_resources_registered_by ON app.scientific_resources
    (registered_by)
    """,
    """
    CREATE TABLE app.service_accounts ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL,
    description TEXT, actor_type VARCHAR(64) DEFAULT 'service_account' NOT NULL, organization_id
    VARCHAR(64), created_by VARCHAR(64), disabled_at TIMESTAMP WITH TIME ZONE, created_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT
    'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64),
    retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT,
    permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_service_accounts PRIMARY KEY
    (id), CONSTRAINT ck_service_accounts_actor_type_valid CHECK (actor_type IN ('user',
    'service_account', 'system', 'scheduler', 'worker')), CONSTRAINT
    ck_service_accounts_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT uq_service_accounts_name
    UNIQUE (name), CONSTRAINT fk_service_accounts_created_by FOREIGN KEY(created_by) REFERENCES
    app.users (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_service_accounts_created_by ON app.service_accounts (created_by)
    """,
    """
    CREATE TABLE app.user_authentication_metadata ( id VARCHAR(64) NOT NULL, user_id VARCHAR(64)
    NOT NULL, password_hash TEXT, password_algorithm VARCHAR(64), password_updated_at TIMESTAMP
    WITH TIME ZONE, mfa_enabled BOOLEAN DEFAULT 'false' NOT NULL, mfa_enrolled_at TIMESTAMP WITH
    TIME ZONE, failed_attempt_count INTEGER DEFAULT '0' NOT NULL, locked_until TIMESTAMP WITH
    TIME ZONE, last_successful_authentication_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_user_authentication_metadata
    PRIMARY KEY (id), CONSTRAINT fk_user_authentication_metadata_user_id FOREIGN KEY(user_id)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_user_authentication_metadata_user_id UNIQUE (user_id) )
    """,
    """
    CREATE INDEX ix_user_authentication_metadata_user_id ON app.user_authentication_metadata
    (user_id)
    """,
    """
    CREATE TABLE app.user_preferences ( id VARCHAR(64) NOT NULL, user_id VARCHAR(64) NOT NULL,
    preference_key VARCHAR(128) NOT NULL, preference_value JSONB, created_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_user_preferences PRIMARY KEY (id),
    CONSTRAINT fk_user_preferences_user_id FOREIGN KEY(user_id) REFERENCES app.users (id) ON
    DELETE CASCADE, CONSTRAINT uq_user_preferences_user_id_key UNIQUE (user_id, preference_key)
    )
    """,
    """
    CREATE INDEX ix_user_preferences_user_id ON app.user_preferences (user_id)
    """,
    """
    CREATE TABLE platform.configuration_settings ( id VARCHAR(64) NOT NULL, scope VARCHAR(64)
    NOT NULL, scope_id VARCHAR(64), setting_key VARCHAR(255) NOT NULL, state VARCHAR(64) DEFAULT
    'active' NOT NULL, value_json JSONB, is_sensitive BOOLEAN DEFAULT 'false' NOT NULL,
    version_number INTEGER DEFAULT '1' NOT NULL, updated_by VARCHAR(64), change_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_configuration_settings PRIMARY KEY (id), CONSTRAINT ck_configuration_settings_scope_valid
    CHECK (scope IN ('platform', 'organization', 'project', 'personal')), CONSTRAINT
    ck_configuration_settings_state_valid CHECK (state IN ('draft', 'active', 'superseded',
    'retired')), CONSTRAINT fk_configuration_settings_updated_by FOREIGN KEY(updated_by)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_configuration_settings_scope_scope_id_setting_key UNIQUE (scope, scope_id, setting_key) )
    """,
    """
    CREATE INDEX ix_configuration_settings_setting_key ON platform.configuration_settings
    (setting_key)
    """,
    """
    CREATE INDEX ix_configuration_settings_updated_by ON platform.configuration_settings
    (updated_by)
    """,
    """
    CREATE TABLE platform.retention_policies ( id VARCHAR(64) NOT NULL, scope VARCHAR(64) NOT
    NULL, scope_id VARCHAR(64), resource_type VARCHAR(128) NOT NULL, soft_delete_retention_days
    INTEGER, purge_enabled BOOLEAN DEFAULT 'false' NOT NULL, legal_hold BOOLEAN DEFAULT 'false'
    NOT NULL, updated_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT
    '1' NOT NULL, CONSTRAINT pk_retention_policies PRIMARY KEY (id), CONSTRAINT
    fk_retention_policies_updated_by FOREIGN KEY(updated_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT ck_retention_policies_scope_valid CHECK (scope IN ('platform',
    'organization', 'project', 'personal')), CONSTRAINT
    uq_retention_policies_scope_scope_id_resource_type UNIQUE (scope, scope_id, resource_type) )
    """,
    """
    CREATE INDEX ix_retention_policies_updated_by ON platform.retention_policies (updated_by)
    """,
    """
    CREATE TABLE platform.security_events ( id VARCHAR(64) NOT NULL, occurred_at TIMESTAMP WITH
    TIME ZONE NOT NULL, event_kind VARCHAR(128) NOT NULL, outcome VARCHAR(64) NOT NULL,
    subject_user_id VARCHAR(64), subject_identifier_hash VARCHAR(128), request_ip_hash
    VARCHAR(128), detail JSONB, correlation_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_security_events PRIMARY KEY (id), CONSTRAINT ck_security_events_outcome_valid
    CHECK (outcome IN ('success', 'failure', 'denied')), CONSTRAINT
    fk_security_events_subject_user_id FOREIGN KEY(subject_user_id) REFERENCES app.users (id) ON
    DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_security_events_event_kind ON platform.security_events (event_kind)
    """,
    """
    CREATE INDEX ix_security_events_occurred_at ON platform.security_events (occurred_at)
    """,
    """
    CREATE INDEX ix_security_events_subject_user_id ON platform.security_events
    (subject_user_id)
    """,
    """
    CREATE TABLE app.external_assertion_sources ( id VARCHAR(64) NOT NULL, source_key
    VARCHAR(128) NOT NULL, source_version VARCHAR(128) NOT NULL, resource_id VARCHAR(64),
    display_name VARCHAR(255), metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_external_assertion_sources PRIMARY KEY (id), CONSTRAINT
    fk_external_assertion_sources_resource_id FOREIGN KEY(resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    uq_external_assertion_sources_source_key_source_version UNIQUE (source_key, source_version)
    )
    """,
    """
    CREATE INDEX ix_external_assertion_sources_resource_id ON app.external_assertion_sources
    (resource_id)
    """,
    """
    CREATE TABLE app.genes ( id VARCHAR(64) NOT NULL, namespace VARCHAR(64) NOT NULL,
    gene_identifier VARCHAR(128) NOT NULL, symbol VARCHAR(128), source_resource_id VARCHAR(64),
    metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_genes PRIMARY KEY (id),
    CONSTRAINT uq_genes_namespace_gene_identifier UNIQUE (namespace, gene_identifier),
    CONSTRAINT fk_genes_source_resource_id FOREIGN KEY(source_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_genes_source_resource_id ON app.genes (source_resource_id)
    """,
    """
    CREATE INDEX ix_genes_symbol ON app.genes (symbol)
    """,
    """
    CREATE TABLE app.organization_invitations ( id VARCHAR(64) NOT NULL, organization_id
    VARCHAR(64) NOT NULL, invited_email_normalized VARCHAR(320) NOT NULL, role VARCHAR(64) NOT
    NULL, state VARCHAR(64) DEFAULT 'pending' NOT NULL, token_hash VARCHAR(128) NOT NULL,
    invited_by VARCHAR(64), expires_at TIMESTAMP WITH TIME ZONE NOT NULL, responded_at TIMESTAMP
    WITH TIME ZONE, accepted_user_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER
    DEFAULT '1' NOT NULL, CONSTRAINT pk_organization_invitations PRIMARY KEY (id), CONSTRAINT
    uq_organization_invitations_token_hash UNIQUE (token_hash), CONSTRAINT
    ck_organization_invitations_role_valid CHECK (role IN ('owner', 'admin', 'member',
    'billing', 'guest')), CONSTRAINT fk_organization_invitations_invited_by FOREIGN
    KEY(invited_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    ck_organization_invitations_state_valid CHECK (state IN ('pending', 'accepted', 'declined',
    'revoked', 'expired')), CONSTRAINT fk_organization_invitations_accepted_user_id FOREIGN
    KEY(accepted_user_id) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_organization_invitations_organization_id FOREIGN KEY(organization_id) REFERENCES
    app.organizations (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_organization_invitations_accepted_user_id ON app.organization_invitations
    (accepted_user_id)
    """,
    """
    CREATE INDEX ix_organization_invitations_invited_by ON app.organization_invitations
    (invited_by)
    """,
    """
    CREATE INDEX ix_organization_invitations_organization_id ON app.organization_invitations
    (organization_id)
    """,
    """
    CREATE INDEX ix_organization_invitations_organization_id_state ON
    app.organization_invitations (organization_id, state)
    """,
    """
    CREATE TABLE app.organization_memberships ( id VARCHAR(64) NOT NULL, organization_id
    VARCHAR(64) NOT NULL, user_id VARCHAR(64) NOT NULL, role VARCHAR(64) DEFAULT 'member' NOT
    NULL, state VARCHAR(64) DEFAULT 'invited' NOT NULL, invited_by VARCHAR(64), joined_at
    TIMESTAMP WITH TIME ZONE, left_at TIMESTAMP WITH TIME ZONE, removed_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_organization_memberships PRIMARY KEY (id), CONSTRAINT
    ck_organization_memberships_role_valid CHECK (role IN ('owner', 'admin', 'member',
    'billing', 'guest')), CONSTRAINT fk_organization_memberships_removed_by FOREIGN
    KEY(removed_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_organization_memberships_organization_id_user_id UNIQUE (organization_id, user_id),
    CONSTRAINT fk_organization_memberships_user_id FOREIGN KEY(user_id) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT ck_organization_memberships_state_valid CHECK (state IN
    ('invited', 'active', 'suspended', 'left', 'removed')), CONSTRAINT
    fk_organization_memberships_invited_by FOREIGN KEY(invited_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_organization_memberships_organization_id FOREIGN
    KEY(organization_id) REFERENCES app.organizations (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_organization_memberships_invited_by ON app.organization_memberships
    (invited_by)
    """,
    """
    CREATE INDEX ix_organization_memberships_organization_id ON app.organization_memberships
    (organization_id)
    """,
    """
    CREATE INDEX ix_organization_memberships_removed_by ON app.organization_memberships
    (removed_by)
    """,
    """
    CREATE INDEX ix_organization_memberships_user_id ON app.organization_memberships (user_id)
    """,
    """
    CREATE INDEX ix_organization_memberships_user_id_state ON app.organization_memberships
    (user_id, state)
    """,
    """
    CREATE TABLE app.organization_settings ( id VARCHAR(64) NOT NULL, organization_id
    VARCHAR(64) NOT NULL, setting_key VARCHAR(128) NOT NULL, setting_value JSONB, updated_by
    VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL,
    CONSTRAINT pk_organization_settings PRIMARY KEY (id), CONSTRAINT
    fk_organization_settings_updated_by FOREIGN KEY(updated_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_organization_settings_organization_id FOREIGN
    KEY(organization_id) REFERENCES app.organizations (id) ON DELETE CASCADE, CONSTRAINT
    uq_organization_settings_organization_id_key UNIQUE (organization_id, setting_key) )
    """,
    """
    CREATE INDEX ix_organization_settings_organization_id ON app.organization_settings
    (organization_id)
    """,
    """
    CREATE INDEX ix_organization_settings_updated_by ON app.organization_settings (updated_by)
    """,
    """
    CREATE TABLE app.populations ( id VARCHAR(64) NOT NULL, population_resource_id VARCHAR(64)
    NOT NULL, population_key VARCHAR(128) NOT NULL, display_name VARCHAR(255), metadata_json
    JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_populations PRIMARY KEY (id), CONSTRAINT
    uq_populations_population_resource_id_population_key UNIQUE (population_resource_id,
    population_key), CONSTRAINT fk_populations_population_resource_id FOREIGN
    KEY(population_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_populations_population_resource_id ON app.populations
    (population_resource_id)
    """,
    """
    CREATE TABLE app.report_templates ( id VARCHAR(64) NOT NULL, template_key VARCHAR(128) NOT
    NULL, version_number INTEGER NOT NULL, display_name VARCHAR(255) NOT NULL, organization_id
    VARCHAR(64), definition JSONB, created_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version
    INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_report_templates PRIMARY KEY (id), CONSTRAINT
    fk_report_templates_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT uq_report_templates_template_key_version_number UNIQUE (template_key,
    version_number), CONSTRAINT fk_report_templates_organization_id FOREIGN KEY(organization_id)
    REFERENCES app.organizations (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_report_templates_created_by ON app.report_templates (created_by)
    """,
    """
    CREATE INDEX ix_report_templates_organization_id ON app.report_templates (organization_id)
    """,
    """
    CREATE TABLE app.scientific_resource_compatibility ( id VARCHAR(64) NOT NULL, resource_id
    VARCHAR(64) NOT NULL, compatible_resource_id VARCHAR(64) NOT NULL, relation VARCHAR(64) NOT
    NULL, notes TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_scientific_resource_compatibility PRIMARY KEY (id), CONSTRAINT
    fk_scientific_resource_compatibility_compatible_resource_id FOREIGN
    KEY(compatible_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT fk_scientific_resource_compatibility_resource_id FOREIGN KEY(resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE CASCADE, CONSTRAINT
    uq_scientific_resource_compatibility_resource_id_compatible UNIQUE (resource_id,
    compatible_resource_id) )
    """,
    """
    CREATE INDEX ix_scientific_resource_compatibility_compatible_resource_id ON
    app.scientific_resource_compatibility (compatible_resource_id)
    """,
    """
    CREATE INDEX ix_scientific_resource_compatibility_resource_id ON
    app.scientific_resource_compatibility (resource_id)
    """,
    """
    CREATE TABLE app.workspaces ( id VARCHAR(64) NOT NULL, kind VARCHAR(64) NOT NULL, name
    VARCHAR(255) NOT NULL, owner_user_id VARCHAR(64), organization_id VARCHAR(64), created_by
    VARCHAR(64), metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT
    '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP
    WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE,
    deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_workspaces PRIMARY KEY (id), CONSTRAINT ck_workspaces_ck_workspaces_scope_exclusive CHECK
    ((kind = 'personal' AND organization_id IS NULL AND owner_user_id IS NOT NULL) OR (kind =
    'organization' AND organization_id IS NOT NULL)), CONSTRAINT fk_workspaces_created_by
    FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    ck_workspaces_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    uq_workspaces_organization_id UNIQUE (organization_id), CONSTRAINT ck_workspaces_kind_valid
    CHECK (kind IN ('personal', 'organization')), CONSTRAINT fk_workspaces_organization_id
    FOREIGN KEY(organization_id) REFERENCES app.organizations (id) ON DELETE RESTRICT,
    CONSTRAINT fk_workspaces_owner_user_id FOREIGN KEY(owner_user_id) REFERENCES app.users (id)
    ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_workspaces_created_by ON app.workspaces (created_by)
    """,
    """
    CREATE INDEX ix_workspaces_organization_id ON app.workspaces (organization_id)
    """,
    """
    CREATE INDEX ix_workspaces_owner_user_id ON app.workspaces (owner_user_id)
    """,
    """
    CREATE UNIQUE INDEX uq_workspaces_personal_owner ON app.workspaces (owner_user_id) WHERE
    kind = 'personal'
    """,
    """
    CREATE TABLE platform.configuration_setting_versions ( id VARCHAR(64) NOT NULL,
    configuration_setting_id VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, value_json
    JSONB, updated_by VARCHAR(64), change_reason TEXT, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_configuration_setting_versions PRIMARY KEY (id), CONSTRAINT
    fk_configuration_setting_versions_updated_by FOREIGN KEY(updated_by) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT
    fk_configuration_setting_versions_configuration_setting_id FOREIGN
    KEY(configuration_setting_id) REFERENCES platform.configuration_settings (id) ON DELETE
    CASCADE, CONSTRAINT uq_configuration_setting_versions_setting_id_version_number UNIQUE
    (configuration_setting_id, version_number) )
    """,
    """
    CREATE INDEX ix_configuration_setting_versions_configuration_setting_id ON
    platform.configuration_setting_versions (configuration_setting_id)
    """,
    """
    CREATE INDEX ix_configuration_setting_versions_updated_by ON
    platform.configuration_setting_versions (updated_by)
    """,
    """
    CREATE TABLE platform.retention_actions ( id VARCHAR(64) NOT NULL, resource_type
    VARCHAR(128) NOT NULL, resource_id VARCHAR(64) NOT NULL, retention_policy_id VARCHAR(64),
    previous_state VARCHAR(64), target_state VARCHAR(64) NOT NULL, performed_by VARCHAR(64),
    job_id VARCHAR(64), performed_at TIMESTAMP WITH TIME ZONE NOT NULL, dependency_summary
    JSONB, recoverable_until TIMESTAMP WITH TIME ZONE, reason TEXT, created_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, CONSTRAINT pk_retention_actions PRIMARY KEY (id), CONSTRAINT
    fk_retention_actions_performed_by FOREIGN KEY(performed_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT ck_retention_actions_target_state_valid CHECK (target_state IN
    ('active', 'soft_deleted', 'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    fk_retention_actions_retention_policy_id FOREIGN KEY(retention_policy_id) REFERENCES
    platform.retention_policies (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_retention_actions_performed_by ON platform.retention_actions (performed_by)
    """,
    """
    CREATE INDEX ix_retention_actions_resource_type_resource_id ON platform.retention_actions
    (resource_type, resource_id)
    """,
    """
    CREATE INDEX ix_retention_actions_retention_policy_id ON platform.retention_actions
    (retention_policy_id)
    """,
    """
    CREATE TABLE app.projects ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL, name
    VARCHAR(255) NOT NULL, description TEXT, state VARCHAR(64) DEFAULT 'draft' NOT NULL,
    created_by VARCHAR(64) NOT NULL, owner_user_id VARCHAR(64), configuration_id VARCHAR(64),
    configuration_version INTEGER, archived_at TIMESTAMP WITH TIME ZONE, archived_by
    VARCHAR(64), reopened_at TIMESTAMP WITH TIME ZONE, closed_at TIMESTAMP WITH TIME ZONE,
    metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL,
    deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE,
    deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason
    TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_projects PRIMARY KEY
    (id), CONSTRAINT uq_projects_workspace_id_name UNIQUE (workspace_id, name), CONSTRAINT
    fk_projects_archived_by FOREIGN KEY(archived_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_projects_created_by FOREIGN KEY(created_by) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT ck_projects_state_valid CHECK (state IN ('draft',
    'active', 'archived', 'suspended', 'closed')), CONSTRAINT ck_projects_deletion_state_valid
    CHECK (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')), CONSTRAINT fk_projects_owner_user_id FOREIGN KEY(owner_user_id)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_projects_workspace_id FOREIGN
    KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_projects_archived_by ON app.projects (archived_by)
    """,
    """
    CREATE INDEX ix_projects_created_by ON app.projects (created_by)
    """,
    """
    CREATE INDEX ix_projects_owner_user_id ON app.projects (owner_user_id)
    """,
    """
    CREATE INDEX ix_projects_workspace_id ON app.projects (workspace_id)
    """,
    """
    CREATE INDEX ix_projects_workspace_id_state_deletion_state ON app.projects (workspace_id,
    state, deletion_state)
    """,
    """
    CREATE TABLE app.transcripts ( id VARCHAR(64) NOT NULL, namespace VARCHAR(64) NOT NULL,
    transcript_identifier VARCHAR(128) NOT NULL, transcript_version VARCHAR(32), gene_id
    VARCHAR(64), is_canonical BOOLEAN, source_resource_id VARCHAR(64), metadata_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_transcripts PRIMARY KEY (id), CONSTRAINT
    fk_transcripts_source_resource_id FOREIGN KEY(source_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT fk_transcripts_gene_id FOREIGN
    KEY(gene_id) REFERENCES app.genes (id) ON DELETE RESTRICT, CONSTRAINT
    uq_transcripts_namespace_transcript_identifier_version UNIQUE (namespace,
    transcript_identifier, transcript_version) )
    """,
    """
    CREATE INDEX ix_transcripts_gene_id ON app.transcripts (gene_id)
    """,
    """
    CREATE INDEX ix_transcripts_source_resource_id ON app.transcripts (source_resource_id)
    """,
    """
    CREATE TABLE platform.domain_event_outbox ( id VARCHAR(64) NOT NULL, event_key VARCHAR(255)
    NOT NULL, event_type VARCHAR(128) NOT NULL, event_version INTEGER DEFAULT '1' NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, aggregate_type VARCHAR(128), aggregate_id
    VARCHAR(64), workspace_id VARCHAR(64), payload JSONB, state VARCHAR(64) DEFAULT 'pending'
    NOT NULL, attempt_number INTEGER DEFAULT '0' NOT NULL, available_at TIMESTAMP WITH TIME
    ZONE, dispatched_at TIMESTAMP WITH TIME ZONE, failure_message TEXT, correlation_id
    VARCHAR(64), causation_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_domain_event_outbox PRIMARY KEY (id), CONSTRAINT ck_domain_event_outbox_state_valid CHECK
    (state IN ('pending', 'dispatching', 'dispatched', 'failed', 'dead_letter')), CONSTRAINT
    uq_domain_event_outbox_event_key UNIQUE (event_key), CONSTRAINT
    fk_domain_event_outbox_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id)
    ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_domain_event_outbox_correlation_id ON platform.domain_event_outbox
    (correlation_id)
    """,
    """
    CREATE INDEX ix_domain_event_outbox_state_available_at ON platform.domain_event_outbox
    (state, available_at)
    """,
    """
    CREATE INDEX ix_domain_event_outbox_workspace_id ON platform.domain_event_outbox
    (workspace_id)
    """,
    """
    CREATE TABLE app.analyses ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL, description TEXT, kind
    VARCHAR(64) NOT NULL, capability_key VARCHAR(128), state VARCHAR(64) DEFAULT 'draft' NOT
    NULL, created_by VARCHAR(64) NOT NULL, owner_user_id VARCHAR(64), current_configuration_id
    VARCHAR(64), metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT
    '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP
    WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE,
    deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_analyses PRIMARY KEY (id), CONSTRAINT fk_analyses_owner_user_id FOREIGN
    KEY(owner_user_id) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analyses_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON DELETE
    RESTRICT, CONSTRAINT ck_analyses_state_valid CHECK (state IN ('draft', 'ready', 'active',
    'archived')), CONSTRAINT uq_analyses_project_id_name UNIQUE (project_id, name), CONSTRAINT
    ck_analyses_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT fk_analyses_workspace_id
    FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analyses_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE RESTRICT,
    CONSTRAINT ck_analyses_kind_valid CHECK (kind IN ('variant_prioritization', 'annotation',
    'filtering', 'ranking', 'interpretation', 'quality_control', 'custom', 'genomic_analysis',
    'annotated_data_analysis', 'import_processing', 'scientific_pipeline')) )
    """,
    """
    CREATE INDEX ix_analyses_created_by ON app.analyses (created_by)
    """,
    """
    CREATE INDEX ix_analyses_owner_user_id ON app.analyses (owner_user_id)
    """,
    """
    CREATE INDEX ix_analyses_project_id ON app.analyses (project_id)
    """,
    """
    CREATE INDEX ix_analyses_workspace_id ON app.analyses (workspace_id)
    """,
    """
    CREATE INDEX ix_analyses_workspace_id_state ON app.analyses (workspace_id, state)
    """,
    """
    CREATE TABLE app.datasets ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64), name VARCHAR(255) NOT NULL, description TEXT, kind VARCHAR(64) NOT
    NULL, state VARCHAR(64) DEFAULT 'draft' NOT NULL, created_by VARCHAR(64) NOT NULL,
    owner_user_id VARCHAR(64), current_version_id VARCHAR(64), source_metadata JSONB,
    scientific_metadata JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT
    NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME
    ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE,
    deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_datasets PRIMARY KEY (id), CONSTRAINT ck_datasets_kind_valid CHECK (kind IN
    ('variant_calls', 'alignment', 'sample_manifest', 'phenotype', 'annotation_input',
    'derived_result', 'other')), CONSTRAINT fk_datasets_owner_user_id FOREIGN KEY(owner_user_id)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_datasets_project_id FOREIGN
    KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    ck_datasets_state_valid CHECK (state IN ('draft', 'validating', 'ready', 'rejected',
    'archived')), CONSTRAINT uq_datasets_workspace_id_name UNIQUE (workspace_id, name),
    CONSTRAINT fk_datasets_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_datasets_workspace_id FOREIGN KEY(workspace_id) REFERENCES
    app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT ck_datasets_deletion_state_valid CHECK
    (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')) )
    """,
    """
    CREATE INDEX ix_datasets_created_by ON app.datasets (created_by)
    """,
    """
    CREATE INDEX ix_datasets_owner_user_id ON app.datasets (owner_user_id)
    """,
    """
    CREATE INDEX ix_datasets_project_id ON app.datasets (project_id)
    """,
    """
    CREATE INDEX ix_datasets_project_id_state ON app.datasets (project_id, state)
    """,
    """
    CREATE INDEX ix_datasets_workspace_id ON app.datasets (workspace_id)
    """,
    """
    CREATE TABLE app.discussion_comments ( id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT
    NULL, resource_type VARCHAR(64) NOT NULL, resource_id VARCHAR(64) NOT NULL,
    parent_comment_id VARCHAR(64), author_user_id VARCHAR(64) NOT NULL, body TEXT NOT NULL,
    edited_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT
    '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP
    WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE,
    deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_discussion_comments PRIMARY KEY (id), CONSTRAINT fk_discussion_comments_author_user_id
    FOREIGN KEY(author_user_id) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_discussion_comments_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT, CONSTRAINT ck_discussion_comments_deletion_state_valid CHECK
    (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')), CONSTRAINT fk_discussion_comments_parent_comment_id FOREIGN
    KEY(parent_comment_id) REFERENCES app.discussion_comments (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_discussion_comments_author_user_id ON app.discussion_comments
    (author_user_id)
    """,
    """
    CREATE INDEX ix_discussion_comments_parent_comment_id ON app.discussion_comments
    (parent_comment_id)
    """,
    """
    CREATE INDEX ix_discussion_comments_project_id ON app.discussion_comments (project_id)
    """,
    """
    CREATE INDEX ix_discussion_comments_resource ON app.discussion_comments (resource_type,
    resource_id)
    """,
    """
    CREATE TABLE app.filter_definitions ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL,
    description TEXT, scope VARCHAR(64) NOT NULL, scope_id VARCHAR(64), is_preset BOOLEAN
    DEFAULT 'false' NOT NULL, current_version_number INTEGER DEFAULT '1' NOT NULL,
    predicate_tree JSONB, created_by VARCHAR(64), updated_by VARCHAR(64), created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT
    NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at
    TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH
    TIME ZONE, CONSTRAINT pk_filter_definitions PRIMARY KEY (id), CONSTRAINT
    fk_filter_definitions_updated_by FOREIGN KEY(updated_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT uq_filter_definitions_scope_scope_id_name UNIQUE (scope, scope_id,
    name), CONSTRAINT ck_filter_definitions_deletion_state_valid CHECK (deletion_state IN
    ('active', 'soft_deleted', 'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    fk_filter_definitions_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_filter_definitions_created_by ON app.filter_definitions (created_by)
    """,
    """
    CREATE INDEX ix_filter_definitions_scope_scope_id ON app.filter_definitions (scope,
    scope_id)
    """,
    """
    CREATE INDEX ix_filter_definitions_updated_by ON app.filter_definitions (updated_by)
    """,
    """
    ALTER TABLE app.filter_definitions ADD CONSTRAINT ck_filter_definitions_scope_valid CHECK
    (scope IN ('personal', 'project', 'organization', 'platform'))
    """,
    """
    CREATE TABLE app.notifications ( id VARCHAR(64) NOT NULL, recipient_user_id VARCHAR(64) NOT
    NULL, workspace_id VARCHAR(64), project_id VARCHAR(64), notification_kind VARCHAR(128) NOT
    NULL, state VARCHAR(64) DEFAULT 'unread' NOT NULL, subject VARCHAR(255) NOT NULL, body TEXT,
    subject_resource_type VARCHAR(128), subject_resource_id VARCHAR(64), payload JSONB, read_at
    TIMESTAMP WITH TIME ZONE, archived_at TIMESTAMP WITH TIME ZONE, correlation_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_notifications PRIMARY KEY (id), CONSTRAINT ck_notifications_state_valid CHECK (state IN
    ('unread', 'read', 'archived')), CONSTRAINT fk_notifications_project_id FOREIGN
    KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    fk_notifications_recipient_user_id FOREIGN KEY(recipient_user_id) REFERENCES app.users (id)
    ON DELETE RESTRICT, CONSTRAINT fk_notifications_workspace_id FOREIGN KEY(workspace_id)
    REFERENCES app.workspaces (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_notifications_created_at ON app.notifications (created_at)
    """,
    """
    CREATE INDEX ix_notifications_project_id ON app.notifications (project_id)
    """,
    """
    CREATE INDEX ix_notifications_recipient_user_id ON app.notifications (recipient_user_id)
    """,
    """
    CREATE INDEX ix_notifications_recipient_user_id_state ON app.notifications
    (recipient_user_id, state)
    """,
    """
    CREATE INDEX ix_notifications_workspace_id ON app.notifications (workspace_id)
    """,
    """
    CREATE TABLE app.project_invitations ( id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT
    NULL, invited_email_normalized VARCHAR(320) NOT NULL, role VARCHAR(64) NOT NULL, state
    VARCHAR(64) DEFAULT 'pending' NOT NULL, token_hash VARCHAR(128) NOT NULL, invited_by
    VARCHAR(64), expires_at TIMESTAMP WITH TIME ZONE NOT NULL, responded_at TIMESTAMP WITH TIME
    ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_project_invitations PRIMARY KEY (id), CONSTRAINT ck_project_invitations_role_valid CHECK
    (role IN ('owner', 'manager', 'analyst', 'reviewer', 'viewer')), CONSTRAINT
    fk_project_invitations_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE CASCADE, CONSTRAINT ck_project_invitations_state_valid CHECK (state IN ('pending',
    'accepted', 'declined', 'revoked', 'expired')), CONSTRAINT uq_project_invitations_token_hash
    UNIQUE (token_hash), CONSTRAINT fk_project_invitations_invited_by FOREIGN KEY(invited_by)
    REFERENCES app.users (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_project_invitations_invited_by ON app.project_invitations (invited_by)
    """,
    """
    CREATE INDEX ix_project_invitations_project_id ON app.project_invitations (project_id)
    """,
    """
    CREATE INDEX ix_project_invitations_project_id_state ON app.project_invitations (project_id,
    state)
    """,
    """
    CREATE TABLE app.project_memberships ( id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT
    NULL, user_id VARCHAR(64) NOT NULL, role VARCHAR(64) NOT NULL, state VARCHAR(64) DEFAULT
    'active' NOT NULL, granted_by VARCHAR(64), joined_at TIMESTAMP WITH TIME ZONE, left_at
    TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT
    NULL, CONSTRAINT pk_project_memberships PRIMARY KEY (id), CONSTRAINT
    uq_project_memberships_project_id_user_id UNIQUE (project_id, user_id), CONSTRAINT
    ck_project_memberships_role_valid CHECK (role IN ('owner', 'manager', 'analyst', 'reviewer',
    'viewer')), CONSTRAINT fk_project_memberships_user_id FOREIGN KEY(user_id) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_project_memberships_granted_by FOREIGN
    KEY(granted_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_project_memberships_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT, CONSTRAINT ck_project_memberships_state_valid CHECK (state IN ('invited',
    'active', 'suspended', 'left', 'removed')) )
    """,
    """
    CREATE INDEX ix_project_memberships_granted_by ON app.project_memberships (granted_by)
    """,
    """
    CREATE INDEX ix_project_memberships_project_id ON app.project_memberships (project_id)
    """,
    """
    CREATE INDEX ix_project_memberships_user_id ON app.project_memberships (user_id)
    """,
    """
    CREATE INDEX ix_project_memberships_user_id_state ON app.project_memberships (user_id,
    state)
    """,
    """
    CREATE TABLE app.ranking_configurations ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT
    NULL, description TEXT, scope VARCHAR(64) NOT NULL, scope_id VARCHAR(64), is_preset BOOLEAN
    DEFAULT 'false' NOT NULL, method_key VARCHAR(128) NOT NULL, method_version VARCHAR(128),
    method_resource_id VARCHAR(64), current_version_number INTEGER DEFAULT '1' NOT NULL, weights
    JSONB, parameters JSONB, created_by VARCHAR(64), updated_by VARCHAR(64), created_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT
    'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64),
    retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT,
    permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_ranking_configurations
    PRIMARY KEY (id), CONSTRAINT fk_ranking_configurations_updated_by FOREIGN KEY(updated_by)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_configurations_method_resource_id FOREIGN KEY(method_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    ck_ranking_configurations_deletion_state_valid CHECK (deletion_state IN ('active',
    'soft_deleted', 'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    uq_ranking_configurations_scope_scope_id_name UNIQUE (scope, scope_id, name), CONSTRAINT
    fk_ranking_configurations_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON
    DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_ranking_configurations_created_by ON app.ranking_configurations (created_by)
    """,
    """
    CREATE INDEX ix_ranking_configurations_method_resource_id ON app.ranking_configurations
    (method_resource_id)
    """,
    """
    CREATE INDEX ix_ranking_configurations_scope_scope_id ON app.ranking_configurations (scope,
    scope_id)
    """,
    """
    CREATE INDEX ix_ranking_configurations_updated_by ON app.ranking_configurations (updated_by)
    """,
    """
    ALTER TABLE app.ranking_configurations ADD CONSTRAINT ck_ranking_configurations_scope_valid
    CHECK (scope IN ('personal', 'project', 'organization', 'platform'))
    """,
    """
    CREATE TABLE app.reports ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL, title VARCHAR(255) NOT NULL, report_template_id
    VARCHAR(64), state VARCHAR(64) DEFAULT 'draft' NOT NULL, current_version_id VARCHAR(64),
    current_version_number INTEGER DEFAULT '0' NOT NULL, created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state
    VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by
    VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT,
    permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_reports PRIMARY KEY (id),
    CONSTRAINT fk_reports_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_reports_project_id FOREIGN KEY(project_id) REFERENCES app.projects
    (id) ON DELETE RESTRICT, CONSTRAINT fk_reports_workspace_id FOREIGN KEY(workspace_id)
    REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    ck_reports_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT ck_reports_state_valid
    CHECK (state IN ('draft', 'in_review', 'approved', 'finalized', 'superseded', 'withdrawn')),
    CONSTRAINT fk_reports_report_template_id FOREIGN KEY(report_template_id) REFERENCES
    app.report_templates (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_reports_created_by ON app.reports (created_by)
    """,
    """
    CREATE INDEX ix_reports_project_id ON app.reports (project_id)
    """,
    """
    CREATE INDEX ix_reports_report_template_id ON app.reports (report_template_id)
    """,
    """
    CREATE INDEX ix_reports_workspace_id ON app.reports (workspace_id)
    """,
    """
    CREATE INDEX ix_reports_workspace_id_state ON app.reports (workspace_id, state)
    """,
    """
    CREATE TABLE app.resource_assignments ( id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT
    NULL, resource_type VARCHAR(64) NOT NULL, resource_id VARCHAR(64) NOT NULL, assignee_user_id
    VARCHAR(64) NOT NULL, assigned_by VARCHAR(64), state VARCHAR(64) DEFAULT 'active' NOT NULL,
    due_at TIMESTAMP WITH TIME ZONE, metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version
    INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_resource_assignments PRIMARY KEY (id),
    CONSTRAINT fk_resource_assignments_assignee_user_id FOREIGN KEY(assignee_user_id) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_resource_assignments_assigned_by FOREIGN
    KEY(assigned_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_resource_assignments_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT, CONSTRAINT ck_resource_assignments_state_valid CHECK (state IN ('invited',
    'active', 'suspended', 'left', 'removed')) )
    """,
    """
    CREATE INDEX ix_resource_assignments_assigned_by ON app.resource_assignments (assigned_by)
    """,
    """
    CREATE INDEX ix_resource_assignments_assignee_state ON app.resource_assignments
    (assignee_user_id, state)
    """,
    """
    CREATE INDEX ix_resource_assignments_assignee_user_id ON app.resource_assignments
    (assignee_user_id)
    """,
    """
    CREATE INDEX ix_resource_assignments_project_id ON app.resource_assignments (project_id)
    """,
    """
    CREATE INDEX ix_resource_assignments_resource ON app.resource_assignments (resource_type,
    resource_id)
    """,
    """
    CREATE TABLE platform.audit_events ( id VARCHAR(64) NOT NULL, occurred_at TIMESTAMP WITH
    TIME ZONE NOT NULL, action VARCHAR(128) NOT NULL, actor_type VARCHAR(64) NOT NULL,
    actor_user_id VARCHAR(64), actor_service_account_id VARCHAR(64), actor_label VARCHAR(255),
    channel VARCHAR(64) NOT NULL, outcome VARCHAR(64) NOT NULL, resource_type VARCHAR(128),
    resource_id VARCHAR(64), organization_id VARCHAR(64), workspace_id VARCHAR(64), project_id
    VARCHAR(64), previous_state VARCHAR(64), new_state VARCHAR(64), detail JSONB, reason TEXT,
    correlation_id VARCHAR(64), request_ip_hash VARCHAR(128), user_agent_summary VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_audit_events PRIMARY KEY (id), CONSTRAINT
    fk_audit_events_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON
    DELETE RESTRICT, CONSTRAINT ck_audit_events_outcome_valid CHECK (outcome IN ('success',
    'failure', 'denied')), CONSTRAINT fk_audit_events_actor_service_account_id FOREIGN
    KEY(actor_service_account_id) REFERENCES app.service_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT ck_audit_events_actor_type_valid CHECK (actor_type IN ('user', 'service_account',
    'system', 'scheduler', 'worker')), CONSTRAINT ck_audit_events_channel_valid CHECK (channel
    IN ('web', 'api', 'worker', 'scheduler', 'admin', 'system')), CONSTRAINT
    fk_audit_events_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON DELETE
    RESTRICT, CONSTRAINT fk_audit_events_organization_id FOREIGN KEY(organization_id) REFERENCES
    app.organizations (id) ON DELETE RESTRICT, CONSTRAINT fk_audit_events_actor_user_id FOREIGN
    KEY(actor_user_id) REFERENCES app.users (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_audit_events_actor_service_account_id ON platform.audit_events
    (actor_service_account_id)
    """,
    """
    CREATE INDEX ix_audit_events_actor_user_id ON platform.audit_events (actor_user_id)
    """,
    """
    CREATE INDEX ix_audit_events_correlation_id ON platform.audit_events (correlation_id)
    """,
    """
    CREATE INDEX ix_audit_events_occurred_at ON platform.audit_events (occurred_at)
    """,
    """
    CREATE INDEX ix_audit_events_organization_id ON platform.audit_events (organization_id)
    """,
    """
    CREATE INDEX ix_audit_events_organization_id_occurred_at ON platform.audit_events
    (organization_id, occurred_at)
    """,
    """
    CREATE INDEX ix_audit_events_project_id ON platform.audit_events (project_id)
    """,
    """
    CREATE INDEX ix_audit_events_resource_type_resource_id ON platform.audit_events
    (resource_type, resource_id)
    """,
    """
    CREATE INDEX ix_audit_events_workspace_id ON platform.audit_events (workspace_id)
    """,
    """
    CREATE TABLE app.analysis_configurations ( id VARCHAR(64) NOT NULL, analysis_id VARCHAR(64)
    NOT NULL, version_number INTEGER NOT NULL, created_by VARCHAR(64) NOT NULL,
    filtering_configuration JSONB, ranking_configuration JSONB, annotation_configuration JSONB,
    evidence_configuration JSONB, interpretation_configuration JSONB, reporting_configuration
    JSONB, execution_parameters JSONB, pipeline_resource_id VARCHAR(64), engine_resource_id
    VARCHAR(64), reference_genome_resource_id VARCHAR(64), ruleset_resource_id VARCHAR(64),
    execution_profile_resource_id VARCHAR(64), snapshot JSONB, created_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_analysis_configurations PRIMARY KEY (id), CONSTRAINT
    uq_analysis_configurations_analysis_id_version UNIQUE (analysis_id, version_number),
    CONSTRAINT fk_analysis_configurations_pipeline_resource_id FOREIGN KEY(pipeline_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_configurations_ruleset_resource_id FOREIGN KEY(ruleset_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_configurations_analysis_id FOREIGN KEY(analysis_id) REFERENCES app.analyses (id)
    ON DELETE RESTRICT, CONSTRAINT fk_analysis_configurations_engine_resource_id FOREIGN
    KEY(engine_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT fk_analysis_configurations_reference_genome_resource_id FOREIGN
    KEY(reference_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_analysis_configurations_created_by FOREIGN KEY(created_by)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_configurations_execution_profile_resource_id FOREIGN
    KEY(execution_profile_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_analysis_configurations_analysis_id ON app.analysis_configurations
    (analysis_id)
    """,
    """
    CREATE INDEX ix_analysis_configurations_created_by ON app.analysis_configurations
    (created_by)
    """,
    """
    CREATE INDEX ix_analysis_configurations_engine_resource_id ON app.analysis_configurations
    (engine_resource_id)
    """,
    """
    CREATE INDEX ix_analysis_configurations_execution_profile_resource_id ON
    app.analysis_configurations (execution_profile_resource_id)
    """,
    """
    CREATE INDEX ix_analysis_configurations_pipeline_resource_id ON app.analysis_configurations
    (pipeline_resource_id)
    """,
    """
    CREATE INDEX ix_analysis_configurations_reference_genome_resource_id ON
    app.analysis_configurations (reference_genome_resource_id)
    """,
    """
    CREATE INDEX ix_analysis_configurations_ruleset_resource_id ON app.analysis_configurations
    (ruleset_resource_id)
    """,
    """
    CREATE TABLE app.dataset_versions ( id VARCHAR(64) NOT NULL, dataset_id VARCHAR(64) NOT
    NULL, version_number INTEGER NOT NULL, state VARCHAR(64) DEFAULT 'created' NOT NULL,
    created_by VARCHAR(64) NOT NULL, checksum_algorithm VARCHAR(64) DEFAULT 'sha256' NOT NULL,
    checksum_value VARCHAR(256), source_representation JSONB, version_metadata JSONB,
    scientific_metadata JSONB, derived_from_version_id VARCHAR(64), processing_lineage JSONB,
    validated_at TIMESTAMP WITH TIME ZONE, accepted_at TIMESTAMP WITH TIME ZONE, accepted_by
    VARCHAR(64), rejected_at TIMESTAMP WITH TIME ZONE, rejection_reason TEXT,
    superseded_by_version_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, deletion_state VARCHAR(64)
    DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64),
    retention_expires_at TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT,
    permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT pk_dataset_versions PRIMARY KEY
    (id), CONSTRAINT fk_dataset_versions_superseded_by_version_id FOREIGN
    KEY(superseded_by_version_id) REFERENCES app.dataset_versions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_dataset_versions_derived_from_version_id FOREIGN KEY(derived_from_version_id)
    REFERENCES app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_dataset_versions_dataset_id FOREIGN KEY(dataset_id) REFERENCES app.datasets (id) ON
    DELETE RESTRICT, CONSTRAINT uq_dataset_versions_dataset_id_version_number UNIQUE
    (dataset_id, version_number), CONSTRAINT ck_dataset_versions_checksum_algorithm_valid CHECK
    (checksum_algorithm IN ('sha256', 'sha512', 'md5', 'crc32c')), CONSTRAINT
    ck_dataset_versions_state_valid CHECK (state IN ('created', 'uploading', 'validating',
    'validated', 'accepted', 'rejected', 'superseded')), CONSTRAINT
    fk_dataset_versions_accepted_by FOREIGN KEY(accepted_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT ck_dataset_versions_deletion_state_valid CHECK (deletion_state IN
    ('active', 'soft_deleted', 'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    fk_dataset_versions_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_dataset_versions_accepted_by ON app.dataset_versions (accepted_by)
    """,
    """
    CREATE INDEX ix_dataset_versions_created_by ON app.dataset_versions (created_by)
    """,
    """
    CREATE INDEX ix_dataset_versions_dataset_id ON app.dataset_versions (dataset_id)
    """,
    """
    CREATE INDEX ix_dataset_versions_dataset_id_state ON app.dataset_versions (dataset_id,
    state)
    """,
    """
    CREATE INDEX ix_dataset_versions_derived_from_version_id ON app.dataset_versions
    (derived_from_version_id)
    """,
    """
    CREATE INDEX ix_dataset_versions_superseded_by_version_id ON app.dataset_versions
    (superseded_by_version_id)
    """,
    """
    CREATE TABLE app.filter_definition_versions ( id VARCHAR(64) NOT NULL, filter_definition_id
    VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, predicate_tree JSONB, created_by
    VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_filter_definition_versions
    PRIMARY KEY (id), CONSTRAINT fk_filter_definition_versions_created_by FOREIGN
    KEY(created_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_filter_definition_versions_definition_id_version_number UNIQUE (filter_definition_id,
    version_number), CONSTRAINT fk_filter_definition_versions_filter_definition_id FOREIGN
    KEY(filter_definition_id) REFERENCES app.filter_definitions (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_filter_definition_versions_created_by ON app.filter_definition_versions
    (created_by)
    """,
    """
    CREATE INDEX ix_filter_definition_versions_filter_definition_id ON
    app.filter_definition_versions (filter_definition_id)
    """,
    """
    CREATE TABLE app.notification_deliveries ( id VARCHAR(64) NOT NULL, notification_id
    VARCHAR(64) NOT NULL, channel VARCHAR(64) NOT NULL, state VARCHAR(64) DEFAULT 'pending' NOT
    NULL, attempt_number INTEGER DEFAULT '1' NOT NULL, job_id VARCHAR(64), dispatched_at
    TIMESTAMP WITH TIME ZONE, delivered_at TIMESTAMP WITH TIME ZONE, failure_code VARCHAR(128),
    failure_message TEXT, provider_reference VARCHAR(255), created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_notification_deliveries PRIMARY KEY (id), CONSTRAINT
    fk_notification_deliveries_notification_id FOREIGN KEY(notification_id) REFERENCES
    app.notifications (id) ON DELETE CASCADE, CONSTRAINT
    ck_notification_deliveries_channel_valid CHECK (channel IN ('in_app', 'email', 'webhook')),
    CONSTRAINT uq_notification_deliveries_notification_channel_attempt UNIQUE (notification_id,
    channel, attempt_number), CONSTRAINT ck_notification_deliveries_state_valid CHECK (state IN
    ('pending', 'sending', 'delivered', 'failed', 'suppressed')) )
    """,
    """
    CREATE INDEX ix_notification_deliveries_notification_id ON app.notification_deliveries
    (notification_id)
    """,
    """
    CREATE INDEX ix_notification_deliveries_state ON app.notification_deliveries (state)
    """,
    """
    CREATE TABLE app.ranking_configuration_versions ( id VARCHAR(64) NOT NULL,
    ranking_configuration_id VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, method_key
    VARCHAR(128) NOT NULL, method_version VARCHAR(128), weights JSONB, parameters JSONB,
    created_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_ranking_configuration_versions PRIMARY KEY (id), CONSTRAINT
    fk_ranking_configuration_versions_created_by FOREIGN KEY(created_by) REFERENCES app.users
    (id) ON DELETE RESTRICT, CONSTRAINT
    fk_ranking_configuration_versions_ranking_configuration_id FOREIGN
    KEY(ranking_configuration_id) REFERENCES app.ranking_configurations (id) ON DELETE CASCADE,
    CONSTRAINT uq_ranking_configuration_versions_configuration_id_version UNIQUE
    (ranking_configuration_id, version_number) )
    """,
    """
    CREATE INDEX ix_ranking_configuration_versions_created_by ON
    app.ranking_configuration_versions (created_by)
    """,
    """
    CREATE INDEX ix_ranking_configuration_versions_ranking_configuration_id ON
    app.ranking_configuration_versions (ranking_configuration_id)
    """,
    """
    CREATE TABLE app.saved_views ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL, scope
    VARCHAR(64) NOT NULL, scope_id VARCHAR(64), filter_definition_id VARCHAR(64),
    ranking_configuration_id VARCHAR(64), column_layout JSONB, sort_specification JSONB,
    created_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT
    NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME
    ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE,
    deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_saved_views PRIMARY KEY (id), CONSTRAINT fk_saved_views_created_by FOREIGN
    KEY(created_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_saved_views_scope_scope_id_name UNIQUE (scope, scope_id, name), CONSTRAINT
    fk_saved_views_filter_definition_id FOREIGN KEY(filter_definition_id) REFERENCES
    app.filter_definitions (id) ON DELETE RESTRICT, CONSTRAINT
    ck_saved_views_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    fk_saved_views_ranking_configuration_id FOREIGN KEY(ranking_configuration_id) REFERENCES
    app.ranking_configurations (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_saved_views_created_by ON app.saved_views (created_by)
    """,
    """
    CREATE INDEX ix_saved_views_filter_definition_id ON app.saved_views (filter_definition_id)
    """,
    """
    CREATE INDEX ix_saved_views_ranking_configuration_id ON app.saved_views
    (ranking_configuration_id)
    """,
    """
    ALTER TABLE app.saved_views ADD CONSTRAINT ck_saved_views_scope_valid CHECK (scope IN
    ('personal', 'project', 'organization', 'platform'))
    """,
    """
    CREATE TABLE app.analysis_configuration_inputs ( id VARCHAR(64) NOT NULL,
    analysis_configuration_id VARCHAR(64) NOT NULL, dataset_version_id VARCHAR(64) NOT NULL,
    role VARCHAR(64) NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_analysis_configuration_inputs PRIMARY KEY (id), CONSTRAINT
    fk_analysis_configuration_inputs_dataset_version_id FOREIGN KEY(dataset_version_id)
    REFERENCES app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_configuration_inputs_analysis_configuration_id FOREIGN
    KEY(analysis_configuration_id) REFERENCES app.analysis_configurations (id) ON DELETE
    CASCADE, CONSTRAINT uq_analysis_configuration_inputs_configuration_version_role UNIQUE
    (analysis_configuration_id, dataset_version_id, role) )
    """,
    """
    CREATE INDEX ix_analysis_configuration_inputs_analysis_configuration_id ON
    app.analysis_configuration_inputs (analysis_configuration_id)
    """,
    """
    CREATE INDEX ix_analysis_configuration_inputs_dataset_version_id ON
    app.analysis_configuration_inputs (dataset_version_id)
    """,
    """
    CREATE TABLE app.analysis_executions ( id VARCHAR(64) NOT NULL, analysis_id VARCHAR(64) NOT
    NULL, workspace_id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT NULL,
    analysis_configuration_id VARCHAR(64) NOT NULL, configuration_snapshot JSONB,
    attempt_sequence INTEGER NOT NULL, state VARCHAR(64) DEFAULT 'requested' NOT NULL,
    requested_by VARCHAR(64), requested_at TIMESTAMP WITH TIME ZONE NOT NULL, started_at
    TIMESTAMP WITH TIME ZONE, completed_at TIMESTAMP WITH TIME ZONE, correlation_id VARCHAR(64)
    NOT NULL, execution_environment JSONB, resource_profile JSONB, scientific_versions JSONB,
    failure_code VARCHAR(128), failure_message TEXT, failure_details JSONB, scheduled_job_id
    VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_analysis_executions PRIMARY
    KEY (id), CONSTRAINT fk_analysis_executions_analysis_id FOREIGN KEY(analysis_id) REFERENCES
    app.analyses (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_executions_analysis_configuration_id FOREIGN KEY(analysis_configuration_id)
    REFERENCES app.analysis_configurations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_executions_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id)
    ON DELETE RESTRICT, CONSTRAINT uq_analysis_executions_analysis_id_attempt UNIQUE
    (analysis_id, attempt_sequence), CONSTRAINT fk_analysis_executions_requested_by FOREIGN
    KEY(requested_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_analysis_executions_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_analysis_executions_analysis_configuration_id ON app.analysis_executions
    (analysis_configuration_id)
    """,
    """
    CREATE INDEX ix_analysis_executions_analysis_id ON app.analysis_executions (analysis_id)
    """,
    """
    CREATE INDEX ix_analysis_executions_correlation_id ON app.analysis_executions
    (correlation_id)
    """,
    """
    CREATE INDEX ix_analysis_executions_project_id ON app.analysis_executions (project_id)
    """,
    """
    CREATE INDEX ix_analysis_executions_requested_at ON app.analysis_executions (requested_at)
    """,
    """
    CREATE INDEX ix_analysis_executions_requested_by ON app.analysis_executions (requested_by)
    """,
    """
    CREATE INDEX ix_analysis_executions_workspace_id ON app.analysis_executions (workspace_id)
    """,
    """
    CREATE INDEX ix_analysis_executions_workspace_id_state ON app.analysis_executions
    (workspace_id, state)
    """,
    """
    ALTER TABLE app.analysis_executions ADD CONSTRAINT ck_analysis_executions_state_valid CHECK
    (state IN ('requested', 'queued', 'running', 'succeeded', 'failed', 'cancelled',
    'timed_out'))
    """,
    """
    CREATE TABLE app.file_artifacts ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, dataset_id VARCHAR(64), dataset_version_id VARCHAR(64), storage_provider VARCHAR(64)
    NOT NULL, storage_bucket VARCHAR(255) NOT NULL, storage_key TEXT NOT NULL, filename
    VARCHAR(512) NOT NULL, content_type VARCHAR(255), size_bytes BIGINT, checksum_algorithm
    VARCHAR(64) DEFAULT 'sha256' NOT NULL, checksum_value VARCHAR(256), upload_state VARCHAR(64)
    DEFAULT 'pending' NOT NULL, validation_state VARCHAR(64) DEFAULT 'not_validated' NOT NULL,
    quarantined_at TIMESTAMP WITH TIME ZONE, quarantine_reason TEXT, uploaded_by VARCHAR(64) NOT
    NULL, uploaded_at TIMESTAMP WITH TIME ZONE, metadata_json JSONB, created_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, version INTEGER DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT
    NULL, deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at
    TIMESTAMP WITH TIME ZONE, deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH
    TIME ZONE, CONSTRAINT pk_file_artifacts PRIMARY KEY (id), CONSTRAINT
    ck_file_artifacts_checksum_algorithm_valid CHECK (checksum_algorithm IN ('sha256', 'sha512',
    'md5', 'crc32c')), CONSTRAINT ck_file_artifacts_validation_state_valid CHECK
    (validation_state IN ('not_validated', 'validating', 'valid', 'invalid', 'quarantined')),
    CONSTRAINT fk_file_artifacts_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT fk_file_artifacts_workspace_id
    FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    ck_file_artifacts_deletion_state_valid CHECK (deletion_state IN ('active', 'soft_deleted',
    'retention', 'purge_pending', 'permanently_deleted')), CONSTRAINT
    uq_file_artifacts_storage_provider_storage_bucket_storage_key UNIQUE (storage_provider,
    storage_bucket, storage_key), CONSTRAINT fk_file_artifacts_uploaded_by FOREIGN
    KEY(uploaded_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_file_artifacts_dataset_id FOREIGN KEY(dataset_id) REFERENCES app.datasets (id) ON DELETE
    RESTRICT, CONSTRAINT ck_file_artifacts_upload_state_valid CHECK (upload_state IN ('pending',
    'in_progress', 'uploaded', 'failed', 'aborted')) )
    """,
    """
    CREATE INDEX ix_file_artifacts_dataset_id ON app.file_artifacts (dataset_id)
    """,
    """
    CREATE INDEX ix_file_artifacts_dataset_version_id ON app.file_artifacts (dataset_version_id)
    """,
    """
    CREATE INDEX ix_file_artifacts_dataset_version_id_upload_state ON app.file_artifacts
    (dataset_version_id, upload_state)
    """,
    """
    CREATE INDEX ix_file_artifacts_uploaded_by ON app.file_artifacts (uploaded_by)
    """,
    """
    CREATE INDEX ix_file_artifacts_workspace_id ON app.file_artifacts (workspace_id)
    """,
    """
    CREATE TABLE app.samples ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
    dataset_id VARCHAR(64) NOT NULL, dataset_version_id VARCHAR(64) NOT NULL, sample_key
    VARCHAR(255) NOT NULL, display_label VARCHAR(255), sex_karyotype VARCHAR(32),
    source_metadata JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_samples PRIMARY
    KEY (id), CONSTRAINT fk_samples_dataset_id FOREIGN KEY(dataset_id) REFERENCES app.datasets
    (id) ON DELETE RESTRICT, CONSTRAINT uq_samples_dataset_version_id_sample_key UNIQUE
    (dataset_version_id, sample_key), CONSTRAINT fk_samples_dataset_version_id FOREIGN
    KEY(dataset_version_id) REFERENCES app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_samples_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_samples_dataset_id ON app.samples (dataset_id)
    """,
    """
    CREATE INDEX ix_samples_dataset_version_id ON app.samples (dataset_version_id)
    """,
    """
    CREATE INDEX ix_samples_workspace_id ON app.samples (workspace_id)
    """,
    """
    CREATE TABLE platform.scheduled_jobs ( id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL,
    owner_scope VARCHAR(64) NOT NULL, owner_id VARCHAR(64), job_kind VARCHAR(64) NOT NULL,
    analysis_id VARCHAR(64), analysis_configuration_id VARCHAR(64), state VARCHAR(64) DEFAULT
    'disabled' NOT NULL, schedule_configuration JSONB, next_execution_at TIMESTAMP WITH TIME
    ZONE, previous_execution_at TIMESTAMP WITH TIME ZONE, previous_job_id VARCHAR(64),
    created_by VARCHAR(64), updated_by VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER
    DEFAULT '1' NOT NULL, CONSTRAINT pk_scheduled_jobs PRIMARY KEY (id), CONSTRAINT
    fk_scheduled_jobs_analysis_configuration_id FOREIGN KEY(analysis_configuration_id)
    REFERENCES app.analysis_configurations (id) ON DELETE RESTRICT, CONSTRAINT
    ck_scheduled_jobs_state_valid CHECK (state IN ('enabled', 'disabled', 'archived')),
    CONSTRAINT fk_scheduled_jobs_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_scheduled_jobs_analysis_id FOREIGN KEY(analysis_id)
    REFERENCES app.analyses (id) ON DELETE RESTRICT, CONSTRAINT
    uq_scheduled_jobs_owner_scope_owner_id_name UNIQUE (owner_scope, owner_id, name), CONSTRAINT
    fk_scheduled_jobs_updated_by FOREIGN KEY(updated_by) REFERENCES app.users (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_scheduled_jobs_analysis_configuration_id ON platform.scheduled_jobs
    (analysis_configuration_id)
    """,
    """
    CREATE INDEX ix_scheduled_jobs_analysis_id ON platform.scheduled_jobs (analysis_id)
    """,
    """
    CREATE INDEX ix_scheduled_jobs_created_by ON platform.scheduled_jobs (created_by)
    """,
    """
    CREATE INDEX ix_scheduled_jobs_state_next_execution_at ON platform.scheduled_jobs (state,
    next_execution_at)
    """,
    """
    CREATE INDEX ix_scheduled_jobs_updated_by ON platform.scheduled_jobs (updated_by)
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD CONSTRAINT ck_scheduled_jobs_job_kind_valid CHECK
    (job_kind IN ('analysis_execution', 'dataset_import', 'dataset_validation',
    'scientific_execution', 'export', 'report_generation', 'notification_delivery', 'retention',
    'maintenance', 'schedule_trigger', 'stale_recovery', 'result_ingestion', 'variant_query',
    'annotation_execution', 'annotation_ingestion', 'classification_evaluation',
    'classification_ingestion'))
    """,
    """
    CREATE TABLE app.analysis_execution_inputs ( id VARCHAR(64) NOT NULL, analysis_execution_id
    VARCHAR(64) NOT NULL, dataset_version_id VARCHAR(64) NOT NULL, role VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_analysis_execution_inputs PRIMARY KEY (id),
    CONSTRAINT fk_analysis_execution_inputs_analysis_execution_id FOREIGN
    KEY(analysis_execution_id) REFERENCES app.analysis_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_analysis_execution_inputs_dataset_version_id FOREIGN KEY(dataset_version_id)
    REFERENCES app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    uq_analysis_execution_inputs_execution_version_role UNIQUE (analysis_execution_id,
    dataset_version_id, role) )
    """,
    """
    CREATE INDEX ix_analysis_execution_inputs_analysis_execution_id ON
    app.analysis_execution_inputs (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_analysis_execution_inputs_dataset_version_id ON
    app.analysis_execution_inputs (dataset_version_id)
    """,
    """
    CREATE TABLE app.import_sessions ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, project_id VARCHAR(64), dataset_id VARCHAR(64), dataset_version_id VARCHAR(64), state
    VARCHAR(64) DEFAULT 'open' NOT NULL, initiated_by VARCHAR(64) NOT NULL, mapping_metadata
    JSONB, import_provenance JSONB, submitted_at TIMESTAMP WITH TIME ZONE, decided_at TIMESTAMP
    WITH TIME ZONE, decided_by VARCHAR(64), rejection_reason TEXT, created_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_import_sessions PRIMARY KEY (id),
    CONSTRAINT fk_import_sessions_dataset_id FOREIGN KEY(dataset_id) REFERENCES app.datasets
    (id) ON DELETE RESTRICT, CONSTRAINT fk_import_sessions_workspace_id FOREIGN
    KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    ck_import_sessions_state_valid CHECK (state IN ('open', 'submitted', 'validating',
    'accepted', 'rejected', 'abandoned')), CONSTRAINT fk_import_sessions_dataset_version_id
    FOREIGN KEY(dataset_version_id) REFERENCES app.dataset_versions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_import_sessions_project_id FOREIGN KEY(project_id) REFERENCES app.projects
    (id) ON DELETE RESTRICT, CONSTRAINT fk_import_sessions_decided_by FOREIGN KEY(decided_by)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_import_sessions_initiated_by
    FOREIGN KEY(initiated_by) REFERENCES app.users (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_import_sessions_dataset_id ON app.import_sessions (dataset_id)
    """,
    """
    CREATE INDEX ix_import_sessions_dataset_version_id ON app.import_sessions
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_import_sessions_decided_by ON app.import_sessions (decided_by)
    """,
    """
    CREATE INDEX ix_import_sessions_initiated_by ON app.import_sessions (initiated_by)
    """,
    """
    CREATE INDEX ix_import_sessions_project_id ON app.import_sessions (project_id)
    """,
    """
    CREATE INDEX ix_import_sessions_workspace_id ON app.import_sessions (workspace_id)
    """,
    """
    CREATE INDEX ix_import_sessions_workspace_id_state ON app.import_sessions (workspace_id,
    state)
    """,
    """
    CREATE TABLE app.scientific_executions ( id VARCHAR(64) NOT NULL, analysis_execution_id
    VARCHAR(64), job_id VARCHAR(64), external_execution_id VARCHAR(255), capability_key
    VARCHAR(128) NOT NULL, capability_version VARCHAR(128), engine_resource_id VARCHAR(64),
    engine_version VARCHAR(128), environment_resource_id VARCHAR(64), environment_version
    VARCHAR(128), container_image_digest VARCHAR(255), node_identity VARCHAR(255),
    reference_genome_resource_id VARCHAR(64), ruleset_resource_id VARCHAR(64),
    resource_identities JSONB, parameters JSONB, state VARCHAR(64) DEFAULT 'submitted' NOT NULL,
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL, started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE, correlation_id VARCHAR(64) NOT NULL,
    provenance_manifest_id VARCHAR(64), failure_code VARCHAR(128), failure_message TEXT,
    failure_details JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_scientific_executions PRIMARY KEY (id), CONSTRAINT
    fk_scientific_executions_ruleset_resource_id FOREIGN KEY(ruleset_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_scientific_executions_environment_resource_id FOREIGN KEY(environment_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_scientific_executions_analysis_execution_id FOREIGN KEY(analysis_execution_id) REFERENCES
    app.analysis_executions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_scientific_executions_reference_genome_resource_id FOREIGN
    KEY(reference_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_scientific_executions_engine_resource_id FOREIGN
    KEY(engine_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT ck_scientific_executions_state_valid CHECK (state IN ('submitted', 'accepted',
    'running', 'succeeded', 'failed', 'rejected', 'cancelled')) )
    """,
    """
    CREATE INDEX ix_scientific_executions_analysis_execution_id ON app.scientific_executions
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_scientific_executions_correlation_id ON app.scientific_executions
    (correlation_id)
    """,
    """
    CREATE INDEX ix_scientific_executions_engine_resource_id ON app.scientific_executions
    (engine_resource_id)
    """,
    """
    CREATE INDEX ix_scientific_executions_environment_resource_id ON app.scientific_executions
    (environment_resource_id)
    """,
    """
    CREATE INDEX ix_scientific_executions_reference_genome_resource_id ON
    app.scientific_executions (reference_genome_resource_id)
    """,
    """
    CREATE INDEX ix_scientific_executions_ruleset_resource_id ON app.scientific_executions
    (ruleset_resource_id)
    """,
    """
    CREATE INDEX ix_scientific_executions_state_submitted_at ON app.scientific_executions
    (state, submitted_at)
    """,
    """
    CREATE TABLE platform.jobs ( id VARCHAR(64) NOT NULL, kind VARCHAR(64) NOT NULL, state
    VARCHAR(64) DEFAULT 'pending' NOT NULL, queue VARCHAR(64) DEFAULT 'default' NOT NULL,
    priority INTEGER DEFAULT '100' NOT NULL, analysis_execution_id VARCHAR(64),
    scientific_execution_id VARCHAR(64), scheduled_job_id VARCHAR(64), workspace_id VARCHAR(64),
    project_id VARCHAR(64), payload JSONB, execution_context_ref VARCHAR(128), requested_by
    VARCHAR(64), idempotency_key VARCHAR(255), attempt_number INTEGER DEFAULT '0' NOT NULL,
    max_attempts INTEGER DEFAULT '3' NOT NULL, available_at TIMESTAMP WITH TIME ZONE, claimed_at
    TIMESTAMP WITH TIME ZONE, claimed_by_worker_id VARCHAR(128), assigned_node_id VARCHAR(128),
    lease_expires_at TIMESTAMP WITH TIME ZONE, heartbeat_at TIMESTAMP WITH TIME ZONE, started_at
    TIMESTAMP WITH TIME ZONE, completed_at TIMESTAMP WITH TIME ZONE, cancellation_requested_at
    TIMESTAMP WITH TIME ZONE, cancellation_requested_by VARCHAR(64), progress_percent INTEGER,
    progress_message TEXT, failure_code VARCHAR(128), failure_message TEXT, failure_details
    JSONB, correlation_id VARCHAR(64) NOT NULL, causation_id VARCHAR(64), created_at TIMESTAMP
    WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_jobs PRIMARY KEY (id), CONSTRAINT
    fk_jobs_requested_by FOREIGN KEY(requested_by) REFERENCES app.users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_jobs_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON
    DELETE RESTRICT, CONSTRAINT uq_jobs_idempotency_key UNIQUE (idempotency_key), CONSTRAINT
    fk_jobs_cancellation_requested_by FOREIGN KEY(cancellation_requested_by) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_jobs_project_id FOREIGN KEY(project_id)
    REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT fk_jobs_analysis_execution_id
    FOREIGN KEY(analysis_execution_id) REFERENCES app.analysis_executions (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_jobs_analysis_execution_id ON platform.jobs (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_jobs_cancellation_requested_by ON platform.jobs (cancellation_requested_by)
    """,
    """
    CREATE INDEX ix_jobs_correlation_id ON platform.jobs (correlation_id)
    """,
    """
    CREATE INDEX ix_jobs_project_id ON platform.jobs (project_id)
    """,
    """
    CREATE INDEX ix_jobs_queue_state_priority_available_at ON platform.jobs (queue, state,
    priority, available_at)
    """,
    """
    CREATE INDEX ix_jobs_requested_by ON platform.jobs (requested_by)
    """,
    """
    CREATE INDEX ix_jobs_state_lease_expires_at ON platform.jobs (state, lease_expires_at)
    """,
    """
    CREATE INDEX ix_jobs_workspace_id ON platform.jobs (workspace_id)
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_state_valid CHECK (state IN ('pending',
    'queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelling', 'cancelled',
    'dead_letter'))
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
    CREATE TABLE app.provenance_manifests ( id VARCHAR(64) NOT NULL, analysis_execution_id
    VARCHAR(64), scientific_execution_id VARCHAR(64), recorded_at TIMESTAMP WITH TIME ZONE NOT
    NULL, correlation_id VARCHAR(64) NOT NULL, manifest JSONB, manifest_digest VARCHAR(256),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_provenance_manifests PRIMARY KEY (id), CONSTRAINT
    uq_provenance_manifests_scientific_execution_id UNIQUE (scientific_execution_id), CONSTRAINT
    fk_provenance_manifests_scientific_execution_id FOREIGN KEY(scientific_execution_id)
    REFERENCES app.scientific_executions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_provenance_manifests_analysis_execution_id FOREIGN KEY(analysis_execution_id) REFERENCES
    app.analysis_executions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_provenance_manifests_analysis_execution_id ON app.provenance_manifests
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_provenance_manifests_correlation_id ON app.provenance_manifests
    (correlation_id)
    """,
    """
    CREATE INDEX ix_provenance_manifests_scientific_execution_id ON app.provenance_manifests
    (scientific_execution_id)
    """,
    """
    CREATE TABLE app.scientific_artifacts ( id VARCHAR(64) NOT NULL, scientific_execution_id
    VARCHAR(64) NOT NULL, artifact_key VARCHAR(255) NOT NULL, artifact_kind VARCHAR(64) NOT
    NULL, file_artifact_id VARCHAR(64), analytical_location TEXT, content_type VARCHAR(255),
    size_bytes BIGINT, checksum_algorithm VARCHAR(64), checksum_value VARCHAR(256),
    metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_scientific_artifacts PRIMARY
    KEY (id), CONSTRAINT fk_scientific_artifacts_file_artifact_id FOREIGN KEY(file_artifact_id)
    REFERENCES app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT
    uq_scientific_artifacts_scientific_execution_id_artifact_key UNIQUE
    (scientific_execution_id, artifact_key), CONSTRAINT
    ck_scientific_artifacts_checksum_algorithm_valid CHECK (checksum_algorithm IN ('sha256',
    'sha512', 'md5', 'crc32c')), CONSTRAINT fk_scientific_artifacts_scientific_execution_id
    FOREIGN KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_scientific_artifacts_artifact_kind ON app.scientific_artifacts
    (artifact_kind)
    """,
    """
    CREATE INDEX ix_scientific_artifacts_file_artifact_id ON app.scientific_artifacts
    (file_artifact_id)
    """,
    """
    CREATE INDEX ix_scientific_artifacts_scientific_execution_id ON app.scientific_artifacts
    (scientific_execution_id)
    """,
    """
    CREATE TABLE app.validation_runs ( id VARCHAR(64) NOT NULL, import_session_id VARCHAR(64),
    dataset_version_id VARCHAR(64), file_artifact_id VARCHAR(64), state VARCHAR(64) DEFAULT
    'pending' NOT NULL, requested_by VARCHAR(64), correlation_id VARCHAR(64), started_at
    TIMESTAMP WITH TIME ZONE, completed_at TIMESTAMP WITH TIME ZONE, blocking_issue_count
    INTEGER DEFAULT '0' NOT NULL, error_issue_count INTEGER DEFAULT '0' NOT NULL,
    warning_issue_count INTEGER DEFAULT '0' NOT NULL, info_issue_count INTEGER DEFAULT '0' NOT
    NULL, summary JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_validation_runs PRIMARY KEY
    (id), CONSTRAINT ck_validation_runs_state_valid CHECK (state IN ('pending', 'running',
    'passed', 'passed_with_warnings', 'failed', 'errored')), CONSTRAINT
    fk_validation_runs_file_artifact_id FOREIGN KEY(file_artifact_id) REFERENCES
    app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT fk_validation_runs_requested_by
    FOREIGN KEY(requested_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_validation_runs_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_validation_runs_import_session_id FOREIGN KEY(import_session_id) REFERENCES
    app.import_sessions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_validation_runs_correlation_id ON app.validation_runs (correlation_id)
    """,
    """
    CREATE INDEX ix_validation_runs_dataset_version_id ON app.validation_runs
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_validation_runs_dataset_version_id_state ON app.validation_runs
    (dataset_version_id, state)
    """,
    """
    CREATE INDEX ix_validation_runs_file_artifact_id ON app.validation_runs (file_artifact_id)
    """,
    """
    CREATE INDEX ix_validation_runs_import_session_id ON app.validation_runs (import_session_id)
    """,
    """
    CREATE INDEX ix_validation_runs_requested_by ON app.validation_runs (requested_by)
    """,
    """
    CREATE TABLE app.variants ( id VARCHAR(64) NOT NULL, reference_genome_resource_id
    VARCHAR(64) NOT NULL, contig VARCHAR(64) NOT NULL, position BIGINT NOT NULL, end_position
    BIGINT, reference_allele TEXT NOT NULL, alternate_allele TEXT NOT NULL, variant_class
    VARCHAR(64) NOT NULL, symbolic_allele VARCHAR(64), structural_variant_type VARCHAR(64),
    normalization_state VARCHAR(64) DEFAULT 'not_normalized' NOT NULL, normalization_version
    VARCHAR(128) NOT NULL, normalization_engine_resource_id VARCHAR(64), canonical_key TEXT NOT
    NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_variants PRIMARY KEY (id), CONSTRAINT
    fk_variants_normalization_engine_resource_id FOREIGN KEY(normalization_engine_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variants_reference_genome_resource_id FOREIGN KEY(reference_genome_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    ck_variants_variant_class_valid CHECK (variant_class IN ('snv', 'mnv', 'insertion',
    'deletion', 'indel', 'symbolic', 'structural', 'copy_number', 'complex', 'unknown')),
    CONSTRAINT uq_variants_canonical_identity UNIQUE (reference_genome_resource_id, contig,
    position, reference_allele, alternate_allele, normalization_version) )
    """,
    """
    CREATE INDEX ix_variants_canonical_key ON app.variants (canonical_key)
    """,
    """
    CREATE INDEX ix_variants_contig_position ON app.variants (contig, position)
    """,
    """
    CREATE INDEX ix_variants_normalization_engine_resource_id ON app.variants
    (normalization_engine_resource_id)
    """,
    """
    CREATE INDEX ix_variants_reference_genome_resource_id ON app.variants
    (reference_genome_resource_id)
    """,
    """
    ALTER TABLE app.variants ADD CONSTRAINT ck_variants_normalization_state_valid CHECK
    (normalization_state IN ('not_normalized', 'normalized', 'normalization_failed'))
    """,
    """
    CREATE TABLE platform.job_attempts ( id VARCHAR(64) NOT NULL, job_id VARCHAR(64) NOT NULL,
    attempt_number INTEGER NOT NULL, state VARCHAR(64) NOT NULL, worker_id VARCHAR(128),
    started_at TIMESTAMP WITH TIME ZONE, finished_at TIMESTAMP WITH TIME ZONE, failure_code
    VARCHAR(128), failure_message TEXT, diagnostics JSONB, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_job_attempts PRIMARY KEY (id), CONSTRAINT fk_job_attempts_job_id FOREIGN
    KEY(job_id) REFERENCES platform.jobs (id) ON DELETE CASCADE, CONSTRAINT
    uq_job_attempts_job_id_attempt_number UNIQUE (job_id, attempt_number) )
    """,
    """
    CREATE INDEX ix_job_attempts_job_id ON platform.job_attempts (job_id)
    """,
    """
    ALTER TABLE platform.job_attempts ADD CONSTRAINT ck_job_attempts_state_valid CHECK (state IN
    ('pending', 'queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelling',
    'cancelled', 'dead_letter'))
    """,
    """
    CREATE TABLE app.clinical_assertions ( id VARCHAR(64) NOT NULL, variant_id VARCHAR(64) NOT
    NULL, source_id VARCHAR(64) NOT NULL, external_record_identifier VARCHAR(255) NOT NULL,
    reported_classification VARCHAR(255), condition_term VARCHAR(512), condition_identifier
    VARCHAR(128), assertion_statement TEXT, review_status_text VARCHAR(255), submitter
    VARCHAR(255), conflict_information JSONB, assertion_payload JSONB, origin VARCHAR(64)
    DEFAULT 'retrieved' NOT NULL, retrieved_at TIMESTAMP WITH TIME ZONE, provenance JSONB,
    record_count INTEGER, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_clinical_assertions PRIMARY
    KEY (id), CONSTRAINT ck_clinical_assertions_origin_valid CHECK (origin IN ('imported',
    'retrieved', 'generated', 'machine_generated', 'human_entered', 'human_evaluated')),
    CONSTRAINT fk_clinical_assertions_variant_id FOREIGN KEY(variant_id) REFERENCES app.variants
    (id) ON DELETE RESTRICT, CONSTRAINT uq_clinical_assertions_identity UNIQUE (source_id,
    external_record_identifier, variant_id), CONSTRAINT fk_clinical_assertions_source_id FOREIGN
    KEY(source_id) REFERENCES app.external_assertion_sources (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_clinical_assertions_external_record_identifier ON app.clinical_assertions
    (external_record_identifier)
    """,
    """
    CREATE INDEX ix_clinical_assertions_source_id ON app.clinical_assertions (source_id)
    """,
    """
    CREATE INDEX ix_clinical_assertions_variant_id ON app.clinical_assertions (variant_id)
    """,
    """
    CREATE TABLE app.criterion_evaluations ( id VARCHAR(64) NOT NULL, variant_id VARCHAR(64) NOT
    NULL, interpretation_id VARCHAR(64), interpretation_version_id VARCHAR(64),
    ruleset_resource_id VARCHAR(64) NOT NULL, ruleset_version VARCHAR(128) NOT NULL,
    criterion_key VARCHAR(64) NOT NULL, applied BOOLEAN DEFAULT 'false' NOT NULL, strength
    VARCHAR(64) DEFAULT 'not_applicable' NOT NULL, direction VARCHAR(64) DEFAULT 'neutral' NOT
    NULL, rationale TEXT, origin VARCHAR(64) NOT NULL, evaluated_by_user_id VARCHAR(64),
    evaluation_method VARCHAR(128), scientific_execution_id VARCHAR(64), evaluated_at TIMESTAMP
    WITH TIME ZONE NOT NULL, supersedes_evaluation_id VARCHAR(64), is_override BOOLEAN DEFAULT
    'false' NOT NULL, override_reason TEXT, details JSONB, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version
    INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_criterion_evaluations PRIMARY KEY (id),
    CONSTRAINT fk_criterion_evaluations_evaluated_by_user_id FOREIGN KEY(evaluated_by_user_id)
    REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_criterion_evaluations_variant_id
    FOREIGN KEY(variant_id) REFERENCES app.variants (id) ON DELETE RESTRICT, CONSTRAINT
    ck_criterion_evaluations_strength_valid CHECK (strength IN ('standalone', 'very_strong',
    'strong', 'moderate', 'supporting', 'not_applicable')), CONSTRAINT
    ck_criterion_evaluations_direction_valid CHECK (direction IN ('pathogenic', 'benign',
    'neutral')), CONSTRAINT fk_criterion_evaluations_scientific_execution_id FOREIGN
    KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE RESTRICT,
    CONSTRAINT ck_criterion_evaluations_origin_valid CHECK (origin IN ('imported', 'retrieved',
    'generated', 'machine_generated', 'human_entered', 'human_evaluated')), CONSTRAINT
    fk_criterion_evaluations_ruleset_resource_id FOREIGN KEY(ruleset_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_criterion_evaluations_criterion_key ON app.criterion_evaluations
    (criterion_key)
    """,
    """
    CREATE INDEX ix_criterion_evaluations_evaluated_by_user_id ON app.criterion_evaluations
    (evaluated_by_user_id)
    """,
    """
    CREATE INDEX ix_criterion_evaluations_interpretation_id ON app.criterion_evaluations
    (interpretation_id)
    """,
    """
    CREATE INDEX ix_criterion_evaluations_ruleset_resource_id ON app.criterion_evaluations
    (ruleset_resource_id)
    """,
    """
    CREATE INDEX ix_criterion_evaluations_scientific_execution_id ON app.criterion_evaluations
    (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_criterion_evaluations_variant_id ON app.criterion_evaluations (variant_id)
    """,
    """
    CREATE TABLE app.interpretations ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, project_id VARCHAR(64) NOT NULL, variant_id VARCHAR(64) NOT NULL, sample_id
    VARCHAR(64), condition_identifier VARCHAR(128), condition_term VARCHAR(512), state
    VARCHAR(64) DEFAULT 'draft' NOT NULL, review_state VARCHAR(64) DEFAULT 'not_started' NOT
    NULL, current_version_id VARCHAR(64), current_version_number INTEGER DEFAULT '0' NOT NULL,
    created_by VARCHAR(64) NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT
    NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at TIMESTAMP WITH TIME
    ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME ZONE,
    deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_interpretations PRIMARY KEY (id), CONSTRAINT ck_interpretations_deletion_state_valid
    CHECK (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')), CONSTRAINT fk_interpretations_sample_id FOREIGN KEY(sample_id)
    REFERENCES app.samples (id) ON DELETE RESTRICT, CONSTRAINT fk_interpretations_project_id
    FOREIGN KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT, CONSTRAINT
    ck_interpretations_state_valid CHECK (state IN ('draft', 'automated', 'in_review',
    'adjudication', 'approved', 'finalized', 'superseded', 'withdrawn')), CONSTRAINT
    ck_interpretations_review_state_valid CHECK (review_state IN ('not_started', 'assigned',
    'in_progress', 'submitted', 'accepted', 'rejected', 'escalated', 'withdrawn')), CONSTRAINT
    fk_interpretations_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_interpretations_variant_id FOREIGN KEY(variant_id) REFERENCES
    app.variants (id) ON DELETE RESTRICT, CONSTRAINT fk_interpretations_workspace_id FOREIGN
    KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_interpretations_created_by ON app.interpretations (created_by)
    """,
    """
    CREATE INDEX ix_interpretations_project_id ON app.interpretations (project_id)
    """,
    """
    CREATE INDEX ix_interpretations_sample_id ON app.interpretations (sample_id)
    """,
    """
    CREATE INDEX ix_interpretations_variant_id ON app.interpretations (variant_id)
    """,
    """
    CREATE INDEX ix_interpretations_workspace_id ON app.interpretations (workspace_id)
    """,
    """
    CREATE INDEX ix_interpretations_workspace_id_state ON app.interpretations (workspace_id,
    state)
    """,
    """
    CREATE TABLE app.population_frequency_observations ( id VARCHAR(64) NOT NULL, variant_id
    VARCHAR(64) NOT NULL, population_id VARCHAR(64) NOT NULL, population_resource_id VARCHAR(64)
    NOT NULL, resource_version VARCHAR(128) NOT NULL, genome_resource_id VARCHAR(64),
    allele_count BIGINT, allele_number BIGINT, homozygote_count BIGINT, hemizygote_count BIGINT,
    allele_frequency FLOAT, denominator_context JSONB, value_semantics VARCHAR(64) DEFAULT
    'present' NOT NULL, origin VARCHAR(64) DEFAULT 'retrieved' NOT NULL, retrieved_at TIMESTAMP
    WITH TIME ZONE, provenance JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_population_frequency_observations PRIMARY KEY (id), CONSTRAINT
    fk_population_frequency_observations_genome_resource_id FOREIGN KEY(genome_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    ck_population_frequency_observations_value_semantics_valid CHECK (value_semantics IN
    ('present', 'missing', 'null', 'empty', 'na', 'unknown', 'not_applicable', 'zero',
    'false')), CONSTRAINT fk_population_frequency_observations_population_id FOREIGN
    KEY(population_id) REFERENCES app.populations (id) ON DELETE RESTRICT, CONSTRAINT
    uq_population_frequency_observations_variant_population_version UNIQUE (variant_id,
    population_id, population_resource_id, resource_version), CONSTRAINT
    fk_population_frequency_observations_population_resource_id FOREIGN
    KEY(population_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT ck_population_frequency_observations_origin_valid CHECK (origin IN ('imported',
    'retrieved', 'generated', 'machine_generated', 'human_entered', 'human_evaluated')),
    CONSTRAINT fk_population_frequency_observations_variant_id FOREIGN KEY(variant_id)
    REFERENCES app.variants (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_population_frequency_observations_genome_resource_id ON
    app.population_frequency_observations (genome_resource_id)
    """,
    """
    CREATE INDEX ix_population_frequency_observations_population_id ON
    app.population_frequency_observations (population_id)
    """,
    """
    CREATE INDEX ix_population_frequency_observations_population_resource_id ON
    app.population_frequency_observations (population_resource_id)
    """,
    """
    CREATE INDEX ix_population_frequency_observations_variant_id ON
    app.population_frequency_observations (variant_id)
    """,
    """
    CREATE TABLE app.provenance_entries ( id VARCHAR(64) NOT NULL, provenance_manifest_id
    VARCHAR(64) NOT NULL, entry_kind VARCHAR(64) NOT NULL, reference_type VARCHAR(128),
    reference_id VARCHAR(64), reference_version VARCHAR(128), checksum_value VARCHAR(256),
    detail JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_provenance_entries PRIMARY
    KEY (id), CONSTRAINT fk_provenance_entries_provenance_manifest_id FOREIGN
    KEY(provenance_manifest_id) REFERENCES app.provenance_manifests (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_provenance_entries_entry_kind_reference_id ON app.provenance_entries
    (entry_kind, reference_id)
    """,
    """
    CREATE INDEX ix_provenance_entries_provenance_manifest_id ON app.provenance_entries
    (provenance_manifest_id)
    """,
    """
    CREATE TABLE app.result_sets ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL, analysis_execution_id VARCHAR(64) NOT NULL, result_key
    VARCHAR(128) NOT NULL, state VARCHAR(64) DEFAULT 'pending' NOT NULL, analytical_location
    TEXT, scientific_artifact_id VARCHAR(64), row_count BIGINT, column_schema JSONB,
    provenance_manifest_id VARCHAR(64), metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version
    INTEGER DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP
    WITH TIME ZONE, deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_result_sets PRIMARY KEY (id), CONSTRAINT fk_result_sets_analysis_execution_id
    FOREIGN KEY(analysis_execution_id) REFERENCES app.analysis_executions (id) ON DELETE
    RESTRICT, CONSTRAINT fk_result_sets_workspace_id FOREIGN KEY(workspace_id) REFERENCES
    app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT ck_result_sets_deletion_state_valid CHECK
    (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')), CONSTRAINT fk_result_sets_scientific_artifact_id FOREIGN
    KEY(scientific_artifact_id) REFERENCES app.scientific_artifacts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_result_sets_analysis_execution_id_result_key UNIQUE (analysis_execution_id,
    result_key), CONSTRAINT fk_result_sets_project_id FOREIGN KEY(project_id) REFERENCES
    app.projects (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_result_sets_analysis_execution_id ON app.result_sets (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_result_sets_scientific_artifact_id ON app.result_sets
    (scientific_artifact_id)
    """,
    """
    CREATE INDEX ix_result_sets_workspace_id ON app.result_sets (workspace_id)
    """,
    """
    CREATE INDEX ix_result_sets_workspace_id_state ON app.result_sets (workspace_id, state)
    """,
    """
    ALTER TABLE app.result_sets ADD CONSTRAINT ck_result_sets_state_valid CHECK (state IN
    ('pending', 'generating', 'available', 'invalidated', 'expired'))
    """,
    """
    CREATE TABLE app.validation_issues ( id VARCHAR(64) NOT NULL, validation_run_id VARCHAR(64)
    NOT NULL, validation_rule_id VARCHAR(64), severity VARCHAR(64) NOT NULL, message TEXT NOT
    NULL, locator JSONB, value_semantics VARCHAR(64) DEFAULT 'present' NOT NULL, observed_value
    TEXT, details JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_validation_issues PRIMARY KEY
    (id), CONSTRAINT fk_validation_issues_validation_run_id FOREIGN KEY(validation_run_id)
    REFERENCES app.validation_runs (id) ON DELETE CASCADE, CONSTRAINT
    ck_validation_issues_severity_valid CHECK (severity IN ('info', 'warning', 'error',
    'blocking')), CONSTRAINT fk_validation_issues_validation_rule_id FOREIGN
    KEY(validation_rule_id) REFERENCES app.validation_rules (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_validation_issues_validation_rule_id ON app.validation_issues
    (validation_rule_id)
    """,
    """
    CREATE INDEX ix_validation_issues_validation_run_id ON app.validation_issues
    (validation_run_id)
    """,
    """
    CREATE INDEX ix_validation_issues_validation_run_id_severity ON app.validation_issues
    (validation_run_id, severity)
    """,
    """
    ALTER TABLE app.validation_issues ADD CONSTRAINT ck_validation_issues_value_semantics_valid
    CHECK (value_semantics IN ('present', 'missing', 'unknown', 'not_applicable', 'zero',
    'false'))
    """,
    """
    CREATE TABLE app.variant_annotations ( id VARCHAR(64) NOT NULL, variant_id VARCHAR(64) NOT
    NULL, transcript_id VARCHAR(64), annotation_resource_id VARCHAR(64) NOT NULL,
    resource_version VARCHAR(128) NOT NULL, engine_resource_id VARCHAR(64), engine_version
    VARCHAR(128), scientific_execution_id VARCHAR(64), field_key VARCHAR(255) NOT NULL,
    value_type VARCHAR(64) NOT NULL, value_string TEXT, value_number FLOAT, value_integer
    BIGINT, value_boolean BOOLEAN, value_json JSONB, value_semantics VARCHAR(64) DEFAULT
    'present' NOT NULL, origin VARCHAR(64) DEFAULT 'generated' NOT NULL, retrieved_at TIMESTAMP
    WITH TIME ZONE, provenance JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_variant_annotations PRIMARY KEY (id), CONSTRAINT
    fk_variant_annotations_annotation_resource_id FOREIGN KEY(annotation_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variant_annotations_variant_id FOREIGN KEY(variant_id) REFERENCES app.variants (id) ON
    DELETE RESTRICT, CONSTRAINT ck_variant_annotations_origin_valid CHECK (origin IN
    ('imported', 'retrieved', 'generated', 'machine_generated', 'human_entered',
    'human_evaluated')), CONSTRAINT ck_variant_annotations_value_type_valid CHECK (value_type IN
    ('string', 'integer', 'number', 'boolean', 'date', 'json')), CONSTRAINT
    fk_variant_annotations_engine_resource_id FOREIGN KEY(engine_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variant_annotations_transcript_id FOREIGN KEY(transcript_id) REFERENCES app.transcripts
    (id) ON DELETE RESTRICT, CONSTRAINT uq_variant_annotations_variant_resource_field_transcript
    UNIQUE (variant_id, annotation_resource_id, field_key, transcript_id), CONSTRAINT
    ck_variant_annotations_value_semantics_valid CHECK (value_semantics IN ('present',
    'missing', 'null', 'empty', 'na', 'unknown', 'not_applicable', 'zero', 'false')), CONSTRAINT
    fk_variant_annotations_scientific_execution_id FOREIGN KEY(scientific_execution_id)
    REFERENCES app.scientific_executions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_variant_annotations_annotation_resource_id ON app.variant_annotations
    (annotation_resource_id)
    """,
    """
    CREATE INDEX ix_variant_annotations_engine_resource_id ON app.variant_annotations
    (engine_resource_id)
    """,
    """
    CREATE INDEX ix_variant_annotations_field_key ON app.variant_annotations (field_key)
    """,
    """
    CREATE INDEX ix_variant_annotations_scientific_execution_id ON app.variant_annotations
    (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_variant_annotations_transcript_id ON app.variant_annotations (transcript_id)
    """,
    """
    CREATE INDEX ix_variant_annotations_variant_id ON app.variant_annotations (variant_id)
    """,
    """
    CREATE INDEX ix_variant_annotations_variant_id_field_key ON app.variant_annotations
    (variant_id, field_key)
    """,
    """
    CREATE TABLE app.variant_external_identifiers ( id VARCHAR(64) NOT NULL, variant_id
    VARCHAR(64) NOT NULL, namespace VARCHAR(64) NOT NULL, external_identifier VARCHAR(512) NOT
    NULL, source_resource_id VARCHAR(64), origin VARCHAR(64) DEFAULT 'imported' NOT NULL,
    is_primary BOOLEAN DEFAULT 'false' NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_variant_external_identifiers PRIMARY KEY (id), CONSTRAINT
    fk_variant_external_identifiers_variant_id FOREIGN KEY(variant_id) REFERENCES app.variants
    (id) ON DELETE RESTRICT, CONSTRAINT ck_variant_external_identifiers_origin_valid CHECK
    (origin IN ('imported', 'retrieved', 'generated', 'machine_generated', 'human_entered',
    'human_evaluated')), CONSTRAINT fk_variant_external_identifiers_source_resource_id FOREIGN
    KEY(source_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT uq_variant_external_identifiers_identity UNIQUE (variant_id, namespace,
    external_identifier, source_resource_id) )
    """,
    """
    CREATE INDEX ix_variant_external_identifiers_namespace_external_identifier ON
    app.variant_external_identifiers (namespace, external_identifier)
    """,
    """
    CREATE INDEX ix_variant_external_identifiers_source_resource_id ON
    app.variant_external_identifiers (source_resource_id)
    """,
    """
    CREATE INDEX ix_variant_external_identifiers_variant_id ON app.variant_external_identifiers
    (variant_id)
    """,
    """
    CREATE TABLE app.variant_source_representations ( id VARCHAR(64) NOT NULL, variant_id
    VARCHAR(64), dataset_version_id VARCHAR(64) NOT NULL, source_record_key VARCHAR(255) NOT
    NULL, source_genome_resource_id VARCHAR(64), source_contig VARCHAR(64) NOT NULL,
    source_position BIGINT NOT NULL, source_reference_allele TEXT, source_alternate_allele TEXT,
    source_identifier VARCHAR(255), source_payload JSONB, normalization_state VARCHAR(64)
    DEFAULT 'not_normalized' NOT NULL, normalization_failure_reason TEXT,
    transformation_metadata JSONB, build_conversion_metadata JSONB, created_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, CONSTRAINT pk_variant_source_representations PRIMARY KEY (id), CONSTRAINT
    fk_variant_source_representations_dataset_version_id FOREIGN KEY(dataset_version_id)
    REFERENCES app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variant_source_representations_source_genome_resource_id FOREIGN
    KEY(source_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE RESTRICT,
    CONSTRAINT fk_variant_source_representations_variant_id FOREIGN KEY(variant_id) REFERENCES
    app.variants (id) ON DELETE RESTRICT, CONSTRAINT
    uq_variant_source_representations_dataset_version_id_record_key UNIQUE (dataset_version_id,
    source_record_key) )
    """,
    """
    CREATE INDEX ix_variant_source_representations_dataset_version_id ON
    app.variant_source_representations (dataset_version_id)
    """,
    """
    CREATE INDEX ix_variant_source_representations_source_genome_resource_id ON
    app.variant_source_representations (source_genome_resource_id)
    """,
    """
    CREATE INDEX ix_variant_source_representations_variant_id ON
    app.variant_source_representations (variant_id)
    """,
    """
    ALTER TABLE app.variant_source_representations ADD CONSTRAINT
    ck_variant_source_representations_normalization_state_valid CHECK (normalization_state IN
    ('not_normalized', 'normalized', 'normalization_failed'))
    """,
    """
    CREATE TABLE app.variant_transcript_consequences ( id VARCHAR(64) NOT NULL, variant_id
    VARCHAR(64) NOT NULL, transcript_id VARCHAR(64), gene_id VARCHAR(64), consequence_term
    VARCHAR(128) NOT NULL, impact VARCHAR(64), hgvs_genomic TEXT, hgvs_coding TEXT, hgvs_protein
    TEXT, exon VARCHAR(32), intron VARCHAR(32), source_resource_id VARCHAR(64),
    engine_resource_id VARCHAR(64), scientific_execution_id VARCHAR(64), origin VARCHAR(64)
    DEFAULT 'generated' NOT NULL, details JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_variant_transcript_consequences PRIMARY KEY (id), CONSTRAINT
    fk_variant_transcript_consequences_source_resource_id FOREIGN KEY(source_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variant_transcript_consequences_transcript_id FOREIGN KEY(transcript_id) REFERENCES
    app.transcripts (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variant_transcript_consequences_engine_resource_id FOREIGN KEY(engine_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_variant_transcript_consequences_gene_id FOREIGN KEY(gene_id) REFERENCES app.genes (id) ON
    DELETE RESTRICT, CONSTRAINT fk_variant_transcript_consequences_variant_id FOREIGN
    KEY(variant_id) REFERENCES app.variants (id) ON DELETE RESTRICT, CONSTRAINT
    ck_variant_transcript_consequences_origin_valid CHECK (origin IN ('imported', 'retrieved',
    'generated', 'machine_generated', 'human_entered', 'human_evaluated')), CONSTRAINT
    uq_variant_transcript_consequences_identity UNIQUE (variant_id, transcript_id,
    source_resource_id, consequence_term), CONSTRAINT
    fk_variant_transcript_consequences_scientific_execution_id FOREIGN
    KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_variant_transcript_consequences_engine_resource_id ON
    app.variant_transcript_consequences (engine_resource_id)
    """,
    """
    CREATE INDEX ix_variant_transcript_consequences_gene_id ON
    app.variant_transcript_consequences (gene_id)
    """,
    """
    CREATE INDEX ix_variant_transcript_consequences_scientific_execution_id ON
    app.variant_transcript_consequences (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_variant_transcript_consequences_source_resource_id ON
    app.variant_transcript_consequences (source_resource_id)
    """,
    """
    CREATE INDEX ix_variant_transcript_consequences_transcript_id ON
    app.variant_transcript_consequences (transcript_id)
    """,
    """
    CREATE INDEX ix_variant_transcript_consequences_variant_id ON
    app.variant_transcript_consequences (variant_id)
    """,
    """
    CREATE TABLE app.evidence_items ( id VARCHAR(64) NOT NULL, variant_id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(64), project_id VARCHAR(64), category VARCHAR(64) NOT NULL, strength
    VARCHAR(64) DEFAULT 'not_applicable' NOT NULL, direction VARCHAR(64) DEFAULT 'neutral' NOT
    NULL, summary TEXT, rationale TEXT, origin VARCHAR(64) NOT NULL, source_resource_id
    VARCHAR(64), clinical_assertion_id VARCHAR(64), external_reference TEXT,
    scientific_execution_id VARCHAR(64), created_by VARCHAR(64), recorded_at TIMESTAMP WITH TIME
    ZONE, payload JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL,
    CONSTRAINT pk_evidence_items PRIMARY KEY (id), CONSTRAINT ck_evidence_items_category_valid
    CHECK (category IN ('population', 'computational', 'functional', 'segregation', 'de_novo',
    'allelic', 'phenotype', 'literature', 'clinical_database', 'other')), CONSTRAINT
    ck_evidence_items_direction_valid CHECK (direction IN ('pathogenic', 'benign', 'neutral')),
    CONSTRAINT fk_evidence_items_created_by FOREIGN KEY(created_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_evidence_items_clinical_assertion_id FOREIGN
    KEY(clinical_assertion_id) REFERENCES app.clinical_assertions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_evidence_items_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id)
    ON DELETE RESTRICT, CONSTRAINT fk_evidence_items_variant_id FOREIGN KEY(variant_id)
    REFERENCES app.variants (id) ON DELETE RESTRICT, CONSTRAINT ck_evidence_items_origin_valid
    CHECK (origin IN ('imported', 'retrieved', 'generated', 'machine_generated',
    'human_entered', 'human_evaluated')), CONSTRAINT ck_evidence_items_strength_valid CHECK
    (strength IN ('standalone', 'very_strong', 'strong', 'moderate', 'supporting',
    'not_applicable')), CONSTRAINT fk_evidence_items_scientific_execution_id FOREIGN
    KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_evidence_items_source_resource_id FOREIGN KEY(source_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT fk_evidence_items_workspace_id
    FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_evidence_items_clinical_assertion_id ON app.evidence_items
    (clinical_assertion_id)
    """,
    """
    CREATE INDEX ix_evidence_items_created_by ON app.evidence_items (created_by)
    """,
    """
    CREATE INDEX ix_evidence_items_project_id ON app.evidence_items (project_id)
    """,
    """
    CREATE INDEX ix_evidence_items_scientific_execution_id ON app.evidence_items
    (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_evidence_items_source_resource_id ON app.evidence_items (source_resource_id)
    """,
    """
    CREATE INDEX ix_evidence_items_variant_id ON app.evidence_items (variant_id)
    """,
    """
    CREATE INDEX ix_evidence_items_workspace_id ON app.evidence_items (workspace_id)
    """,
    """
    CREATE INDEX ix_evidence_items_workspace_id_project_id ON app.evidence_items (workspace_id,
    project_id)
    """,
    """
    CREATE TABLE app.interpretation_versions ( id VARCHAR(64) NOT NULL, interpretation_id
    VARCHAR(64) NOT NULL, version_number INTEGER NOT NULL, classification VARCHAR(64) DEFAULT
    'not_classified' NOT NULL, suggested_classification VARCHAR(64), origin VARCHAR(64) NOT
    NULL, rationale TEXT, clinical_significance_statement TEXT, ruleset_resource_id VARCHAR(64),
    ruleset_version VARCHAR(128), reference_genome_resource_id VARCHAR(64),
    analysis_execution_id VARCHAR(64), scientific_execution_id VARCHAR(64),
    provenance_manifest_id VARCHAR(64), evaluation_snapshot JSONB, conflict_summary JSONB,
    authored_by VARCHAR(64), finalized_by VARCHAR(64), finalized_at TIMESTAMP WITH TIME ZONE,
    supersedes_version_id VARCHAR(64), reclassification_reason TEXT, created_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, CONSTRAINT pk_interpretation_versions PRIMARY KEY (id), CONSTRAINT
    ck_interpretation_versions_classification_valid CHECK (classification IN ('pathogenic',
    'likely_pathogenic', 'uncertain_significance', 'likely_benign', 'benign',
    'not_classified')), CONSTRAINT fk_interpretation_versions_finalized_by FOREIGN
    KEY(finalized_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    uq_interpretation_versions_interpretation_id_version_number UNIQUE (interpretation_id,
    version_number), CONSTRAINT fk_interpretation_versions_scientific_execution_id FOREIGN
    KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_interpretation_versions_reference_genome_resource_id FOREIGN
    KEY(reference_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_interpretation_versions_interpretation_id FOREIGN
    KEY(interpretation_id) REFERENCES app.interpretations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_interpretation_versions_authored_by FOREIGN KEY(authored_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_interpretation_versions_analysis_execution_id FOREIGN
    KEY(analysis_execution_id) REFERENCES app.analysis_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_interpretation_versions_ruleset_resource_id FOREIGN KEY(ruleset_resource_id)
    REFERENCES app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    ck_interpretation_versions_origin_valid CHECK (origin IN ('imported', 'retrieved',
    'generated', 'machine_generated', 'human_entered', 'human_evaluated')) )
    """,
    """
    CREATE INDEX ix_interpretation_versions_analysis_execution_id ON app.interpretation_versions
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_interpretation_versions_authored_by ON app.interpretation_versions
    (authored_by)
    """,
    """
    CREATE INDEX ix_interpretation_versions_finalized_by ON app.interpretation_versions
    (finalized_by)
    """,
    """
    CREATE INDEX ix_interpretation_versions_interpretation_id ON app.interpretation_versions
    (interpretation_id)
    """,
    """
    CREATE INDEX ix_interpretation_versions_reference_genome_resource_id ON
    app.interpretation_versions (reference_genome_resource_id)
    """,
    """
    CREATE INDEX ix_interpretation_versions_ruleset_resource_id ON app.interpretation_versions
    (ruleset_resource_id)
    """,
    """
    CREATE INDEX ix_interpretation_versions_scientific_execution_id ON
    app.interpretation_versions (scientific_execution_id)
    """,
    """
    CREATE TABLE app.report_versions ( id VARCHAR(64) NOT NULL, report_id VARCHAR(64) NOT NULL,
    version_number INTEGER NOT NULL, report_template_id VARCHAR(64), analysis_execution_id
    VARCHAR(64), result_set_id VARCHAR(64), content_snapshot JSONB, provenance_manifest_id
    VARCHAR(64), rendered_file_artifact_id VARCHAR(64), checksum_algorithm VARCHAR(64),
    checksum_value VARCHAR(256), authored_by VARCHAR(64), approved_by VARCHAR(64), finalized_by
    VARCHAR(64), finalized_at TIMESTAMP WITH TIME ZONE, supersedes_version_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_report_versions PRIMARY KEY (id), CONSTRAINT
    fk_report_versions_approved_by FOREIGN KEY(approved_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_report_versions_rendered_file_artifact_id FOREIGN
    KEY(rendered_file_artifact_id) REFERENCES app.file_artifacts (id) ON DELETE RESTRICT,
    CONSTRAINT fk_report_versions_analysis_execution_id FOREIGN KEY(analysis_execution_id)
    REFERENCES app.analysis_executions (id) ON DELETE RESTRICT, CONSTRAINT
    ck_report_versions_checksum_algorithm_valid CHECK (checksum_algorithm IN ('sha256',
    'sha512', 'md5', 'crc32c')), CONSTRAINT fk_report_versions_report_id FOREIGN KEY(report_id)
    REFERENCES app.reports (id) ON DELETE RESTRICT, CONSTRAINT fk_report_versions_finalized_by
    FOREIGN KEY(finalized_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_report_versions_authored_by FOREIGN KEY(authored_by) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT fk_report_versions_result_set_id FOREIGN KEY(result_set_id) REFERENCES
    app.result_sets (id) ON DELETE RESTRICT, CONSTRAINT fk_report_versions_report_template_id
    FOREIGN KEY(report_template_id) REFERENCES app.report_templates (id) ON DELETE RESTRICT,
    CONSTRAINT uq_report_versions_report_id_version_number UNIQUE (report_id, version_number) )
    """,
    """
    CREATE INDEX ix_report_versions_analysis_execution_id ON app.report_versions
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_report_versions_approved_by ON app.report_versions (approved_by)
    """,
    """
    CREATE INDEX ix_report_versions_authored_by ON app.report_versions (authored_by)
    """,
    """
    CREATE INDEX ix_report_versions_finalized_by ON app.report_versions (finalized_by)
    """,
    """
    CREATE INDEX ix_report_versions_rendered_file_artifact_id ON app.report_versions
    (rendered_file_artifact_id)
    """,
    """
    CREATE INDEX ix_report_versions_report_id ON app.report_versions (report_id)
    """,
    """
    CREATE INDEX ix_report_versions_report_template_id ON app.report_versions
    (report_template_id)
    """,
    """
    CREATE INDEX ix_report_versions_result_set_id ON app.report_versions (result_set_id)
    """,
    """
    CREATE TABLE app.review_assignments ( id VARCHAR(64) NOT NULL, interpretation_id VARCHAR(64)
    NOT NULL, workspace_id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT NULL,
    reviewer_user_id VARCHAR(64) NOT NULL, review_role VARCHAR(64) DEFAULT 'reviewer' NOT NULL,
    state VARCHAR(64) DEFAULT 'not_started' NOT NULL, assigned_by VARCHAR(64), assigned_at
    TIMESTAMP WITH TIME ZONE, due_at TIMESTAMP WITH TIME ZONE, completed_at TIMESTAMP WITH TIME
    ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL, CONSTRAINT
    pk_review_assignments PRIMARY KEY (id), CONSTRAINT fk_review_assignments_assigned_by FOREIGN
    KEY(assigned_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_review_assignments_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id) ON
    DELETE RESTRICT, CONSTRAINT fk_review_assignments_interpretation_id FOREIGN
    KEY(interpretation_id) REFERENCES app.interpretations (id) ON DELETE RESTRICT, CONSTRAINT
    uq_review_assignments_interpretation_reviewer_role UNIQUE (interpretation_id,
    reviewer_user_id, review_role), CONSTRAINT ck_review_assignments_state_valid CHECK (state IN
    ('not_started', 'assigned', 'in_progress', 'submitted', 'accepted', 'rejected', 'escalated',
    'withdrawn')), CONSTRAINT fk_review_assignments_reviewer_user_id FOREIGN
    KEY(reviewer_user_id) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_review_assignments_workspace_id FOREIGN KEY(workspace_id) REFERENCES app.workspaces (id)
    ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_review_assignments_assigned_by ON app.review_assignments (assigned_by)
    """,
    """
    CREATE INDEX ix_review_assignments_interpretation_id ON app.review_assignments
    (interpretation_id)
    """,
    """
    CREATE INDEX ix_review_assignments_project_id ON app.review_assignments (project_id)
    """,
    """
    CREATE INDEX ix_review_assignments_reviewer_user_id ON app.review_assignments
    (reviewer_user_id)
    """,
    """
    CREATE INDEX ix_review_assignments_reviewer_user_id_state ON app.review_assignments
    (reviewer_user_id, state)
    """,
    """
    CREATE INDEX ix_review_assignments_workspace_id ON app.review_assignments (workspace_id)
    """,
    """
    CREATE TABLE app.variant_observations ( id VARCHAR(64) NOT NULL, sample_id VARCHAR(64) NOT
    NULL, variant_id VARCHAR(64) NOT NULL, dataset_version_id VARCHAR(64) NOT NULL,
    variant_source_representation_id VARCHAR(64), genotype VARCHAR(64), genotype_semantics
    VARCHAR(64) DEFAULT 'present' NOT NULL, zygosity VARCHAR(64) DEFAULT 'unknown' NOT NULL,
    allele_balance FLOAT, read_depth INTEGER, alternate_allele_depth INTEGER, genotype_quality
    INTEGER, variant_quality FLOAT, filter_status VARCHAR(255), observation_metadata JSONB,
    source_provenance JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_variant_observations PRIMARY KEY (id), CONSTRAINT
    fk_variant_observations_variant_source_representation_id FOREIGN
    KEY(variant_source_representation_id) REFERENCES app.variant_source_representations (id) ON
    DELETE RESTRICT, CONSTRAINT uq_variant_observations_sample_id_variant_id_dataset_version_id
    UNIQUE (sample_id, variant_id, dataset_version_id), CONSTRAINT
    fk_variant_observations_variant_id FOREIGN KEY(variant_id) REFERENCES app.variants (id) ON
    DELETE RESTRICT, CONSTRAINT fk_variant_observations_sample_id FOREIGN KEY(sample_id)
    REFERENCES app.samples (id) ON DELETE RESTRICT, CONSTRAINT
    ck_variant_observations_genotype_semantics_valid CHECK (genotype_semantics IN ('present',
    'missing', 'null', 'empty', 'na', 'unknown', 'not_applicable', 'zero', 'false')), CONSTRAINT
    ck_variant_observations_zygosity_valid CHECK (zygosity IN ('homozygous_reference',
    'heterozygous', 'homozygous_alternate', 'hemizygous', 'unknown', 'other')), CONSTRAINT
    fk_variant_observations_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_variant_observations_dataset_version_id ON app.variant_observations
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_variant_observations_sample_id ON app.variant_observations (sample_id)
    """,
    """
    CREATE INDEX ix_variant_observations_variant_id ON app.variant_observations (variant_id)
    """,
    """
    CREATE INDEX ix_variant_observations_variant_source_representation_id ON
    app.variant_observations (variant_source_representation_id)
    """,
    """
    CREATE TABLE app.criterion_evaluation_evidence ( id VARCHAR(64) NOT NULL,
    criterion_evaluation_id VARCHAR(64) NOT NULL, evidence_item_id VARCHAR(64) NOT NULL,
    relation VARCHAR(64) DEFAULT 'supports' NOT NULL, notes TEXT, created_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_criterion_evaluation_evidence PRIMARY KEY (id), CONSTRAINT
    uq_criterion_evaluation_evidence_evaluation_id_evidence_id UNIQUE (criterion_evaluation_id,
    evidence_item_id), CONSTRAINT fk_criterion_evaluation_evidence_evidence_item_id FOREIGN
    KEY(evidence_item_id) REFERENCES app.evidence_items (id) ON DELETE RESTRICT, CONSTRAINT
    fk_criterion_evaluation_evidence_criterion_evaluation_id FOREIGN
    KEY(criterion_evaluation_id) REFERENCES app.criterion_evaluations (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_criterion_evaluation_evidence_criterion_evaluation_id ON
    app.criterion_evaluation_evidence (criterion_evaluation_id)
    """,
    """
    CREATE INDEX ix_criterion_evaluation_evidence_evidence_item_id ON
    app.criterion_evaluation_evidence (evidence_item_id)
    """,
    """
    CREATE TABLE app.export_requests ( id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT
    NULL, project_id VARCHAR(64), result_set_id VARCHAR(64), report_version_id VARCHAR(64),
    dataset_version_id VARCHAR(64), export_format VARCHAR(64) NOT NULL, state VARCHAR(64)
    DEFAULT 'requested' NOT NULL, export_specification JSONB, filter_definition_id VARCHAR(64),
    ranking_configuration_id VARCHAR(64), requested_by VARCHAR(64) NOT NULL, job_id VARCHAR(64),
    file_artifact_id VARCHAR(64), row_count BIGINT, size_bytes BIGINT, expires_at TIMESTAMP WITH
    TIME ZONE, revoked_at TIMESTAMP WITH TIME ZONE, failure_code VARCHAR(128), failure_message
    TEXT, provenance_manifest_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
    NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER
    DEFAULT '1' NOT NULL, deletion_state VARCHAR(64) DEFAULT 'active' NOT NULL, deleted_at
    TIMESTAMP WITH TIME ZONE, deleted_by VARCHAR(64), retention_expires_at TIMESTAMP WITH TIME
    ZONE, deletion_hold_reason TEXT, permanently_deleted_at TIMESTAMP WITH TIME ZONE, CONSTRAINT
    pk_export_requests PRIMARY KEY (id), CONSTRAINT ck_export_requests_deletion_state_valid
    CHECK (deletion_state IN ('active', 'soft_deleted', 'retention', 'purge_pending',
    'permanently_deleted')), CONSTRAINT fk_export_requests_file_artifact_id FOREIGN
    KEY(file_artifact_id) REFERENCES app.file_artifacts (id) ON DELETE RESTRICT, CONSTRAINT
    fk_export_requests_ranking_configuration_id FOREIGN KEY(ranking_configuration_id) REFERENCES
    app.ranking_configurations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_export_requests_dataset_version_id FOREIGN KEY(dataset_version_id) REFERENCES
    app.dataset_versions (id) ON DELETE RESTRICT, CONSTRAINT ck_export_requests_state_valid
    CHECK (state IN ('requested', 'generating', 'available', 'failed', 'expired', 'revoked')),
    CONSTRAINT fk_export_requests_result_set_id FOREIGN KEY(result_set_id) REFERENCES
    app.result_sets (id) ON DELETE RESTRICT, CONSTRAINT fk_export_requests_workspace_id FOREIGN
    KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    fk_export_requests_requested_by FOREIGN KEY(requested_by) REFERENCES app.users (id) ON
    DELETE RESTRICT, CONSTRAINT fk_export_requests_filter_definition_id FOREIGN
    KEY(filter_definition_id) REFERENCES app.filter_definitions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_export_requests_report_version_id FOREIGN KEY(report_version_id) REFERENCES
    app.report_versions (id) ON DELETE RESTRICT, CONSTRAINT
    ck_export_requests_export_format_valid CHECK (export_format IN ('csv', 'tsv', 'json',
    'xlsx', 'vcf', 'pdf', 'parquet')), CONSTRAINT fk_export_requests_project_id FOREIGN
    KEY(project_id) REFERENCES app.projects (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_export_requests_dataset_version_id ON app.export_requests
    (dataset_version_id)
    """,
    """
    CREATE INDEX ix_export_requests_file_artifact_id ON app.export_requests (file_artifact_id)
    """,
    """
    CREATE INDEX ix_export_requests_filter_definition_id ON app.export_requests
    (filter_definition_id)
    """,
    """
    CREATE INDEX ix_export_requests_project_id ON app.export_requests (project_id)
    """,
    """
    CREATE INDEX ix_export_requests_ranking_configuration_id ON app.export_requests
    (ranking_configuration_id)
    """,
    """
    CREATE INDEX ix_export_requests_report_version_id ON app.export_requests (report_version_id)
    """,
    """
    CREATE INDEX ix_export_requests_requested_by ON app.export_requests (requested_by)
    """,
    """
    CREATE INDEX ix_export_requests_result_set_id ON app.export_requests (result_set_id)
    """,
    """
    CREATE INDEX ix_export_requests_workspace_id ON app.export_requests (workspace_id)
    """,
    """
    CREATE INDEX ix_export_requests_workspace_id_state ON app.export_requests (workspace_id,
    state)
    """,
    """
    CREATE TABLE app.report_version_interpretations ( id VARCHAR(64) NOT NULL, report_version_id
    VARCHAR(64) NOT NULL, interpretation_version_id VARCHAR(64) NOT NULL, display_order INTEGER,
    section_key VARCHAR(128), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_report_version_interpretations PRIMARY KEY (id), CONSTRAINT
    uq_report_version_interpretations_version_interpretation UNIQUE (report_version_id,
    interpretation_version_id), CONSTRAINT
    fk_report_version_interpretations_interpretation_version_id FOREIGN
    KEY(interpretation_version_id) REFERENCES app.interpretation_versions (id) ON DELETE
    RESTRICT, CONSTRAINT fk_report_version_interpretations_report_version_id FOREIGN
    KEY(report_version_id) REFERENCES app.report_versions (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_report_version_interpretations_interpretation_version_id ON
    app.report_version_interpretations (interpretation_version_id)
    """,
    """
    CREATE INDEX ix_report_version_interpretations_report_version_id ON
    app.report_version_interpretations (report_version_id)
    """,
    """
    CREATE TABLE app.review_decisions ( id VARCHAR(64) NOT NULL, interpretation_id VARCHAR(64)
    NOT NULL, interpretation_version_id VARCHAR(64) NOT NULL, review_assignment_id VARCHAR(64),
    reviewer_user_id VARCHAR(64) NOT NULL, decision VARCHAR(64) NOT NULL,
    criterion_evaluation_id VARCHAR(64), proposed_classification VARCHAR(64), rationale TEXT,
    decided_at TIMESTAMP WITH TIME ZONE NOT NULL, is_adjudication BOOLEAN DEFAULT 'false' NOT
    NULL, details JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_review_decisions PRIMARY KEY
    (id), CONSTRAINT fk_review_decisions_interpretation_id FOREIGN KEY(interpretation_id)
    REFERENCES app.interpretations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_review_decisions_criterion_evaluation_id FOREIGN KEY(criterion_evaluation_id) REFERENCES
    app.criterion_evaluations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_review_decisions_review_assignment_id FOREIGN KEY(review_assignment_id) REFERENCES
    app.review_assignments (id) ON DELETE RESTRICT, CONSTRAINT
    ck_review_decisions_decision_valid CHECK (decision IN ('accept', 'reject', 'modify',
    'add_criterion', 'remove_criterion', 'override', 'abstain', 'adjudicate')), CONSTRAINT
    fk_review_decisions_interpretation_version_id FOREIGN KEY(interpretation_version_id)
    REFERENCES app.interpretation_versions (id) ON DELETE RESTRICT, CONSTRAINT
    fk_review_decisions_reviewer_user_id FOREIGN KEY(reviewer_user_id) REFERENCES app.users (id)
    ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_review_decisions_criterion_evaluation_id ON app.review_decisions
    (criterion_evaluation_id)
    """,
    """
    CREATE INDEX ix_review_decisions_interpretation_id ON app.review_decisions
    (interpretation_id)
    """,
    """
    CREATE INDEX ix_review_decisions_interpretation_version_id ON app.review_decisions
    (interpretation_version_id)
    """,
    """
    CREATE INDEX ix_review_decisions_review_assignment_id ON app.review_decisions
    (review_assignment_id)
    """,
    """
    CREATE INDEX ix_review_decisions_reviewer_user_id ON app.review_decisions (reviewer_user_id)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP TABLE app.review_decisions
    """,
    """
    DROP TABLE app.report_version_interpretations
    """,
    """
    DROP TABLE app.export_requests
    """,
    """
    DROP TABLE app.criterion_evaluation_evidence
    """,
    """
    DROP TABLE app.variant_observations
    """,
    """
    DROP TABLE app.review_assignments
    """,
    """
    DROP TABLE app.report_versions
    """,
    """
    DROP TABLE app.interpretation_versions
    """,
    """
    DROP TABLE app.evidence_items
    """,
    """
    DROP TABLE app.variant_transcript_consequences
    """,
    """
    DROP TABLE app.variant_source_representations
    """,
    """
    DROP TABLE app.variant_external_identifiers
    """,
    """
    DROP TABLE app.variant_annotations
    """,
    """
    DROP TABLE app.validation_issues
    """,
    """
    DROP TABLE app.result_sets
    """,
    """
    DROP TABLE app.provenance_entries
    """,
    """
    DROP TABLE app.population_frequency_observations
    """,
    """
    DROP TABLE app.interpretations
    """,
    """
    DROP TABLE app.criterion_evaluations
    """,
    """
    DROP TABLE app.clinical_assertions
    """,
    """
    DROP TABLE platform.job_attempts
    """,
    """
    DROP TABLE app.variants
    """,
    """
    DROP TABLE app.validation_runs
    """,
    """
    DROP TABLE app.scientific_artifacts
    """,
    """
    DROP TABLE app.provenance_manifests
    """,
    """
    DROP TABLE platform.jobs
    """,
    """
    DROP TABLE app.scientific_executions
    """,
    """
    DROP TABLE app.import_sessions
    """,
    """
    DROP TABLE app.analysis_execution_inputs
    """,
    """
    DROP TABLE platform.scheduled_jobs
    """,
    """
    DROP TABLE app.samples
    """,
    """
    DROP TABLE app.file_artifacts
    """,
    """
    DROP TABLE app.analysis_executions
    """,
    """
    DROP TABLE app.analysis_configuration_inputs
    """,
    """
    DROP TABLE app.saved_views
    """,
    """
    DROP TABLE app.ranking_configuration_versions
    """,
    """
    DROP TABLE app.notification_deliveries
    """,
    """
    DROP TABLE app.filter_definition_versions
    """,
    """
    DROP TABLE app.dataset_versions
    """,
    """
    DROP TABLE app.analysis_configurations
    """,
    """
    DROP TABLE platform.audit_events
    """,
    """
    DROP TABLE app.resource_assignments
    """,
    """
    DROP TABLE app.reports
    """,
    """
    DROP TABLE app.ranking_configurations
    """,
    """
    DROP TABLE app.project_memberships
    """,
    """
    DROP TABLE app.project_invitations
    """,
    """
    DROP TABLE app.notifications
    """,
    """
    DROP TABLE app.filter_definitions
    """,
    """
    DROP TABLE app.discussion_comments
    """,
    """
    DROP TABLE app.datasets
    """,
    """
    DROP TABLE app.analyses
    """,
    """
    DROP TABLE platform.domain_event_outbox
    """,
    """
    DROP TABLE app.transcripts
    """,
    """
    DROP TABLE app.projects
    """,
    """
    DROP TABLE platform.retention_actions
    """,
    """
    DROP TABLE platform.configuration_setting_versions
    """,
    """
    DROP TABLE app.workspaces
    """,
    """
    DROP TABLE app.scientific_resource_compatibility
    """,
    """
    DROP TABLE app.report_templates
    """,
    """
    DROP TABLE app.populations
    """,
    """
    DROP TABLE app.organization_settings
    """,
    """
    DROP TABLE app.organization_memberships
    """,
    """
    DROP TABLE app.organization_invitations
    """,
    """
    DROP TABLE app.genes
    """,
    """
    DROP TABLE app.external_assertion_sources
    """,
    """
    DROP TABLE platform.security_events
    """,
    """
    DROP TABLE platform.retention_policies
    """,
    """
    DROP TABLE platform.configuration_settings
    """,
    """
    DROP TABLE app.user_preferences
    """,
    """
    DROP TABLE app.user_authentication_metadata
    """,
    """
    DROP TABLE app.service_accounts
    """,
    """
    DROP TABLE app.scientific_resources
    """,
    """
    DROP TABLE app.platform_role_assignments
    """,
    """
    DROP TABLE app.organizations
    """,
    """
    DROP TABLE app.notification_preferences
    """,
    """
    DROP TABLE platform.worker_nodes
    """,
    """
    DROP TABLE platform.resource_usage_records
    """,
    """
    DROP TABLE app.validation_rules
    """,
    """
    DROP TABLE app.users
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
