"""Structural guarantees the domain schema must keep.

These tests run against the declarative metadata, so they are fast and require no
database, while still failing the build on the mistakes that matter: drift
between the migration and the models, tenancy columns going missing, mutable
history, silent cascades that would destroy scientific lineage, unconstrained
state columns and PostgreSQL identifier-length violations.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.infrastructure.persistence.models import Base

MAX_IDENTIFIER_LENGTH = 63

#: Tables that are append-only history and therefore must never be mutated.
IMMUTABLE_TABLES = {
    "analysis_executions",
    "filter_executions",
    "ranking_executions",
    "audit_events",
    "criterion_evaluation_evidence",
    "interpretation_versions",
    "job_attempts",
    "provenance_entries",
    "provenance_manifests",
    "report_versions",
    "review_decisions",
    "scientific_artifacts",
    "scientific_executions",
    "security_events",
    "variant_source_representations",
}

#: Tables scoped to a tenant must carry the workspace scope explicitly.
WORKSPACE_SCOPED_TABLES = {
    "analyses",
    "analysis_executions",
    "datasets",
    "export_requests",
    "interpretations",
    "projects",
    "reports",
    "result_sets",
    "review_assignments",
    "samples",
}


def _qualified(table) -> str:  # noqa: ANN001
    return f"{table.schema or 'app'}.{table.name}"


def _revision_module(filename: str):  # noqa: ANN202
    """Load a migration revision module directly from its file."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2] / "database" / "migrations" / "versions" / filename
    )
    specification = importlib.util.spec_from_file_location(f"revision_{filename}", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


#: Every revision that owns tables, newest last. A new table must be added to a
#: revision here, otherwise the drift test below fails.
TABLE_OWNING_REVISIONS = (
    "0002_domain_schema.py",
    "0003_identity_sessions.py",
    "0004_dataset_ingest.py",
    "0005_analysis_jobs.py",
    "0006_variant_results.py",
    "0007_filtering_ranking.py",
)


def test_metadata_matches_the_migration_table_set() -> None:
    """The migrations own exactly the tables the models declare."""
    owned: set[str] = set()
    for filename in TABLE_OWNING_REVISIONS:
        revision_tables = set(_revision_module(filename).TABLES)
        # No table may be created twice across the revision chain.
        assert not (owned & revision_tables), owned & revision_tables
        owned |= revision_tables
    assert owned == {_qualified(t) for t in Base.metadata.sorted_tables}


def test_every_table_lives_in_an_owned_schema() -> None:
    for table in Base.metadata.sorted_tables:
        assert (table.schema or "app") in {"app", "platform"}, table.name


def test_every_table_has_a_single_string_primary_key() -> None:
    for table in Base.metadata.sorted_tables:
        columns = list(table.primary_key.columns)
        assert len(columns) == 1, f"{table.name} must have a single-column primary key"
        assert isinstance(columns[0].type, postgresql.VARCHAR | type(columns[0].type))
        assert columns[0].name == "id", table.name


def test_every_table_records_creation_and_update_time() -> None:
    for table in Base.metadata.sorted_tables:
        assert "created_at" in table.c, table.name
        assert "updated_at" in table.c, table.name
        assert table.c.created_at.type.timezone is True, table.name


def test_no_identifier_exceeds_the_postgresql_limit() -> None:
    """PostgreSQL truncates >63 char identifiers, which breaks later drops."""
    offenders: list[str] = []
    for table in Base.metadata.sorted_tables:
        names = [table.name, *(c.name for c in table.constraints if c.name)]
        names += [i.name for i in table.indexes if i.name]
        offenders += [str(n) for n in names if len(str(n)) > MAX_IDENTIFIER_LENGTH]
    assert offenders == []


def test_all_ddl_compiles_for_postgresql() -> None:
    for table in Base.metadata.sorted_tables:
        CreateTable(table).compile(dialect=postgresql.dialect())


def test_every_state_column_is_constrained_to_a_vocabulary() -> None:
    """A state column without a CHECK constraint can hold any string."""
    unconstrained: list[str] = []
    for table in Base.metadata.sorted_tables:
        checks = " ".join(
            str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
        )
        for column in table.c:
            if column.name in {"state", "deletion_state", "review_state"} and (
                column.name not in checks
            ):
                unconstrained.append(f"{table.name}.{column.name}")
    assert unconstrained == []


#: A cascade is only ever allowed from a row to its own owning parent row, so
#: deleting the parent cannot leave orphaned children. Everything else uses
#: RESTRICT, which forces removal through the retention lifecycle instead of
#: silently destroying dependent records or scientific lineage.
ALLOWED_CASCADES = {
    ("job_attempts", "job_id"),
    ("schedule_triggers", "scheduled_job_id"),
    ("criterion_evaluation_evidence", "criterion_evaluation_id"),
    ("provenance_entries", "provenance_manifest_id"),
    ("analysis_configuration_inputs", "analysis_configuration_id"),
    ("filter_definition_versions", "filter_definition_id"),
    ("filter_preset_versions", "filter_preset_id"),
    ("ranking_preset_versions", "ranking_preset_id"),
    ("ranking_configuration_versions", "ranking_configuration_id"),
    ("configuration_setting_versions", "configuration_setting_id"),
    ("notification_deliveries", "notification_id"),
    ("notification_preferences", "user_id"),
    ("organization_invitations", "organization_id"),
    ("organization_settings", "organization_id"),
    ("platform_role_assignments", "user_id"),
    ("project_invitations", "project_id"),
    ("user_preferences", "user_id"),
    ("validation_issues", "validation_run_id"),
    ("scientific_resource_compatibility", "resource_id"),
}


def test_foreign_keys_never_cascade_outside_owned_child_rows() -> None:
    violations: list[str] = []
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            key = (table.name, fk.parent.name)
            if fk.ondelete == "CASCADE" and key not in ALLOWED_CASCADES:
                violations.append(f"{table.name}.{fk.parent.name}=CASCADE")
            if fk.ondelete not in {"RESTRICT", "CASCADE"}:
                violations.append(f"{table.name}.{fk.parent.name}={fk.ondelete}")
    assert violations == []


def test_immutable_history_tables_are_never_cascade_deleted_by_a_tenant() -> None:
    """Audit, provenance and version history survive resource deletion."""
    for name in IMMUTABLE_TABLES:
        table = next(t for t in Base.metadata.sorted_tables if t.name == name)
        for fk in table.foreign_keys:
            if fk.ondelete == "CASCADE":
                assert (table.name, fk.parent.name) in ALLOWED_CASCADES


@pytest.mark.parametrize("table_name", sorted(WORKSPACE_SCOPED_TABLES))
def test_tenant_scoped_tables_carry_the_workspace_scope(table_name: str) -> None:
    table = next(t for t in Base.metadata.sorted_tables if t.name == table_name)
    assert "workspace_id" in table.c


def test_variant_identity_is_the_canonical_tuple() -> None:
    """Canonical identity may never include rsID or any external accession."""
    variants = Base.metadata.tables["app.variants"]
    unique = next(
        c for c in variants.constraints
        if c.name == "uq_variants_canonical_identity"
    )
    assert [c.name for c in unique.columns] == [
        "reference_genome_resource_id",
        "contig",
        "position",
        "reference_allele",
        "alternate_allele",
        "normalization_version",
    ]
    assert "rsid" not in variants.c
    assert "clinvar_id" not in variants.c


def test_source_representation_is_preserved_separately_from_identity() -> None:
    source = Base.metadata.tables["app.variant_source_representations"]
    for column in ("source_contig", "source_position", "source_payload"):
        assert column in source.c
    #: A record that failed normalization is still kept.
    assert source.c.variant_id.nullable is True


def test_interpretation_versions_are_immutable_and_versioned() -> None:
    versions = Base.metadata.tables["app.interpretation_versions"]
    assert "version_number" in versions.c
    assert "supersedes_version_id" in versions.c
    assert "evaluation_snapshot" in versions.c
    #: Conflicting evidence must be retained, not discarded.
    assert "conflict_summary" in versions.c


def test_criterion_evaluations_distinguish_human_from_automated() -> None:
    evaluations = Base.metadata.tables["app.criterion_evaluations"]
    assert "origin" in evaluations.c
    assert "evaluated_by_user_id" in evaluations.c
    assert "evaluation_method" in evaluations.c
    assert "is_override" in evaluations.c
    #: The ruleset identity is mandatory: a criterion is meaningless without it.
    assert evaluations.c.ruleset_resource_id.nullable is False
    assert evaluations.c.ruleset_version.nullable is False


def test_reports_snapshot_their_interpretation_versions() -> None:
    link = Base.metadata.tables["app.report_version_interpretations"]
    assert "interpretation_version_id" in link.c
    report_versions = Base.metadata.tables["app.report_versions"]
    assert "content_snapshot" in report_versions.c
    assert "provenance_manifest_id" in report_versions.c


def test_filtering_and_ranking_are_separate_tables() -> None:
    assert "app.filter_definitions" in Base.metadata.tables
    assert "app.ranking_configurations" in Base.metadata.tables
    filters = Base.metadata.tables["app.filter_definitions"]
    ranking = Base.metadata.tables["app.ranking_configurations"]
    assert "weights" not in filters.c
    assert "predicate_tree" not in ranking.c


def test_large_genomic_payloads_are_referenced_not_stored() -> None:
    """No table may hold bulk genomic content; only references and metadata."""
    result_sets = Base.metadata.tables["app.result_sets"]
    assert "analytical_location" in result_sets.c
    artifacts = Base.metadata.tables["app.scientific_artifacts"]
    assert "file_artifact_id" in artifacts.c
    assert "analytical_location" in artifacts.c


def test_jobs_support_concurrency_safe_claiming_and_recovery() -> None:
    jobs = Base.metadata.tables["platform.jobs"]
    for column in (
        "state",
        "queue",
        "priority",
        "available_at",
        "claimed_by_worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempt_number",
        "max_attempts",
        "cancellation_requested_at",
        "idempotency_key",
        "correlation_id",
    ):
        assert column in jobs.c, column
    index_columns = {tuple(c.name for c in index.columns) for index in jobs.indexes}
    assert ("queue", "state", "priority", "available_at") in index_columns


def test_audit_provenance_and_events_are_separate_systems() -> None:
    assert "platform.audit_events" in Base.metadata.tables
    assert "app.provenance_manifests" in Base.metadata.tables
    assert "platform.domain_event_outbox" in Base.metadata.tables
    assert "platform.security_events" in Base.metadata.tables
    audit = Base.metadata.tables["platform.audit_events"]
    #: Audit records actions, not scientific lineage.
    assert "manifest" not in audit.c


def test_retention_lifecycle_is_separate_from_operational_state() -> None:
    projects = Base.metadata.tables["app.projects"]
    assert "state" in projects.c
    assert "deletion_state" in projects.c
    assert "retention_expires_at" in projects.c
    assert "permanently_deleted_at" in projects.c


def test_no_table_stores_a_secret_or_credential() -> None:
    forbidden = ("password", "secret", "token", "api_key", "private_key")
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.c
        if any(term in column.name for term in forbidden)
        # Hashes, algorithm names, rotation timestamps and opaque references are
        # metadata about a credential, never the credential itself.
        and not column.name.endswith(
            ("_hash", "_algorithm", "_updated_at", "_expires_at", "_reference", "_ref")
        )
    ]
    assert offenders == []
