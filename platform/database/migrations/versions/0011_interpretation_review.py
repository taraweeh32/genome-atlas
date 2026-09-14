"""Interpretation review, adjudication and pinned decision content.

Additive revision on top of Packages 2-10. No existing table is rebuilt and no
existing data is destroyed.

Deliberately *not* created here:

* a second interpretation model — ``app.interpretations`` and
  ``app.interpretation_versions`` already exist and this revision only widens the
  version row with the decision role it carries and the automated evaluation it
  came from;
* a second review model — ``app.review_assignments`` and ``app.review_decisions``
  already exist and are widened with the review round, the attribution of the
  decision and the decision it resolved;
* a second criterion or evidence model — the new link tables point at
  ``app.criterion_evaluations`` and ``app.evidence_items``.

New tables:

* ``app.interpretation_version_criteria`` — the exact criterion evaluations one
  immutable interpretation version was decided from.
* ``app.interpretation_version_evidence`` — the exact evidence item versions that
  version rested on, including evidence retained as contradicting.

Revision ID: 0011_interpretation_review
Revises: 0010_interpretation_rulesets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.domain.value_objects.enums import ClassificationDecisionRole
from app.infrastructure.persistence.models import Base

revision = "0011_interpretation_review"
down_revision = "0010_interpretation_rulesets"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.interpretation_version_criteria",
    "app.interpretation_version_evidence",
)

_APP = "app"

_ROLE_VALUES = tuple(role.value for role in ClassificationDecisionRole)


def _version_columns() -> tuple[sa.Column, ...]:
    """Columns added to the immutable interpretation version row.

    Built fresh on each call: a ``Column`` object may only be attached to one
    table, so upgrade and downgrade cannot share instances. Every column is either
    nullable or carries a server default, so pre-existing rows stay valid.
    """
    return (
        sa.Column(
            "decision_role",
            sa.String(length=64),
            nullable=False,
            server_default=ClassificationDecisionRole.REVIEWER_DECISION.value,
        ),
        sa.Column("ruleset_id", sa.String(length=64), nullable=True),
        sa.Column("classification_evaluation_id", sa.String(length=64), nullable=True),
        sa.Column("automated_classification_id", sa.String(length=64), nullable=True),
        sa.Column("review_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("adjudicated_by", sa.String(length=64), nullable=True),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disagreement_summary", sa.JSON(), nullable=True),
    )


def _decision_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column(
            "decision_role",
            sa.String(length=64),
            nullable=False,
            server_default=ClassificationDecisionRole.REVIEWER_DECISION.value,
        ),
        sa.Column("review_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("previous_classification", sa.String(length=64), nullable=True),
        sa.Column("resolves_decision_id", sa.String(length=64), nullable=True),
    )


def _assignment_columns() -> tuple[sa.Column, ...]:
    return (sa.Column("review_round", sa.Integer(), nullable=False, server_default="1"),)


def _owned_tables() -> list:
    owned = set(TABLES)
    return [
        table
        for table in Base.metadata.sorted_tables
        if f"{table.schema or _APP}.{table.name}" in owned
    ]


def upgrade() -> None:
    connection = op.get_bind()

    for column in _version_columns():
        op.add_column("interpretation_versions", column, schema=_APP)
    for column in _decision_columns():
        op.add_column("review_decisions", column, schema=_APP)
    for column in _assignment_columns():
        op.add_column("review_assignments", column, schema=_APP)

    Base.metadata.create_all(bind=connection, tables=_owned_tables(), checkfirst=False)

    op.create_check_constraint(
        "ck_interpretation_versions_decision_role_valid",
        "interpretation_versions",
        sa.column("decision_role").in_(_ROLE_VALUES),
        schema=_APP,
    )
    op.create_check_constraint(
        "ck_review_decisions_decision_role_valid",
        "review_decisions",
        sa.column("decision_role").in_(_ROLE_VALUES),
        schema=_APP,
    )
    op.create_foreign_key(
        "fk_interpretation_versions_ruleset_id",
        "interpretation_versions",
        "interpretation_rulesets",
        ["ruleset_id"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    op.create_foreign_key(
        "fk_interpretation_versions_classification_evaluation_id",
        "interpretation_versions",
        "classification_evaluations",
        ["classification_evaluation_id"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    op.create_foreign_key(
        "fk_interpretation_versions_automated_classification_id",
        "interpretation_versions",
        "automated_classifications",
        ["automated_classification_id"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    op.create_foreign_key(
        "fk_interpretation_versions_adjudicated_by",
        "interpretation_versions",
        "users",
        ["adjudicated_by"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    # A superseded or withdrawn interpretation must not block a reclassification
    # from opening a fresh decision context for the same question.
    op.drop_constraint(
        "uq_interpretations_project_id_variant_id_condition_identifier",
        "interpretations",
        type_="unique",
        schema=_APP,
    )
    op.create_index(
        "uq_interpretations_open_context",
        "interpretations",
        ["project_id", "variant_id", "condition_identifier"],
        unique=True,
        schema=_APP,
        postgresql_where=sa.text("state NOT IN ('superseded', 'withdrawn')"),
    )
    op.create_index(
        "ix_review_decisions_interpretation_id_review_round",
        "review_decisions",
        ["interpretation_id", "review_round"],
        schema=_APP,
    )


def downgrade() -> None:
    op.drop_index("uq_interpretations_open_context", "interpretations", schema=_APP)
    op.create_unique_constraint(
        "uq_interpretations_project_id_variant_id_condition_identifier",
        "interpretations",
        ["project_id", "variant_id", "condition_identifier"],
        schema=_APP,
    )
    op.drop_index(
        "ix_review_decisions_interpretation_id_review_round",
        "review_decisions",
        schema=_APP,
    )
    for name in (
        "fk_interpretation_versions_adjudicated_by",
        "fk_interpretation_versions_automated_classification_id",
        "fk_interpretation_versions_classification_evaluation_id",
        "fk_interpretation_versions_ruleset_id",
    ):
        op.drop_constraint(name, "interpretation_versions", type_="foreignkey", schema=_APP)
    op.drop_constraint(
        "ck_review_decisions_decision_role_valid",
        "review_decisions",
        type_="check",
        schema=_APP,
    )
    op.drop_constraint(
        "ck_interpretation_versions_decision_role_valid",
        "interpretation_versions",
        type_="check",
        schema=_APP,
    )

    connection = op.get_bind()
    Base.metadata.drop_all(
        bind=connection, tables=list(reversed(_owned_tables())), checkfirst=False
    )

    for column in reversed(_assignment_columns()):
        op.drop_column("review_assignments", column.name, schema=_APP)
    for column in reversed(_decision_columns()):
        op.drop_column("review_decisions", column.name, schema=_APP)
    for column in reversed(_version_columns()):
        op.drop_column("interpretation_versions", column.name, schema=_APP)
