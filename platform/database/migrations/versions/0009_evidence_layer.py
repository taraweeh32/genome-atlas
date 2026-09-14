"""Evidence ingestion batches, validation findings, and the widened evidence row.

Additive revision on top of Packages 2-8.

Deliberately *not* created here:

* an evidence source table — a registered evidence source version is a row in the
  existing ``app.scientific_resources`` registry (kind ``evidence_resource``), so
  it inherits the platform's resource lifecycle and governance;
* a second evidence record table — evidence records stay ``app.evidence_items``,
  the table Package 2 established. This revision widens it instead of forking the
  evidence model in two.

New tables:

* ``app.evidence_ingestion_batches`` — one validated delivery of evidence,
  unique on ``(source_key, payload_digest)``, which is what makes redelivery
  idempotent rather than duplicating evidence.
* ``app.evidence_validation_findings`` — why individual claims were refused,
  downgraded or flagged, kept so a refusal stays explainable.

``app.evidence_items`` gains source identity (key, version, the source's own
identifier and release time), retrieval time as a fact separate from release time,
gene/condition context, stated applicability, a lifecycle state, method, and the
versioning columns that let a newer delivery from the same source supersede an
older one without rewriting it.

Revision ID: 0009_evidence_layer
Revises: 0008_annotation_resources
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.domain.value_objects.enums import EvidenceApplicability, EvidenceRecordState
from app.infrastructure.persistence.models import Base

revision = "0009_evidence_layer"
down_revision = "0008_annotation_resources"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.evidence_ingestion_batches",
    "app.evidence_validation_findings",
)

_APP = "app"

def _added_columns() -> tuple[sa.Column, ...]:
    """Columns added to the existing evidence row.

    Built fresh on each call: a ``Column`` object may only be attached to one
    table, so upgrade and downgrade cannot share instances.
    """
    return (
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("source_identifier", sa.String(length=255), nullable=True),
        sa.Column("source_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gene_symbol", sa.String(length=128), nullable=True),
        sa.Column("gene_identifier", sa.String(length=128), nullable=True),
        sa.Column("transcript_identifier", sa.String(length=128), nullable=True),
        sa.Column("condition_identifier", sa.String(length=255), nullable=True),
        sa.Column("condition_term", sa.Text(), nullable=True),
        sa.Column("inheritance", sa.String(length=128), nullable=True),
        sa.Column(
            "applicability",
            sa.String(length=64),
            nullable=False,
            server_default=EvidenceApplicability.UNDETERMINED.value,
        ),
        sa.Column(
            "state",
            sa.String(length=64),
            nullable=False,
            server_default=EvidenceRecordState.RECORDED.value,
        ),
        sa.Column("method", sa.String(length=255), nullable=True),
        sa.Column("evidence_key", sa.String(length=255), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_id", sa.String(length=64), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=64), nullable=True),
        sa.Column("ingestion_batch_id", sa.String(length=64), nullable=True),
        sa.Column("payload_digest", sa.String(length=128), nullable=True),
        sa.Column("provenance", JSONB(), nullable=True),
    )



def _vocabulary(vocabulary) -> str:  # noqa: ANN001 - StrEnum subclass
    return ", ".join(f"'{member.value}'" for member in vocabulary)


def _owned_tables() -> list:
    owned = set(TABLES)
    return [
        table
        for table in Base.metadata.sorted_tables
        if f"{table.schema or _APP}.{table.name}" in owned
    ]


def upgrade() -> None:
    connection = op.get_bind()
    Base.metadata.create_all(bind=connection, tables=_owned_tables(), checkfirst=False)

    for column in _added_columns():
        op.add_column("evidence_items", column, schema=_APP)

    op.create_check_constraint(
        "applicability_valid",
        "evidence_items",
        f"applicability IN ({_vocabulary(EvidenceApplicability)})",
        schema=_APP,
    )
    op.create_check_constraint(
        "state_valid",
        "evidence_items",
        f"state IN ({_vocabulary(EvidenceRecordState)})",
        schema=_APP,
    )
    op.create_foreign_key(
        "fk_evidence_items_ingestion_batch_id",
        "evidence_items",
        "evidence_ingestion_batches",
        ["ingestion_batch_id"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    op.create_index(
        "ix_evidence_items_source_key_source_version",
        "evidence_items",
        ["source_key", "source_version"],
        schema=_APP,
    )
    op.create_index(
        "ix_evidence_items_ingestion_batch_id",
        "evidence_items",
        ["ingestion_batch_id"],
        schema=_APP,
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_items_ingestion_batch_id", "evidence_items", schema=_APP)
    op.drop_index(
        "ix_evidence_items_source_key_source_version", "evidence_items", schema=_APP
    )
    op.drop_constraint(
        "fk_evidence_items_ingestion_batch_id",
        "evidence_items",
        type_="foreignkey",
        schema=_APP,
    )
    op.drop_constraint(
        "ck_evidence_items_state_valid", "evidence_items", type_="check", schema=_APP
    )
    op.drop_constraint(
        "ck_evidence_items_applicability_valid",
        "evidence_items",
        type_="check",
        schema=_APP,
    )
    for column in reversed(_added_columns()):
        op.drop_column("evidence_items", column.name, schema=_APP)

    connection = op.get_bind()
    Base.metadata.drop_all(
        bind=connection, tables=list(reversed(_owned_tables())), checkfirst=False
    )
