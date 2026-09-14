"""Durable job, schedule, trigger and node persistence.

Concurrency-safe claiming (``state`` + ``lease_expires_at`` +
``claimed_by_worker_id``), heartbeats, attempt/retry bookkeeping, cancellation,
idempotency keys, priority and queue routing. The claiming SQL and the worker
runtime that use these columns live in the repositories and worker packages;
nothing in this module executes work.

Jobs are operational bookkeeping and therefore live in the ``platform`` schema,
while referencing domain rows in ``app``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    JobKind,
    JobQueue,
    JobState,
    MissedSchedulePolicy,
    NodeClass,
    NodeHealthState,
    NodeLifecycleState,
    ScheduleConcurrencyPolicy,
    ScheduleState,
    ScheduleTriggerOutcome,
)
from app.infrastructure.persistence.base import (
    OPERATIONAL_SCHEMA,
    Base,
    ConcurrencyMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Job(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        state_check("kind", JobKind, "kind_valid"),
        state_check("state", JobState, "state_valid"),
        state_check("queue", JobQueue, "queue_valid"),
        state_check("node_class", NodeClass, "node_class_valid"),
        # Claiming index: the scheduler polls by queue/state/priority.
        Index("ix_jobs_queue_state_priority_available_at", "queue", "state", "priority",
              "available_at"),
        Index("ix_jobs_state_lease_expires_at", "state", "lease_expires_at"),
        Index("ix_jobs_correlation_id", "correlation_id"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=JobState.PENDING.value
    )
    queue: Mapped[str] = mapped_column(String(64), nullable=False, server_default="default")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    #: Optional links to what the job is doing.
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    scientific_execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Tenancy scope so job listings can be authorized like any other resource.
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    payload: Mapped[dict | None] = json_column()
    #: Security/execution context reference — never the credentials themselves.
    execution_context_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assigned_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                              nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_details: Mapped[dict | None] = json_column()
    #: Structured failure taxonomy. Retryability is derived from this class, so
    #: an unclassified failure can never be retried by accident.
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Scheduling requirements matched against a node's advertised profile.
    resource_requirements: Mapped[dict | None] = json_column()
    required_capabilities: Mapped[dict | None] = json_column()
    #: Which fleet may run this job. Application and scientific workers are
    #: distinct fleets and are never interchangeable.
    node_class: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=NodeClass.APPLICATION_WORKER.value
    )
    lease_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class JobAttempt(Base, TimestampMixin):
    """Append-only record of each attempt, so retries stay auditable."""

    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_id_attempt_number"),
        state_check("state", JobState, "state_valid"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    job_id: Mapped[str] = fk_column("platform.jobs.id", ondelete="CASCADE")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    diagnostics: Mapped[dict | None] = json_column()


class ScheduledJob(Base, TimestampMixin, ConcurrencyMixin):
    """A recurring definition. Each firing creates independent execution rows."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("owner_scope", "owner_id", "name",
                         name="uq_scheduled_jobs_owner_scope_owner_id_name"),
        state_check("state", ScheduleState, "state_valid"),
        state_check("job_kind", JobKind, "job_kind_valid"),
        state_check("concurrency_policy", ScheduleConcurrencyPolicy, "concurrency_policy_valid"),
        state_check("missed_policy", MissedSchedulePolicy, "missed_policy_valid"),
        state_check("queue", JobQueue, "queue_valid"),
        Index("ix_scheduled_jobs_state_next_execution_at", "state", "next_execution_at"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: ``platform`` | ``organization`` | ``project`` | ``personal``.
    owner_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_id: Mapped[str | None] = fk_column("app.analyses.id", nullable=True)
    analysis_configuration_id: Mapped[str | None] = fk_column(
        "app.analysis_configurations.id", nullable=True
    )
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ScheduleState.DISABLED.value
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    #: ``interval`` | ``daily`` | ``weekly`` | ``monthly`` — see
    #: ``app.domain.analysis.schedule`` for the expression grammar.
    schedule_kind: Mapped[str] = mapped_column(String(32), nullable=False,
                                               server_default="interval")
    schedule_expression: Mapped[str] = mapped_column(String(128), nullable=False,
                                                     server_default="every:1d")
    #: IANA zone. Stored timestamps stay UTC; the zone only decides which UTC
    #: instant a local wall-clock rule refers to.
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False,
                                               server_default="UTC")
    concurrency_policy: Mapped[str] = mapped_column(
        String(64), nullable=False,
        server_default=ScheduleConcurrencyPolicy.SKIP_IF_RUNNING.value,
    )
    missed_policy: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MissedSchedulePolicy.SKIP.value
    )
    queue: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=JobQueue.DEFAULT.value
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    #: Upper bound on how many missed firings a recovery may run at once.
    catch_up_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    last_trigger_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consecutive_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    schedule_configuration: Mapped[dict | None] = json_column()
    next_execution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    previous_execution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    previous_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class WorkerNode(Base, TimestampMixin, ConcurrencyMixin):
    """Registered application or scientific worker node.

    Application workers and scientific execution workers are distinct: the
    ``node_class`` column keeps them apart rather than merging both fleets.
    """

    __tablename__ = "worker_nodes"
    __table_args__ = (
        UniqueConstraint("node_key", name="uq_worker_nodes_node_key"),
        state_check("node_class", NodeClass, "node_class_valid"),
        state_check("health_state", NodeHealthState, "health_state_valid"),
        state_check("lifecycle_state", NodeLifecycleState, "lifecycle_state_valid"),
        Index("ix_worker_nodes_node_class_heartbeat_at", "node_class", "heartbeat_at"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    #: ``application_worker`` | ``scientific_worker``.
    node_class: Mapped[str] = mapped_column(String(64), nullable=False)
    queues: Mapped[dict | None] = json_column()
    capabilities: Mapped[dict | None] = json_column()
    resource_profile: Mapped[dict | None] = json_column()
    #: Observed health, written from heartbeats. ``unknown`` is never treated as
    #: healthy: a node must prove it is usable before work is offered to it.
    health_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=NodeHealthState.UNKNOWN.value
    )
    #: Administrative intent, deliberately separate from observed health.
    lifecycle_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=NodeLifecycleState.ACTIVE.value
    )
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    active_job_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drain_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduleTrigger(Base, TimestampMixin):
    """One firing of a schedule, written *before* any work is created.

    The unique ``(scheduled_job_id, scheduled_for)`` constraint is what makes
    recurring execution idempotent: two schedulers racing for the same slot
    cannot both create an execution, and a skipped firing is recorded with its
    reason instead of vanishing.
    """

    __tablename__ = "schedule_triggers"
    __table_args__ = (
        UniqueConstraint(
            "scheduled_job_id", "scheduled_for",
            name="uq_schedule_triggers_scheduled_job_id_scheduled_for",
        ),
        state_check("outcome", ScheduleTriggerOutcome, "outcome_valid"),
        Index("ix_schedule_triggers_scheduled_job_id_triggered_at",
              "scheduled_job_id", "triggered_at"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    scheduled_job_id: Mapped[str] = fk_column("platform.scheduled_jobs.id", ondelete="CASCADE")
    #: The slot this firing belongs to, not the moment it was processed.
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = json_column()
