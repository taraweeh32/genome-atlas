"""Audit, provenance, domain events, configuration and retention governance.

Four deliberately separate systems, never collapsed into one table:

* ``audit_events`` — durable, user-visible record of *who did what*.
* ``provenance_manifests`` / ``provenance_entries`` — scientific lineage of a
  result: inputs, resources, engine/environment identity, parameters, artifacts.
* ``domain_event_outbox`` — transactional dispatch of domain events (activity
  feeds, notifications, integrations).
* ``security_events`` — authentication/authorization/security-relevant records.

Operational observability (logs, metrics, traces) is not persisted here at all.
All four live in the ``platform`` schema except provenance, which is domain state
because a result is meaningless without its lineage.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    ActorType,
    AuditChannel,
    AuditOutcome,
    ConfigurationScope,
    ConfigurationState,
    DeletionState,
    OutboxState,
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


class AuditEvent(Base, TimestampMixin):
    """Append-only audit record. No update path, no delete path."""

    __tablename__ = "audit_events"
    __table_args__ = (
        state_check("actor_type", ActorType, "actor_type_valid"),
        state_check("outcome", AuditOutcome, "outcome_valid"),
        state_check("channel", AuditChannel, "channel_valid"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_resource_type_resource_id", "resource_type", "resource_id"),
        Index("ix_audit_events_organization_id_occurred_at", "organization_id", "occurred_at"),
        Index("ix_audit_events_correlation_id", "correlation_id"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Dotted action name, e.g. ``project.archived``, ``dataset_version.accepted``.
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    actor_service_account_id: Mapped[str | None] = fk_column(
        "app.service_accounts.id", nullable=True
    )
    #: Human-readable actor label captured at the time of the event, so the
    #: record stays meaningful after an account is renamed or removed.
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    organization_id: Mapped[str | None] = fk_column("app.organizations.id", nullable=True)
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    #: State transition captured explicitly when the action was a transition.
    previous_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Structured, non-sensitive detail. Never genomic content, never secrets.
    detail: Mapped[dict | None] = json_column()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SecurityEvent(Base, TimestampMixin):
    """Security-relevant record, separate from ordinary audit activity."""

    __tablename__ = "security_events"
    __table_args__ = (
        state_check("outcome", AuditOutcome, "outcome_valid"),
        Index("ix_security_events_occurred_at", "occurred_at"),
        Index("ix_security_events_event_kind", "event_kind"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: e.g. ``authentication.failed``, ``authorization.denied``, ``rate_limited``.
    event_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    #: Login attempts reference an address that may not resolve to a user.
    subject_identifier_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict | None] = json_column()
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProvenanceManifest(Base, TimestampMixin):
    """Immutable lineage record for one produced scientific result."""

    __tablename__ = "provenance_manifests"
    __table_args__ = (
        UniqueConstraint("scientific_execution_id",
                         name="uq_provenance_manifests_scientific_execution_id"),
        Index("ix_provenance_manifests_analysis_execution_id", "analysis_execution_id"),
        Index("ix_provenance_manifests_correlation_id", "correlation_id"),
    )

    id: Mapped[str] = id_column()
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Complete, self-contained snapshot: inputs, configuration, resource
    #: identities, engine/environment/node identity, parameters, artifacts.
    manifest: Mapped[dict | None] = json_column()
    #: Digest of the manifest, so tampering or drift is detectable.
    manifest_digest: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ProvenanceEntry(Base, TimestampMixin):
    """One queryable lineage fact belonging to a manifest."""

    __tablename__ = "provenance_entries"
    __table_args__ = (
        Index("ix_provenance_entries_provenance_manifest_id", "provenance_manifest_id"),
        Index("ix_provenance_entries_entry_kind_reference_id", "entry_kind", "reference_id"),
    )

    id: Mapped[str] = id_column()
    provenance_manifest_id: Mapped[str] = fk_column(
        "app.provenance_manifests.id", ondelete="CASCADE"
    )
    #: ``input_dataset_version`` | ``scientific_resource`` | ``artifact`` |
    #: ``configuration`` | ``environment`` | ``node`` | ``parameter``.
    entry_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[dict | None] = json_column()


class DomainEventOutbox(Base, TimestampMixin):
    """Transactional outbox: a domain event committed with its state change."""

    __tablename__ = "domain_event_outbox"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_domain_event_outbox_event_key"),
        state_check("state", OutboxState, "state_valid"),
        Index("ix_domain_event_outbox_state_available_at", "state", "available_at"),
        Index("ix_domain_event_outbox_correlation_id", "correlation_id"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    #: Idempotency key for dispatch; a duplicate publish is rejected by the DB.
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    aggregate_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    payload: Mapped[dict | None] = json_column()
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=OutboxState.PENDING.value
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ConfigurationSetting(Base, TimestampMixin, ConcurrencyMixin):
    """Scoped, versioned runtime configuration owned by the backend.

    Environment configuration and secrets are *not* stored here — they come from
    the environment. This table holds platform/organization/project/personal
    policy that administrators change at runtime.
    """

    __tablename__ = "configuration_settings"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "setting_key",
                         name="uq_configuration_settings_scope_scope_id_setting_key"),
        state_check("scope", ConfigurationScope, "scope_valid"),
        state_check("state", ConfigurationState, "state_valid"),
        Index("ix_configuration_settings_setting_key", "setting_key"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    setting_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ConfigurationState.ACTIVE.value
    )
    value_json: Mapped[dict | None] = json_column()
    #: Never a secret: secrets are injected from the environment, not persisted.
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                               server_default="false")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfigurationSettingVersion(Base, TimestampMixin):
    """Change history for a configuration setting."""

    __tablename__ = "configuration_setting_versions"
    __table_args__ = (
        UniqueConstraint("configuration_setting_id", "version_number",
                         name="uq_configuration_setting_versions_setting_id_version_number"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    configuration_setting_id: Mapped[str] = fk_column(
        "platform.configuration_settings.id", ondelete="CASCADE"
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[dict | None] = json_column()
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RetentionPolicy(Base, TimestampMixin, ConcurrencyMixin):
    """Scoped retention policy for a resource type."""

    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "resource_type",
                         name="uq_retention_policies_scope_scope_id_resource_type"),
        state_check("scope", ConfigurationScope, "scope_valid"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    soft_delete_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Immutable scientific records may be exempt from purge entirely.
    purge_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                server_default="false")
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class RetentionAction(Base, TimestampMixin):
    """Append-only record of a retention/deletion action and its outcome."""

    __tablename__ = "retention_actions"
    __table_args__ = (
        state_check("target_state", DeletionState, "target_state_valid"),
        Index("ix_retention_actions_resource_type_resource_id",
              "resource_type", "resource_id"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_policy_id: Mapped[str | None] = fk_column(
        "platform.retention_policies.id", nullable=True
    )
    previous_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_state: Mapped[str] = mapped_column(String(64), nullable=False)
    performed_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Dependencies that blocked or accompanied the action.
    dependency_summary: Mapped[dict | None] = json_column()
    recoverable_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResourceUsageRecord(Base, TimestampMixin):
    """Resource governance accounting (storage, compute, job minutes)."""

    __tablename__ = "resource_usage_records"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "metric_key", "period_start",
                         name="uq_resource_usage_records_scope_metric_period"),
        state_check("scope", ConfigurationScope, "scope_valid"),
        Index("ix_resource_usage_records_period_start", "period_start"),
        {"schema": OPERATIONAL_SCHEMA},
    )

    id: Mapped[str] = id_column()
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    quota_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict | None] = json_column()
