"""Foundation migration.

Establishes the schema layout the domain model will be created inside, plus the
extensions the platform relies on. NO domain tables are created here: the
complete database/domain model belongs to Package 2, and speculative tables for
future features are deliberately not created.

Revision ID: 0001_foundation
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

# Domain state lives in `app`; operational/bookkeeping objects live in `platform`.
SCHEMAS = ("app", "platform")


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # Records that a deployment's schema bootstrap ran, and when. Alembic tracks
    # revisions; this records the platform-level initialization event.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform.schema_bootstrap (
            id            integer     PRIMARY KEY DEFAULT 1,
            initialized_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT schema_bootstrap_single_row CHECK (id = 1)
        )
        """
    )
    op.execute(
        "INSERT INTO platform.schema_bootstrap (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.schema_bootstrap")
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
