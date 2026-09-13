"""Durable job and schedule persistence.

Schema support for the later scheduler: concurrency-safe claiming (``state`` +
``lease_expires_at`` + ``claimed_by_worker_id``), heartbeats, attempt/retry
bookkeeping, cancellation, idempotency keys, priority and queue routing. The
scheduler itself is a later package; nothing here executes work.

Jobs are operational bookkeeping and therefore live in the ``platform`` schema,
while referencing domain rows in ``app``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import JobKind, JobState, ScheduleState
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
        # Claiming index: the scheduler polls by queue/state/priority.
        Index("ix_jobs_queue_state_priority_available_at", "queue", "state", "priority",
              "available_at"),
        Index("ix_jobs_state_lease_expires_at", "state", "lease_expires_at"),
        Index("ix_jobs_correlation_id", "correlation_id"),
        Index("ix_jobs_analysis_execution_id", "analysis_execution_id"),
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
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnostics: Mapped[dict | None] = json_column()


class ScheduledJob(Base, TimestampMixin, ConcurrencyMixin):
    """A recurring definition. Each firing creates independent execution rows."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("owner_scope", "owner_id", "name",
                         name="uq_scheduled_jobs_owner_scope_owner_id_name"),
        state_check("state", ScheduleState, "state_valid"),
        state_check("job_kind", JobKind, "job_kind_valid"),
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
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
