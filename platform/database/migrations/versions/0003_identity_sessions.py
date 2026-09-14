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

This revision is **self-contained**: every statement is literal SQL frozen at
this point in the schema history. It deliberately does not import the current
SQLAlchemy models, ``Base.metadata`` or the domain vocabularies — a migration
must describe the schema as it was, so evolving the ORM can never rewrite
history.
"""

from __future__ import annotations

from alembic import op

revision = "0003_identity_sessions"
down_revision = "0002_domain_schema"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.user_sessions",
    "app.user_credential_tokens",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app.user_sessions ( id VARCHAR(64) NOT NULL, user_id VARCHAR(64) NOT NULL,
    token_hash VARCHAR(128) NOT NULL, csrf_token_hash VARCHAR(128), state VARCHAR(64) DEFAULT
    'active' NOT NULL, issued_at TIMESTAMP WITH TIME ZONE NOT NULL, expires_at TIMESTAMP WITH
    TIME ZONE NOT NULL, absolute_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, last_seen_at
    TIMESTAMP WITH TIME ZONE, revoked_at TIMESTAMP WITH TIME ZONE, revocation_reason
    VARCHAR(128), mfa_satisfied BOOLEAN DEFAULT 'false' NOT NULL, reauthenticated_at TIMESTAMP
    WITH TIME ZONE, ip_hash VARCHAR(128), user_agent_summary VARCHAR(255), correlation_id
    VARCHAR(64), metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT
    NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT
    '1' NOT NULL, CONSTRAINT pk_user_sessions PRIMARY KEY (id), CONSTRAINT
    ck_user_sessions_state_valid CHECK (state IN ('active', 'expired', 'revoked',
    'superseded')), CONSTRAINT uq_user_sessions_token_hash UNIQUE (token_hash), CONSTRAINT
    fk_user_sessions_user_id FOREIGN KEY(user_id) REFERENCES app.users (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_user_sessions_expires_at ON app.user_sessions (expires_at)
    """,
    """
    CREATE INDEX ix_user_sessions_user_id ON app.user_sessions (user_id)
    """,
    """
    CREATE INDEX ix_user_sessions_user_id_state ON app.user_sessions (user_id, state)
    """,
    """
    CREATE TABLE app.user_credential_tokens ( id VARCHAR(64) NOT NULL, user_id VARCHAR(64) NOT
    NULL, kind VARCHAR(64) NOT NULL, state VARCHAR(64) DEFAULT 'active' NOT NULL, token_hash
    VARCHAR(128) NOT NULL, expires_at TIMESTAMP WITH TIME ZONE NOT NULL, consumed_at TIMESTAMP
    WITH TIME ZONE, invalidated_at TIMESTAMP WITH TIME ZONE, presentation_count INTEGER DEFAULT
    '0' NOT NULL, requested_ip_hash VARCHAR(128), invalidation_reason TEXT, correlation_id
    VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at
    TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version INTEGER DEFAULT '1' NOT NULL,
    CONSTRAINT pk_user_credential_tokens PRIMARY KEY (id), CONSTRAINT
    fk_user_credential_tokens_user_id FOREIGN KEY(user_id) REFERENCES app.users (id) ON DELETE
    RESTRICT, CONSTRAINT ck_user_credential_tokens_state_valid CHECK (state IN ('active',
    'consumed', 'expired', 'invalidated')), CONSTRAINT ck_user_credential_tokens_kind_valid
    CHECK (kind IN ('email_verification', 'password_reset')), CONSTRAINT
    uq_user_credential_tokens_token_hash UNIQUE (token_hash) )
    """,
    """
    CREATE INDEX ix_user_credential_tokens_expires_at ON app.user_credential_tokens (expires_at)
    """,
    """
    CREATE INDEX ix_user_credential_tokens_user_id ON app.user_credential_tokens (user_id)
    """,
    """
    CREATE INDEX ix_user_credential_tokens_user_id_kind_state ON app.user_credential_tokens
    (user_id, kind, state)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP TABLE app.user_credential_tokens
    """,
    """
    DROP TABLE app.user_sessions
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
