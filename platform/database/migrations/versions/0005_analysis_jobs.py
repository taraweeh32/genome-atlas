"""Analysis configurations, executions, durable jobs, schedules and nodes.

Additive revision on top of Packages 2-4. It owns one new table and extends the
existing analysis/job/schedule/node tables with the columns the Package 5
lifecycle needs:

* ``platform.schedule_triggers`` — one row per schedule firing, written before
  any work is created. The unique ``(scheduled_job_id, scheduled_for)`` key is
  what makes recurring execution idempotent, so two schedulers racing for the
  same slot cannot both launch an execution.

Existing tables gain: operational execution defaults on analyses; validation
state, label and a content digest on configuration versions; scheduling,
capability, cancellation and progress columns on executions; error class,
resource/capability requirements, node class and lease duration on jobs;
recurrence expression, time zone, concurrency and missed-firing policy on
schedules; health, lifecycle, capacity and version identity on nodes.

State vocabularies are persisted as ``VARCHAR + CHECK`` (never as a PostgreSQL
enum), so widening ``execution_state`` and ``job_state`` is an ordinary
transactional constraint replacement. Nothing here drops or rewrites data: every
added column is nullable or carries a server default, so existing rows keep
their meaning.

Revision ID: 0005_analysis_jobs
Revises: 0004_dataset_ingest
"""

from __future__ import annotations

from alembic import op

from app.domain.value_objects.enums import (
    ConfigurationValidationState,
    ExecutionState,
    JobQueue,
    JobState,
    MissedSchedulePolicy,
    NodeClass,
    NodeHealthState,
    NodeLifecycleState,
    ScheduleConcurrencyPolicy,
)
from app.infrastructure.persistence.models import Base

revision = "0005_analysis_jobs"
down_revision = "0004_dataset_ingest"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = ("platform.schedule_triggers",)

_APP = "app"
_OPERATIONAL = "platform"


def _vocabulary(vocabulary) -> str:  # noqa: ANN001 - StrEnum subclass
    return ", ".join(f"'{member.value}'" for member in vocabulary)


def _replace_check(schema: str, table: str, column: str, constraint: str, vocabulary) -> None:  # noqa: ANN001
    """Widen a persisted vocabulary in place."""
    op.execute(f"ALTER TABLE {schema}.{table} DROP CONSTRAINT ck_{table}_{constraint}")
    op.execute(
        f"ALTER TABLE {schema}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
        f"CHECK ({column} IN ({_vocabulary(vocabulary)}))"
    )


def _add_state_column(
    schema: str,
    table: str,
    column: str,
    vocabulary,  # noqa: ANN001 - StrEnum subclass
    default: str,
    constraint: str,
) -> None:
    op.execute(
        f"ALTER TABLE {schema}.{table} "
        f"ADD COLUMN {column} VARCHAR(64) NOT NULL DEFAULT '{default}'"
    )
    op.execute(
        f"ALTER TABLE {schema}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
        f"CHECK ({column} IN ({_vocabulary(vocabulary)}))"
    )


def upgrade() -> None:
    connection = op.get_bind()

    # --- analyses ---------------------------------------------------------- #
    op.execute("ALTER TABLE app.analyses ADD COLUMN execution_defaults JSONB")

    # --- analysis_configurations ------------------------------------------- #
    op.execute("ALTER TABLE app.analysis_configurations ADD COLUMN label VARCHAR(255)")
    _add_state_column(
        _APP,
        "analysis_configurations",
        "validation_state",
        ConfigurationValidationState,
        ConfigurationValidationState.UNVALIDATED.value,
        "validation_state_valid",
    )
    op.execute("ALTER TABLE app.analysis_configurations ADD COLUMN validation_findings JSONB")
    op.execute("ALTER TABLE app.analysis_configurations ADD COLUMN content_hash VARCHAR(128)")
    op.execute(
        "CREATE INDEX ix_analysis_configurations_content_hash "
        "ON app.analysis_configurations (content_hash)"
    )

    # --- analysis_executions ----------------------------------------------- #
    # Widen the execution vocabulary: validation, engine submission and an
    # explicit cancellation *request* become first-class states.
    _replace_check(_APP, "analysis_executions", "state", "state_valid", ExecutionState)
    for statement in (
        "ADD COLUMN capability_key VARCHAR(128)",
        "ADD COLUMN capability_version VARCHAR(128)",
        "ADD COLUMN priority INTEGER NOT NULL DEFAULT 100",
        "ADD COLUMN resource_requirements JSONB",
        "ADD COLUMN idempotency_key VARCHAR(255)",
        "ADD COLUMN schedule_id VARCHAR(64)",
        "ADD COLUMN scheduled_for TIMESTAMP WITH TIME ZONE",
        "ADD COLUMN scientific_execution_id VARCHAR(64)",
        "ADD COLUMN compute_node_id VARCHAR(128)",
        "ADD COLUMN progress_percent INTEGER",
        "ADD COLUMN progress_message TEXT",
        "ADD COLUMN cancel_requested_at TIMESTAMP WITH TIME ZONE",
        "ADD COLUMN cancellation_reason TEXT",
    ):
        op.execute(f"ALTER TABLE app.analysis_executions {statement}")
    op.execute(
        "ALTER TABLE app.analysis_executions ADD COLUMN cancel_requested_by VARCHAR(64) "
        "REFERENCES app.users(id) ON DELETE RESTRICT"
    )
    _add_state_column(
        _APP,
        "analysis_executions",
        "queue",
        JobQueue,
        JobQueue.DEFAULT.value,
        "queue_valid",
    )
    op.execute(
        "ALTER TABLE app.analysis_executions "
        "ADD CONSTRAINT uq_analysis_executions_idempotency_key UNIQUE (idempotency_key)"
    )
    op.execute(
        "CREATE INDEX ix_analysis_executions_project_id_requested_at "
        "ON app.analysis_executions (project_id, requested_at)"
    )
    op.execute(
        "CREATE INDEX ix_analysis_executions_schedule_id "
        "ON app.analysis_executions (schedule_id)"
    )

    # --- jobs -------------------------------------------------------------- #
    # Widen the job vocabulary: retry backoff, staleness and a cancellation
    # request become observable states instead of implicit side effects.
    _replace_check(_OPERATIONAL, "jobs", "state", "state_valid", JobState)
    _replace_check(_OPERATIONAL, "job_attempts", "state", "state_valid", JobState)
    op.execute("ALTER TABLE platform.jobs ADD COLUMN error_class VARCHAR(64)")
    op.execute("ALTER TABLE platform.jobs ADD COLUMN resource_requirements JSONB")
    op.execute("ALTER TABLE platform.jobs ADD COLUMN required_capabilities JSONB")
    op.execute(
        "ALTER TABLE platform.jobs "
        "ADD COLUMN lease_duration_seconds INTEGER NOT NULL DEFAULT 60"
    )
    # ``queue`` already exists from Package 2; constrain it rather than re-adding.
    op.execute(
        "ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_queue_valid "
        f"CHECK (queue IN ({_vocabulary(JobQueue)}))"
    )
    _add_state_column(
        _OPERATIONAL,
        "jobs",
        "node_class",
        NodeClass,
        NodeClass.APPLICATION_WORKER.value,
        "node_class_valid",
    )

    # --- job_attempts ------------------------------------------------------ #
    op.execute("ALTER TABLE platform.job_attempts ADD COLUMN node_id VARCHAR(128)")
    op.execute("ALTER TABLE platform.job_attempts ADD COLUMN error_class VARCHAR(64)")

    # --- scheduled_jobs ---------------------------------------------------- #
    for statement in (
        "ADD COLUMN description TEXT",
        "ADD COLUMN schedule_kind VARCHAR(32) NOT NULL DEFAULT 'interval'",
        "ADD COLUMN schedule_expression VARCHAR(128) NOT NULL DEFAULT 'every:1d'",
        "ADD COLUMN timezone_name VARCHAR(64) NOT NULL DEFAULT 'UTC'",
        "ADD COLUMN priority INTEGER NOT NULL DEFAULT 100",
        "ADD COLUMN catch_up_limit INTEGER NOT NULL DEFAULT 1",
        "ADD COLUMN last_trigger_outcome VARCHAR(64)",
        "ADD COLUMN consecutive_failure_count INTEGER NOT NULL DEFAULT 0",
    ):
        op.execute(f"ALTER TABLE platform.scheduled_jobs {statement}")
    op.execute(
        "ALTER TABLE platform.scheduled_jobs ADD COLUMN workspace_id VARCHAR(64) "
        "REFERENCES app.workspaces(id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE platform.scheduled_jobs ADD COLUMN project_id VARCHAR(64) "
        "REFERENCES app.projects(id) ON DELETE RESTRICT"
    )
    _add_state_column(
        _OPERATIONAL,
        "scheduled_jobs",
        "concurrency_policy",
        ScheduleConcurrencyPolicy,
        ScheduleConcurrencyPolicy.SKIP_IF_RUNNING.value,
        "concurrency_policy_valid",
    )
    _add_state_column(
        _OPERATIONAL,
        "scheduled_jobs",
        "missed_policy",
        MissedSchedulePolicy,
        MissedSchedulePolicy.SKIP.value,
        "missed_policy_valid",
    )
    _add_state_column(
        _OPERATIONAL,
        "scheduled_jobs",
        "queue",
        JobQueue,
        JobQueue.DEFAULT.value,
        "queue_valid",
    )
    op.execute(
        "CREATE INDEX ix_scheduled_jobs_workspace_id "
        "ON platform.scheduled_jobs (workspace_id)"
    )

    # --- worker_nodes ------------------------------------------------------ #
    _add_state_column(
        _OPERATIONAL,
        "worker_nodes",
        "health_state",
        NodeHealthState,
        NodeHealthState.UNKNOWN.value,
        "health_state_valid",
    )
    _add_state_column(
        _OPERATIONAL,
        "worker_nodes",
        "lifecycle_state",
        NodeLifecycleState,
        NodeLifecycleState.ACTIVE.value,
        "lifecycle_state_valid",
    )
    op.execute(
        "ALTER TABLE platform.worker_nodes ADD CONSTRAINT ck_worker_nodes_node_class_valid "
        f"CHECK (node_class IN ({_vocabulary(NodeClass)}))"
    )
    for statement in (
        "ADD COLUMN max_concurrency INTEGER NOT NULL DEFAULT 1",
        "ADD COLUMN active_job_count INTEGER NOT NULL DEFAULT 0",
        "ADD COLUMN engine_version VARCHAR(128)",
        "ADD COLUMN environment_version VARCHAR(128)",
        "ADD COLUMN registered_at TIMESTAMP WITH TIME ZONE",
        "ADD COLUMN drain_reason TEXT",
        "ADD COLUMN last_error TEXT",
    ):
        op.execute(f"ALTER TABLE platform.worker_nodes {statement}")

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

    for column in (
        "last_error",
        "drain_reason",
        "registered_at",
        "environment_version",
        "engine_version",
        "active_job_count",
        "max_concurrency",
        "lifecycle_state",
        "health_state",
    ):
        op.execute(f"ALTER TABLE platform.worker_nodes DROP COLUMN {column}")
    op.execute(
        "ALTER TABLE platform.worker_nodes DROP CONSTRAINT ck_worker_nodes_node_class_valid"
    )

    op.execute("DROP INDEX platform.ix_scheduled_jobs_workspace_id")
    for column in (
        "queue",
        "missed_policy",
        "concurrency_policy",
        "project_id",
        "workspace_id",
        "consecutive_failure_count",
        "last_trigger_outcome",
        "catch_up_limit",
        "priority",
        "timezone_name",
        "schedule_expression",
        "schedule_kind",
        "description",
    ):
        op.execute(f"ALTER TABLE platform.scheduled_jobs DROP COLUMN {column}")

    for column in ("error_class", "node_id"):
        op.execute(f"ALTER TABLE platform.job_attempts DROP COLUMN {column}")
    op.execute("ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_queue_valid")
    for column in (
        "node_class",
        "lease_duration_seconds",
        "required_capabilities",
        "resource_requirements",
        "error_class",
    ):
        op.execute(f"ALTER TABLE platform.jobs DROP COLUMN {column}")
    # Restore the narrower Package 2 vocabularies.
    op.execute("ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_state_valid")
    op.execute(
        "ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_state_valid CHECK (state IN "
        "('pending', 'queued', 'claimed', 'running', 'succeeded', 'failed', "
        "'cancelling', 'cancelled', 'dead_letter'))"
    )
    op.execute("ALTER TABLE platform.job_attempts DROP CONSTRAINT ck_job_attempts_state_valid")
    op.execute(
        "ALTER TABLE platform.job_attempts ADD CONSTRAINT ck_job_attempts_state_valid "
        "CHECK (state IN ('pending', 'queued', 'claimed', 'running', 'succeeded', 'failed', "
        "'cancelling', 'cancelled', 'dead_letter'))"
    )

    op.execute("DROP INDEX app.ix_analysis_executions_schedule_id")
    op.execute("DROP INDEX app.ix_analysis_executions_project_id_requested_at")
    op.execute(
        "ALTER TABLE app.analysis_executions "
        "DROP CONSTRAINT uq_analysis_executions_idempotency_key"
    )
    for column in (
        "queue",
        "cancel_requested_by",
        "cancellation_reason",
        "cancel_requested_at",
        "progress_message",
        "progress_percent",
        "compute_node_id",
        "scientific_execution_id",
        "scheduled_for",
        "schedule_id",
        "idempotency_key",
        "resource_requirements",
        "priority",
        "capability_version",
        "capability_key",
    ):
        op.execute(f"ALTER TABLE app.analysis_executions DROP COLUMN {column}")
    op.execute("ALTER TABLE app.analysis_executions DROP CONSTRAINT ck_analysis_executions_state_valid")
    op.execute(
        "ALTER TABLE app.analysis_executions ADD CONSTRAINT ck_analysis_executions_state_valid "
        "CHECK (state IN ('requested', 'queued', 'running', 'succeeded', 'failed', "
        "'cancelled', 'timed_out'))"
    )

    op.execute("DROP INDEX app.ix_analysis_configurations_content_hash")
    for column in ("content_hash", "validation_findings", "validation_state", "label"):
        op.execute(f"ALTER TABLE app.analysis_configurations DROP COLUMN {column}")
    op.execute("ALTER TABLE app.analyses DROP COLUMN execution_defaults")
