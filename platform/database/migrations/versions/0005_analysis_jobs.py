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

revision = "0005_analysis_jobs"
down_revision = "0004_dataset_ingest"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "platform.schedule_triggers",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE app.analyses ADD COLUMN execution_defaults JSONB
    """,
    """
    ALTER TABLE app.analysis_configurations ADD COLUMN label VARCHAR(255)
    """,
    """
    ALTER TABLE app.analysis_configurations ADD COLUMN validation_state VARCHAR(64) NOT NULL
    DEFAULT 'unvalidated'
    """,
    """
    ALTER TABLE app.analysis_configurations ADD CONSTRAINT
    ck_analysis_configurations_validation_state_valid CHECK (validation_state IN ('unvalidated',
    'valid', 'invalid'))
    """,
    """
    ALTER TABLE app.analysis_configurations ADD COLUMN validation_findings JSONB
    """,
    """
    ALTER TABLE app.analysis_configurations ADD COLUMN content_hash VARCHAR(128)
    """,
    """
    CREATE INDEX ix_analysis_configurations_content_hash ON app.analysis_configurations
    (content_hash)
    """,
    """
    ALTER TABLE app.analysis_executions DROP CONSTRAINT ck_analysis_executions_state_valid
    """,
    """
    ALTER TABLE app.analysis_executions ADD CONSTRAINT ck_analysis_executions_state_valid CHECK
    (state IN ('draft', 'validating', 'validated', 'submitted', 'requested', 'queued',
    'running', 'succeeded', 'failed', 'cancel_requested', 'cancelled', 'timed_out'))
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN capability_key VARCHAR(128)
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN capability_version VARCHAR(128)
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN priority INTEGER NOT NULL DEFAULT 100
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN resource_requirements JSONB
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN idempotency_key VARCHAR(255)
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN schedule_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN scheduled_for TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN scientific_execution_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN compute_node_id VARCHAR(128)
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN progress_percent INTEGER
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN progress_message TEXT
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN cancel_requested_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN cancellation_reason TEXT
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN cancel_requested_by VARCHAR(64) REFERENCES
    app.users(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE app.analysis_executions ADD COLUMN queue VARCHAR(64) NOT NULL DEFAULT 'default'
    """,
    """
    ALTER TABLE app.analysis_executions ADD CONSTRAINT ck_analysis_executions_queue_valid CHECK
    (queue IN ('default', 'scientific', 'import', 'validation', 'maintenance', 'export'))
    """,
    """
    ALTER TABLE app.analysis_executions ADD CONSTRAINT uq_analysis_executions_idempotency_key
    UNIQUE (idempotency_key)
    """,
    """
    CREATE INDEX ix_analysis_executions_project_id_requested_at ON app.analysis_executions
    (project_id, requested_at)
    """,
    """
    CREATE INDEX ix_analysis_executions_schedule_id ON app.analysis_executions (schedule_id)
    """,
    """
    ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_state_valid
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_state_valid CHECK (state IN ('pending',
    'queued', 'claimed', 'running', 'succeeded', 'failed', 'cancel_requested', 'cancelling',
    'cancelled', 'retry_waiting', 'stale', 'dead_letter'))
    """,
    """
    ALTER TABLE platform.job_attempts DROP CONSTRAINT ck_job_attempts_state_valid
    """,
    """
    ALTER TABLE platform.job_attempts ADD CONSTRAINT ck_job_attempts_state_valid CHECK (state IN
    ('pending', 'queued', 'claimed', 'running', 'succeeded', 'failed', 'cancel_requested',
    'cancelling', 'cancelled', 'retry_waiting', 'stale', 'dead_letter'))
    """,
    """
    ALTER TABLE platform.jobs ADD COLUMN error_class VARCHAR(64)
    """,
    """
    ALTER TABLE platform.jobs ADD COLUMN resource_requirements JSONB
    """,
    """
    ALTER TABLE platform.jobs ADD COLUMN required_capabilities JSONB
    """,
    """
    ALTER TABLE platform.jobs ADD COLUMN lease_duration_seconds INTEGER NOT NULL DEFAULT 60
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_queue_valid CHECK (queue IN ('default',
    'scientific', 'import', 'validation', 'maintenance', 'export'))
    """,
    """
    ALTER TABLE platform.jobs ADD COLUMN node_class VARCHAR(64) NOT NULL DEFAULT
    'application_worker'
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_node_class_valid CHECK (node_class IN
    ('application_worker', 'scientific_worker'))
    """,
    """
    ALTER TABLE platform.job_attempts ADD COLUMN node_id VARCHAR(128)
    """,
    """
    ALTER TABLE platform.job_attempts ADD COLUMN error_class VARCHAR(64)
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN description TEXT
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN schedule_kind VARCHAR(32) NOT NULL DEFAULT
    'interval'
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN schedule_expression VARCHAR(128) NOT NULL
    DEFAULT 'every:1d'
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN timezone_name VARCHAR(64) NOT NULL DEFAULT
    'UTC'
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 100
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN catch_up_limit INTEGER NOT NULL DEFAULT 1
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN last_trigger_outcome VARCHAR(64)
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN consecutive_failure_count INTEGER NOT NULL
    DEFAULT 0
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN workspace_id VARCHAR(64) REFERENCES
    app.workspaces(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN project_id VARCHAR(64) REFERENCES
    app.projects(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN concurrency_policy VARCHAR(64) NOT NULL
    DEFAULT 'skip_if_running'
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD CONSTRAINT
    ck_scheduled_jobs_concurrency_policy_valid CHECK (concurrency_policy IN ('allow_concurrent',
    'skip_if_running', 'queue_if_running'))
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN missed_policy VARCHAR(64) NOT NULL DEFAULT
    'skip'
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD CONSTRAINT ck_scheduled_jobs_missed_policy_valid
    CHECK (missed_policy IN ('skip', 'run_once_after_recovery', 'catch_up'))
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD COLUMN queue VARCHAR(64) NOT NULL DEFAULT 'default'
    """,
    """
    ALTER TABLE platform.scheduled_jobs ADD CONSTRAINT ck_scheduled_jobs_queue_valid CHECK
    (queue IN ('default', 'scientific', 'import', 'validation', 'maintenance', 'export'))
    """,
    """
    CREATE INDEX ix_scheduled_jobs_workspace_id ON platform.scheduled_jobs (workspace_id)
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN health_state VARCHAR(64) NOT NULL DEFAULT
    'unknown'
    """,
    """
    ALTER TABLE platform.worker_nodes ADD CONSTRAINT ck_worker_nodes_health_state_valid CHECK
    (health_state IN ('unknown', 'healthy', 'degraded', 'unhealthy', 'unavailable',
    'maintenance'))
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN lifecycle_state VARCHAR(64) NOT NULL DEFAULT
    'active'
    """,
    """
    ALTER TABLE platform.worker_nodes ADD CONSTRAINT ck_worker_nodes_lifecycle_state_valid CHECK
    (lifecycle_state IN ('active', 'draining', 'maintenance', 'unavailable'))
    """,
    """
    ALTER TABLE platform.worker_nodes ADD CONSTRAINT ck_worker_nodes_node_class_valid CHECK
    (node_class IN ('application_worker', 'scientific_worker'))
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN max_concurrency INTEGER NOT NULL DEFAULT 1
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN active_job_count INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN engine_version VARCHAR(128)
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN environment_version VARCHAR(128)
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN registered_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN drain_reason TEXT
    """,
    """
    ALTER TABLE platform.worker_nodes ADD COLUMN last_error TEXT
    """,
    """
    CREATE TABLE platform.schedule_triggers ( id VARCHAR(64) NOT NULL, scheduled_job_id
    VARCHAR(64) NOT NULL, scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL, triggered_at
    TIMESTAMP WITH TIME ZONE NOT NULL, outcome VARCHAR(64) NOT NULL, analysis_execution_id
    VARCHAR(64), job_id VARCHAR(64), detail JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT
    now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_schedule_triggers PRIMARY KEY (id), CONSTRAINT fk_schedule_triggers_analysis_execution_id
    FOREIGN KEY(analysis_execution_id) REFERENCES app.analysis_executions (id) ON DELETE
    RESTRICT, CONSTRAINT uq_schedule_triggers_scheduled_job_id_scheduled_for UNIQUE
    (scheduled_job_id, scheduled_for), CONSTRAINT ck_schedule_triggers_outcome_valid CHECK
    (outcome IN ('triggered', 'skipped_concurrency', 'skipped_missed', 'skipped_disabled',
    'failed')), CONSTRAINT fk_schedule_triggers_scheduled_job_id FOREIGN KEY(scheduled_job_id)
    REFERENCES platform.scheduled_jobs (id) ON DELETE CASCADE )
    """,
    """
    CREATE INDEX ix_schedule_triggers_analysis_execution_id ON platform.schedule_triggers
    (analysis_execution_id)
    """,
    """
    CREATE INDEX ix_schedule_triggers_scheduled_job_id ON platform.schedule_triggers
    (scheduled_job_id)
    """,
    """
    CREATE INDEX ix_schedule_triggers_scheduled_job_id_triggered_at ON
    platform.schedule_triggers (scheduled_job_id, triggered_at)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP TABLE platform.schedule_triggers
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN last_error
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN drain_reason
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN registered_at
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN environment_version
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN engine_version
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN active_job_count
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN max_concurrency
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN lifecycle_state
    """,
    """
    ALTER TABLE platform.worker_nodes DROP COLUMN health_state
    """,
    """
    ALTER TABLE platform.worker_nodes DROP CONSTRAINT ck_worker_nodes_node_class_valid
    """,
    """
    DROP INDEX platform.ix_scheduled_jobs_workspace_id
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN queue
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN missed_policy
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN concurrency_policy
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN project_id
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN workspace_id
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN consecutive_failure_count
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN last_trigger_outcome
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN catch_up_limit
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN priority
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN timezone_name
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN schedule_expression
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN schedule_kind
    """,
    """
    ALTER TABLE platform.scheduled_jobs DROP COLUMN description
    """,
    """
    ALTER TABLE platform.job_attempts DROP COLUMN error_class
    """,
    """
    ALTER TABLE platform.job_attempts DROP COLUMN node_id
    """,
    """
    ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_queue_valid
    """,
    """
    ALTER TABLE platform.jobs DROP COLUMN node_class
    """,
    """
    ALTER TABLE platform.jobs DROP COLUMN lease_duration_seconds
    """,
    """
    ALTER TABLE platform.jobs DROP COLUMN required_capabilities
    """,
    """
    ALTER TABLE platform.jobs DROP COLUMN resource_requirements
    """,
    """
    ALTER TABLE platform.jobs DROP COLUMN error_class
    """,
    """
    ALTER TABLE platform.jobs DROP CONSTRAINT ck_jobs_state_valid
    """,
    """
    ALTER TABLE platform.jobs ADD CONSTRAINT ck_jobs_state_valid CHECK (state IN ('pending',
    'queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelling', 'cancelled',
    'dead_letter'))
    """,
    """
    ALTER TABLE platform.job_attempts DROP CONSTRAINT ck_job_attempts_state_valid
    """,
    """
    ALTER TABLE platform.job_attempts ADD CONSTRAINT ck_job_attempts_state_valid CHECK (state IN
    ('pending', 'queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelling',
    'cancelled', 'dead_letter'))
    """,
    """
    DROP INDEX app.ix_analysis_executions_schedule_id
    """,
    """
    DROP INDEX app.ix_analysis_executions_project_id_requested_at
    """,
    """
    ALTER TABLE app.analysis_executions DROP CONSTRAINT uq_analysis_executions_idempotency_key
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN queue
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN cancel_requested_by
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN cancellation_reason
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN cancel_requested_at
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN progress_message
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN progress_percent
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN compute_node_id
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN scientific_execution_id
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN scheduled_for
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN schedule_id
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN idempotency_key
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN resource_requirements
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN priority
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN capability_version
    """,
    """
    ALTER TABLE app.analysis_executions DROP COLUMN capability_key
    """,
    """
    ALTER TABLE app.analysis_executions DROP CONSTRAINT ck_analysis_executions_state_valid
    """,
    """
    ALTER TABLE app.analysis_executions ADD CONSTRAINT ck_analysis_executions_state_valid CHECK
    (state IN ('requested', 'queued', 'running', 'succeeded', 'failed', 'cancelled',
    'timed_out'))
    """,
    """
    DROP INDEX app.ix_analysis_configurations_content_hash
    """,
    """
    ALTER TABLE app.analysis_configurations DROP COLUMN content_hash
    """,
    """
    ALTER TABLE app.analysis_configurations DROP COLUMN validation_findings
    """,
    """
    ALTER TABLE app.analysis_configurations DROP COLUMN validation_state
    """,
    """
    ALTER TABLE app.analysis_configurations DROP COLUMN label
    """,
    """
    ALTER TABLE app.analyses DROP COLUMN execution_defaults
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
