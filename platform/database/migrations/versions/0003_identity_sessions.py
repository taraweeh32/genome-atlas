"""Sessions and credential tokens.

Package 3 adds the two tables server-authoritative authentication needs and that
Package 2 deliberately did not speculate about:

* ``app.user_sessions`` — one row per authenticated session, storing only the
  *hash* of the opaque session token plus the session's CSRF secret hash. Because
  the session is a database row, revocation is immediate and independent of token
  expiry.
* ``app.user_credential_tokens`` — single-use email-verification and
  password-reset tokens, again hash-only, with consumption and invalidation
  recorded rather than rows being deleted.

Written as explicit ``op.*`` statements against the Package 2 baseline, as that
baseline's docstring prescribes.

Revision ID: 0003_identity_sessions
Revises: 0002_domain_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.domain.value_objects.enums import (
    CredentialTokenKind,
    CredentialTokenState,
    SessionState,
)

revision = "0003_identity_sessions"
down_revision = "0002_domain_schema"
branch_labels = None
depends_on = None

#: The exact table set this revision owns, as ``schema.table``. The schema
#: drift test asserts the union of every revision's ``TABLES`` equals the model
#: metadata, so a forgotten migration fails the build.
TABLES: tuple[str, ...] = (
    "app.user_sessions",
    "app.user_credential_tokens",
)


def _values(vocabulary) -> str:  # noqa: ANN001
    return ", ".join(f"'{member.value}'" for member in vocabulary)


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("csrf_token_hash", sa.String(128), nullable=True),
        sa.Column(
            "state", sa.String(64), nullable=False, server_default=SessionState.ACTIVE.value
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(128), nullable=True),
        sa.Column("mfa_satisfied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reauthenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(128), nullable=True),
        sa.Column("user_agent_summary", sa.String(255), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app.users.id"],
            name="fk_user_sessions_user_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        sa.CheckConstraint(
            f"state IN ({_values(SessionState)})", name="ck_user_sessions_state_valid"
        ),
        schema="app",
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], schema="app")
    op.create_index(
        "ix_user_sessions_user_id_state", "user_sessions", ["user_id", "state"], schema="app"
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"], schema="app")

    op.create_table(
        "user_credential_tokens",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column(
            "state",
            sa.String(64),
            nullable=False,
            server_default=CredentialTokenState.ACTIVE.value,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presentation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_ip_hash", sa.String(128), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app.users.id"],
            name="fk_user_credential_tokens_user_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_user_credential_tokens_token_hash"),
        sa.CheckConstraint(
            f"kind IN ({_values(CredentialTokenKind)})",
            name="ck_user_credential_tokens_kind_valid",
        ),
        sa.CheckConstraint(
            f"state IN ({_values(CredentialTokenState)})",
            name="ck_user_credential_tokens_state_valid",
        ),
        schema="app",
    )
    op.create_index(
        "ix_user_credential_tokens_user_id", "user_credential_tokens", ["user_id"], schema="app"
    )
    op.create_index(
        "ix_user_credential_tokens_user_id_kind_state",
        "user_credential_tokens",
        ["user_id", "kind", "state"],
        schema="app",
    )
    op.create_index(
        "ix_user_credential_tokens_expires_at",
        "user_credential_tokens",
        ["expires_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("user_credential_tokens", schema="app")
    op.drop_table("user_sessions", schema="app")
