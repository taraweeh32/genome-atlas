"""Interpretation ruleset registry, automated evaluations and benchmark cases.

Additive revision on top of Packages 2-9. No existing table is rebuilt and no
existing data is destroyed.

Deliberately *not* created here:

* a second criterion table — criterion evaluations stay ``app.criterion_evaluations``,
  the table Package 2 established. This revision widens it with the ruleset version,
  the criterion family and the automated evaluation it came out of;
* a second evidence link table — a criterion's evidence stays
  ``app.criterion_evaluation_evidence``;
* an interpretation or review table — the human decision layer already owns those,
  and nothing in this revision writes them.

New tables:

* ``app.interpretation_rulesets`` — one immutable registered ruleset version,
  unique on ``(ruleset_key, version)``, carrying its guideline source, citation,
  specification scope, effective dates, combination strategy and configuration
  digest.
* ``app.interpretation_criteria`` / ``app.interpretation_combination_rules`` — the
  criteria and combination rules that version declares, stored as data rather than
  as code, so a historical classification stays explainable against the exact rules
  it was produced under.
* ``app.classification_evaluations`` — one requested automated evaluation, freezing
  the pinned ruleset version and the exact evidence selection.
* ``app.automated_classifications`` — the suggested classification, constrained by
  check to ``automated_suggestion`` so this table can never hold a reviewer or
  adjudicated decision.
* ``app.ruleset_benchmark_cases`` / ``app.ruleset_benchmark_runs`` — controlled
  cases and runs for validating deterministic engine behaviour, with contract
  validation kept distinct from scientific accuracy.

Revision ID: 0010_interpretation_rulesets
Revises: 0009_evidence_layer
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.infrastructure.persistence.models import Base

revision = "0010_interpretation_rulesets"
down_revision = "0009_evidence_layer"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.interpretation_rulesets",
    "app.interpretation_criteria",
    "app.interpretation_combination_rules",
    "app.classification_evaluations",
    "app.automated_classifications",
    "app.ruleset_benchmark_cases",
    "app.ruleset_benchmark_runs",
)

_APP = "app"


def _added_columns() -> tuple[sa.Column, ...]:
    """Columns added to the existing criterion evaluation row.

    Built fresh on each call: a ``Column`` object may only be attached to one
    table, so upgrade and downgrade cannot share instances.

    All three are nullable. A human criterion evaluation exists without any
    automated evaluation behind it, and pre-existing rows must stay valid.
    """
    return (
        sa.Column("ruleset_id", sa.String(length=64), nullable=True),
        sa.Column("classification_evaluation_id", sa.String(length=64), nullable=True),
        sa.Column("family", sa.String(length=16), nullable=True),
    )


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
        op.add_column("criterion_evaluations", column, schema=_APP)

    op.create_foreign_key(
        "fk_criterion_evaluations_classification_evaluation_id",
        "criterion_evaluations",
        "classification_evaluations",
        ["classification_evaluation_id"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    op.create_foreign_key(
        "fk_criterion_evaluations_ruleset_id",
        "criterion_evaluations",
        "interpretation_rulesets",
        ["ruleset_id"],
        ["id"],
        source_schema=_APP,
        referent_schema=_APP,
    )
    op.create_index(
        "ix_criterion_evaluations_classification_evaluation_id",
        "criterion_evaluations",
        ["classification_evaluation_id"],
        schema=_APP,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_criterion_evaluations_classification_evaluation_id",
        "criterion_evaluations",
        schema=_APP,
    )
    op.drop_constraint(
        "fk_criterion_evaluations_ruleset_id",
        "criterion_evaluations",
        type_="foreignkey",
        schema=_APP,
    )
    op.drop_constraint(
        "fk_criterion_evaluations_classification_evaluation_id",
        "criterion_evaluations",
        type_="foreignkey",
        schema=_APP,
    )
    for column in reversed(_added_columns()):
        op.drop_column("criterion_evaluations", column.name, schema=_APP)

    connection = op.get_bind()
    Base.metadata.drop_all(
        bind=connection, tables=list(reversed(_owned_tables())), checkfirst=False
    )
