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
"""

from __future__ import annotations

from alembic import op

from app.infrastructure.persistence.models import Base

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


def _qualified(table) -> str:  # noqa: ANN001 - sqlalchemy Table
    return f"{table.schema or 'app'}.{table.name}"


def upgrade() -> None:
    connection = op.get_bind()
    tables = [t for t in Base.metadata.sorted_tables if _qualified(t) in set(TABLES)]
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=False)


def downgrade() -> None:
    connection = op.get_bind()
    tables = [t for t in Base.metadata.sorted_tables if _qualified(t) in set(TABLES)]
    Base.metadata.drop_all(bind=connection, tables=tables, checkfirst=False)
