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

revision = "0011_interpretation_review"
down_revision = "0010_interpretation_rulesets"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.interpretation_version_criteria",
    "app.interpretation_version_evidence",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN decision_role VARCHAR(64) NOT NULL
    DEFAULT reviewer_decision
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN ruleset_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN classification_evaluation_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN automated_classification_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN review_round INTEGER NOT NULL DEFAULT 1
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN adjudicated_by VARCHAR(64)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN adjudicated_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE app.interpretation_versions ADD COLUMN disagreement_summary JSON
    """,
    """
    ALTER TABLE app.review_decisions ADD COLUMN decision_role VARCHAR(64) NOT NULL DEFAULT
    reviewer_decision
    """,
    """
    ALTER TABLE app.review_decisions ADD COLUMN review_round INTEGER NOT NULL DEFAULT 1
    """,
    """
    ALTER TABLE app.review_decisions ADD COLUMN previous_classification VARCHAR(64)
    """,
    """
    ALTER TABLE app.review_decisions ADD COLUMN resolves_decision_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.review_assignments ADD COLUMN review_round INTEGER NOT NULL DEFAULT 1
    """,
    """
    CREATE TABLE app.interpretation_version_criteria ( id VARCHAR(64) NOT NULL,
    interpretation_version_id VARCHAR(64) NOT NULL, criterion_evaluation_id VARCHAR(64) NOT
    NULL, display_order INTEGER, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT
    pk_interpretation_version_criteria PRIMARY KEY (id), CONSTRAINT
    fk_interpretation_version_criteria_criterion_evaluation_id FOREIGN
    KEY(criterion_evaluation_id) REFERENCES app.criterion_evaluations (id) ON DELETE RESTRICT,
    CONSTRAINT uq_interpretation_version_criteria_version_criterion UNIQUE
    (interpretation_version_id, criterion_evaluation_id), CONSTRAINT
    fk_interpretation_version_criteria_interpretation_version_id FOREIGN
    KEY(interpretation_version_id) REFERENCES app.interpretation_versions (id) ON DELETE
    RESTRICT )
    """,
    """
    CREATE INDEX ix_interpretation_version_criteria_criterion_evaluation_id ON
    app.interpretation_version_criteria (criterion_evaluation_id)
    """,
    """
    CREATE INDEX ix_interpretation_version_criteria_interpretation_version_id ON
    app.interpretation_version_criteria (interpretation_version_id)
    """,
    """
    CREATE TABLE app.interpretation_version_evidence ( id VARCHAR(64) NOT NULL,
    interpretation_version_id VARCHAR(64) NOT NULL, evidence_item_id VARCHAR(64) NOT NULL,
    relation VARCHAR(64) DEFAULT 'supports' NOT NULL, notes TEXT, created_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_interpretation_version_evidence PRIMARY KEY (id), CONSTRAINT
    fk_interpretation_version_evidence_interpretation_version_id FOREIGN
    KEY(interpretation_version_id) REFERENCES app.interpretation_versions (id) ON DELETE
    RESTRICT, CONSTRAINT uq_interpretation_version_evidence_version_evidence UNIQUE
    (interpretation_version_id, evidence_item_id), CONSTRAINT
    fk_interpretation_version_evidence_evidence_item_id FOREIGN KEY(evidence_item_id) REFERENCES
    app.evidence_items (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_interpretation_version_evidence_evidence_item_id ON
    app.interpretation_version_evidence (evidence_item_id)
    """,
    """
    CREATE INDEX ix_interpretation_version_evidence_interpretation_version_id ON
    app.interpretation_version_evidence (interpretation_version_id)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD CONSTRAINT
    ck_interpretation_versions_ck_interpretation_versions_decision_role_valid CHECK
    (decision_role IN (__[POSTCOMPILE_decision_role_1]))
    """,
    """
    ALTER TABLE app.review_decisions ADD CONSTRAINT
    ck_review_decisions_ck_review_decisions_decision_role_valid CHECK (decision_role IN
    (__[POSTCOMPILE_decision_role_1]))
    """,
    """
    ALTER TABLE app.interpretation_versions ADD CONSTRAINT fk_interpretation_versions_ruleset_id
    FOREIGN KEY (ruleset_id) REFERENCES app.interpretation_rulesets (id)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD CONSTRAINT
    fk_interpretation_versions_classification_evaluation_id FOREIGN KEY
    (classification_evaluation_id) REFERENCES app.classification_evaluations (id)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD CONSTRAINT
    fk_interpretation_versions_automated_classification_id FOREIGN KEY
    (automated_classification_id) REFERENCES app.automated_classifications (id)
    """,
    """
    ALTER TABLE app.interpretation_versions ADD CONSTRAINT
    fk_interpretation_versions_adjudicated_by FOREIGN KEY (adjudicated_by) REFERENCES app.users
    (id)
    """,
    """
    ALTER TABLE app.interpretations DROP CONSTRAINT
    uq_interpretations_project_id_variant_id_condition_identifier
    """,
    """
    CREATE UNIQUE INDEX uq_interpretations_open_context ON app.interpretations (project_id,
    variant_id, condition_identifier) WHERE state NOT IN ('superseded', 'withdrawn')
    """,
    """
    CREATE INDEX ix_review_decisions_interpretation_id_review_round ON app.review_decisions
    (interpretation_id, review_round)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP INDEX app.uq_interpretations_open_context
    """,
    """
    ALTER TABLE app.interpretations ADD CONSTRAINT
    uq_interpretations_project_id_variant_id_condition_identifier UNIQUE (project_id,
    variant_id, condition_identifier)
    """,
    """
    DROP INDEX app.ix_review_decisions_interpretation_id_review_round
    """,
    """
    ALTER TABLE app.interpretation_versions DROP CONSTRAINT
    fk_interpretation_versions_adjudicated_by
    """,
    """
    ALTER TABLE app.interpretation_versions DROP CONSTRAINT
    fk_interpretation_versions_automated_classification_id
    """,
    """
    ALTER TABLE app.interpretation_versions DROP CONSTRAINT
    fk_interpretation_versions_classification_evaluation_id
    """,
    """
    ALTER TABLE app.interpretation_versions DROP CONSTRAINT
    fk_interpretation_versions_ruleset_id
    """,
    """
    ALTER TABLE app.review_decisions DROP CONSTRAINT ck_review_decisions_decision_role_valid
    """,
    """
    ALTER TABLE app.interpretation_versions DROP CONSTRAINT
    ck_interpretation_versions_decision_role_valid
    """,
    """
    DROP TABLE app.interpretation_version_evidence
    """,
    """
    DROP TABLE app.interpretation_version_criteria
    """,
    """
    ALTER TABLE app.review_assignments DROP COLUMN review_round
    """,
    """
    ALTER TABLE app.review_decisions DROP COLUMN resolves_decision_id
    """,
    """
    ALTER TABLE app.review_decisions DROP COLUMN previous_classification
    """,
    """
    ALTER TABLE app.review_decisions DROP COLUMN review_round
    """,
    """
    ALTER TABLE app.review_decisions DROP COLUMN decision_role
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN disagreement_summary
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN adjudicated_at
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN adjudicated_by
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN review_round
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN automated_classification_id
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN classification_evaluation_id
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN ruleset_id
    """,
    """
    ALTER TABLE app.interpretation_versions DROP COLUMN decision_role
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
