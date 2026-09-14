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

revision = "0010_interpretation_rulesets"
down_revision = "0009_evidence_layer"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``.
TABLES: tuple[str, ...] = (
    "app.interpretation_rulesets",
    "app.interpretation_criteria",
    "app.interpretation_combination_rules",
    "app.classification_evaluations",
    "app.automated_classifications",
    "app.ruleset_benchmark_cases",
    "app.ruleset_benchmark_runs",
)

#: Applied in order. Literal DDL, frozen at this revision.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app.interpretation_rulesets ( id VARCHAR(64) NOT NULL, ruleset_key VARCHAR(255)
    NOT NULL, version VARCHAR(128) NOT NULL, display_name VARCHAR(255) NOT NULL, description
    TEXT, guideline_source VARCHAR(255) NOT NULL, guideline_citation TEXT, publication_reference
    TEXT, publication_year INTEGER, state VARCHAR(64) DEFAULT 'registered' NOT NULL,
    specification_scope VARCHAR(64) DEFAULT 'general' NOT NULL, gene_symbol VARCHAR(128),
    condition_identifier VARCHAR(255), condition_term TEXT, combination_strategy VARCHAR(64)
    DEFAULT 'criteria_combination' NOT NULL, effective_from TIMESTAMP WITH TIME ZONE,
    effective_to TIMESTAMP WITH TIME ZONE, capability_id VARCHAR(255), capability_version
    VARCHAR(128), ruleset_resource_id VARCHAR(64), engine_resource_id VARCHAR(64),
    genome_assembly VARCHAR(64), configuration_digest VARCHAR(128), provenance JSONB,
    metadata_json JSONB, registered_by VARCHAR(64), activated_at TIMESTAMP WITH TIME ZONE,
    deprecated_at TIMESTAMP WITH TIME ZONE, retired_at TIMESTAMP WITH TIME ZONE, invalidated_at
    TIMESTAMP WITH TIME ZONE, invalidation_reason TEXT, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_interpretation_rulesets PRIMARY KEY (id), CONSTRAINT
    ck_interpretation_rulesets_state_valid CHECK (state IN ('registered', 'validating',
    'active', 'deprecated', 'retired', 'invalidated')), CONSTRAINT
    uq_interpretation_rulesets_ruleset_key_version UNIQUE (ruleset_key, version), CONSTRAINT
    fk_interpretation_rulesets_engine_resource_id FOREIGN KEY(engine_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    ck_interpretation_rulesets_combination_strategy_valid CHECK (combination_strategy IN
    ('criteria_combination', 'point_based', 'bayesian', 'external_specification')), CONSTRAINT
    ck_interpretation_rulesets_specification_scope_valid CHECK (specification_scope IN
    ('general', 'gene_specific', 'disease_specific', 'gene_disease_specific',
    'laboratory_specific')), CONSTRAINT fk_interpretation_rulesets_registered_by FOREIGN
    KEY(registered_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_interpretation_rulesets_ruleset_resource_id FOREIGN KEY(ruleset_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_interpretation_rulesets_engine_resource_id ON app.interpretation_rulesets
    (engine_resource_id)
    """,
    """
    CREATE INDEX ix_interpretation_rulesets_gene_symbol ON app.interpretation_rulesets
    (gene_symbol)
    """,
    """
    CREATE INDEX ix_interpretation_rulesets_registered_by ON app.interpretation_rulesets
    (registered_by)
    """,
    """
    CREATE INDEX ix_interpretation_rulesets_ruleset_resource_id ON app.interpretation_rulesets
    (ruleset_resource_id)
    """,
    """
    CREATE INDEX ix_interpretation_rulesets_state ON app.interpretation_rulesets (state)
    """,
    """
    CREATE TABLE app.interpretation_combination_rules ( id VARCHAR(64) NOT NULL, ruleset_id
    VARCHAR(64) NOT NULL, rule_key VARCHAR(128) NOT NULL, classification VARCHAR(64) NOT NULL,
    description TEXT, requirements JSONB, precedence INTEGER, created_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_interpretation_combination_rules PRIMARY KEY (id), CONSTRAINT
    fk_interpretation_combination_rules_ruleset_id FOREIGN KEY(ruleset_id) REFERENCES
    app.interpretation_rulesets (id) ON DELETE CASCADE, CONSTRAINT
    uq_interpretation_combination_rules_ruleset_id_rule_key UNIQUE (ruleset_id, rule_key),
    CONSTRAINT ck_interpretation_combination_rules_classification_valid CHECK (classification IN
    ('pathogenic', 'likely_pathogenic', 'uncertain_significance', 'likely_benign', 'benign',
    'not_classified')) )
    """,
    """
    CREATE INDEX ix_interpretation_combination_rules_ruleset_id ON
    app.interpretation_combination_rules (ruleset_id)
    """,
    """
    CREATE TABLE app.interpretation_criteria ( id VARCHAR(64) NOT NULL, ruleset_id VARCHAR(64)
    NOT NULL, criterion_key VARCHAR(64) NOT NULL, family VARCHAR(16) NOT NULL, direction
    VARCHAR(64) NOT NULL, default_strength VARCHAR(64) NOT NULL, description TEXT,
    permitted_strengths JSONB, evidence_categories JSONB, requires_evidence BOOLEAN DEFAULT
    'true' NOT NULL, display_order INTEGER, metadata_json JSONB, created_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_interpretation_criteria PRIMARY KEY (id), CONSTRAINT
    ck_interpretation_criteria_family_valid CHECK (family IN ('PVS', 'PS', 'PM', 'PP', 'BA',
    'BS', 'BP')), CONSTRAINT fk_interpretation_criteria_ruleset_id FOREIGN KEY(ruleset_id)
    REFERENCES app.interpretation_rulesets (id) ON DELETE CASCADE, CONSTRAINT
    ck_interpretation_criteria_direction_valid CHECK (direction IN ('pathogenic', 'benign',
    'neutral')), CONSTRAINT ck_interpretation_criteria_default_strength_valid CHECK
    (default_strength IN ('standalone', 'very_strong', 'strong', 'moderate', 'supporting',
    'not_applicable')), CONSTRAINT uq_interpretation_criteria_ruleset_id_criterion_key UNIQUE
    (ruleset_id, criterion_key) )
    """,
    """
    CREATE INDEX ix_interpretation_criteria_criterion_key ON app.interpretation_criteria
    (criterion_key)
    """,
    """
    CREATE INDEX ix_interpretation_criteria_ruleset_id ON app.interpretation_criteria
    (ruleset_id)
    """,
    """
    CREATE TABLE app.ruleset_benchmark_cases ( id VARCHAR(64) NOT NULL, ruleset_id VARCHAR(64)
    NOT NULL, case_key VARCHAR(255) NOT NULL, validation_kind VARCHAR(64) NOT NULL, description
    TEXT, input_snapshot JSONB, expected_criteria JSONB, expected_classification VARCHAR(64),
    source_reference TEXT, is_active BOOLEAN DEFAULT 'true' NOT NULL, created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_ruleset_benchmark_cases PRIMARY KEY (id),
    CONSTRAINT uq_ruleset_benchmark_cases_ruleset_id_case_key UNIQUE (ruleset_id, case_key),
    CONSTRAINT fk_ruleset_benchmark_cases_created_by FOREIGN KEY(created_by) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_ruleset_benchmark_cases_ruleset_id FOREIGN
    KEY(ruleset_id) REFERENCES app.interpretation_rulesets (id) ON DELETE CASCADE, CONSTRAINT
    ck_ruleset_benchmark_cases_validation_kind_valid CHECK (validation_kind IN ('contract',
    'scientific_accuracy')) )
    """,
    """
    CREATE INDEX ix_ruleset_benchmark_cases_created_by ON app.ruleset_benchmark_cases
    (created_by)
    """,
    """
    CREATE INDEX ix_ruleset_benchmark_cases_ruleset_id ON app.ruleset_benchmark_cases
    (ruleset_id)
    """,
    """
    CREATE INDEX ix_ruleset_benchmark_cases_ruleset_id_is_active ON app.ruleset_benchmark_cases
    (ruleset_id, is_active)
    """,
    """
    CREATE TABLE app.ruleset_benchmark_runs ( id VARCHAR(64) NOT NULL, ruleset_id VARCHAR(64)
    NOT NULL, ruleset_key VARCHAR(255) NOT NULL, ruleset_version VARCHAR(128) NOT NULL,
    validation_kind VARCHAR(64) NOT NULL, case_count INTEGER DEFAULT '0' NOT NULL, matched_count
    INTEGER DEFAULT '0' NOT NULL, mismatched_count INTEGER DEFAULT '0' NOT NULL,
    not_evaluated_count INTEGER DEFAULT '0' NOT NULL, comparisons JSONB, is_accuracy_run BOOLEAN
    DEFAULT 'false' NOT NULL, executed_by VARCHAR(64), executed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME
    ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_ruleset_benchmark_runs PRIMARY KEY (id),
    CONSTRAINT fk_ruleset_benchmark_runs_executed_by FOREIGN KEY(executed_by) REFERENCES
    app.users (id) ON DELETE RESTRICT, CONSTRAINT fk_ruleset_benchmark_runs_ruleset_id FOREIGN
    KEY(ruleset_id) REFERENCES app.interpretation_rulesets (id) ON DELETE RESTRICT, CONSTRAINT
    ck_ruleset_benchmark_runs_validation_kind_valid CHECK (validation_kind IN ('contract',
    'scientific_accuracy')) )
    """,
    """
    CREATE INDEX ix_ruleset_benchmark_runs_executed_by ON app.ruleset_benchmark_runs
    (executed_by)
    """,
    """
    CREATE INDEX ix_ruleset_benchmark_runs_ruleset_id ON app.ruleset_benchmark_runs (ruleset_id)
    """,
    """
    CREATE TABLE app.classification_evaluations ( id VARCHAR(64) NOT NULL, workspace_id
    VARCHAR(64) NOT NULL, project_id VARCHAR(64), variant_id VARCHAR(64) NOT NULL, ruleset_id
    VARCHAR(64) NOT NULL, ruleset_key VARCHAR(255) NOT NULL, ruleset_version VARCHAR(128) NOT
    NULL, state VARCHAR(64) DEFAULT 'requested' NOT NULL, gene_symbol VARCHAR(128),
    transcript_identifier VARCHAR(128), condition_identifier VARCHAR(255), condition_term TEXT,
    inheritance VARCHAR(128), genome_assembly VARCHAR(64), reference_genome_resource_id
    VARCHAR(64), evidence_ids JSONB, input_digest VARCHAR(128), configuration_digest
    VARCHAR(128), capability_id VARCHAR(255), capability_version VARCHAR(128),
    engine_resource_id VARCHAR(64), engine_version VARCHAR(128), environment_version
    VARCHAR(128), container_image_digest VARCHAR(256), node_identity VARCHAR(255),
    scientific_execution_id VARCHAR(64), job_id VARCHAR(64), correlation_id VARCHAR(128),
    idempotency_key VARCHAR(255), requested_by VARCHAR(64), requested_at TIMESTAMP WITH TIME
    ZONE, submitted_at TIMESTAMP WITH TIME ZONE, completed_at TIMESTAMP WITH TIME ZONE,
    classification_id VARCHAR(64), failure_code VARCHAR(128), failure_message TEXT,
    benchmark_case_id VARCHAR(64), metadata_json JSONB, created_at TIMESTAMP WITH TIME ZONE
    DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, version
    INTEGER DEFAULT '1' NOT NULL, CONSTRAINT pk_classification_evaluations PRIMARY KEY (id),
    CONSTRAINT fk_classification_evaluations_scientific_execution_id FOREIGN
    KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_classification_evaluations_reference_genome_resource_id FOREIGN
    KEY(reference_genome_resource_id) REFERENCES app.scientific_resources (id) ON DELETE
    RESTRICT, CONSTRAINT fk_classification_evaluations_variant_id FOREIGN KEY(variant_id)
    REFERENCES app.variants (id) ON DELETE RESTRICT, CONSTRAINT
    fk_classification_evaluations_workspace_id FOREIGN KEY(workspace_id) REFERENCES
    app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT ck_classification_evaluations_state_valid
    CHECK (state IN ('requested', 'submitted', 'running', 'ingesting', 'completed', 'failed',
    'cancelled')), CONSTRAINT uq_classification_evaluations_workspace_id_idempotency_key UNIQUE
    (workspace_id, idempotency_key), CONSTRAINT fk_classification_evaluations_requested_by
    FOREIGN KEY(requested_by) REFERENCES app.users (id) ON DELETE RESTRICT, CONSTRAINT
    fk_classification_evaluations_engine_resource_id FOREIGN KEY(engine_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_classification_evaluations_ruleset_id FOREIGN KEY(ruleset_id) REFERENCES
    app.interpretation_rulesets (id) ON DELETE RESTRICT, CONSTRAINT
    fk_classification_evaluations_project_id FOREIGN KEY(project_id) REFERENCES app.projects
    (id) ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_classification_evaluations_engine_resource_id ON
    app.classification_evaluations (engine_resource_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_input_digest ON app.classification_evaluations
    (input_digest)
    """,
    """
    CREATE INDEX ix_classification_evaluations_project_id ON app.classification_evaluations
    (project_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_reference_genome_resource_id ON
    app.classification_evaluations (reference_genome_resource_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_requested_by ON app.classification_evaluations
    (requested_by)
    """,
    """
    CREATE INDEX ix_classification_evaluations_ruleset_id ON app.classification_evaluations
    (ruleset_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_scientific_execution_id ON
    app.classification_evaluations (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_variant_id ON app.classification_evaluations
    (variant_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_workspace_id ON app.classification_evaluations
    (workspace_id)
    """,
    """
    CREATE INDEX ix_classification_evaluations_workspace_id_state ON
    app.classification_evaluations (workspace_id, state)
    """,
    """
    CREATE TABLE app.automated_classifications ( id VARCHAR(64) NOT NULL, evaluation_id
    VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL, project_id VARCHAR(64), variant_id
    VARCHAR(64) NOT NULL, ruleset_id VARCHAR(64) NOT NULL, ruleset_key VARCHAR(255) NOT NULL,
    ruleset_version VARCHAR(128) NOT NULL, classification VARCHAR(64) NOT NULL, version_number
    INTEGER DEFAULT '1' NOT NULL, decision_role VARCHAR(64) DEFAULT 'automated_suggestion' NOT
    NULL, combination_rule_key VARCHAR(128), rationale TEXT, gene_symbol VARCHAR(128),
    condition_identifier VARCHAR(255), applied_criterion_keys JSONB, criterion_evaluation_ids
    JSONB, evidence_ids JSONB, computation JSONB, engine_resource_id VARCHAR(64), engine_version
    VARCHAR(128), environment_version VARCHAR(128), container_image_digest VARCHAR(256),
    node_identity VARCHAR(255), scientific_execution_id VARCHAR(64), contract_version
    VARCHAR(32), input_digest VARCHAR(128), configuration_digest VARCHAR(128), payload_digest
    VARCHAR(128), provenance JSONB, supersedes_id VARCHAR(64), superseded_by_id VARCHAR(64),
    is_development_payload BOOLEAN DEFAULT 'false' NOT NULL, produced_at TIMESTAMP WITH TIME
    ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, updated_at TIMESTAMP WITH
    TIME ZONE DEFAULT now() NOT NULL, CONSTRAINT pk_automated_classifications PRIMARY KEY (id),
    CONSTRAINT uq_automated_classifications_evaluation_id_version_number UNIQUE (evaluation_id,
    version_number), CONSTRAINT fk_automated_classifications_workspace_id FOREIGN
    KEY(workspace_id) REFERENCES app.workspaces (id) ON DELETE RESTRICT, CONSTRAINT
    ck_automated_classifications_decision_role_valid CHECK (decision_role IN
    ('automated_suggestion', 'reviewer_decision', 'adjudicated_decision',
    'final_interpretation')), CONSTRAINT fk_automated_classifications_scientific_execution_id
    FOREIGN KEY(scientific_execution_id) REFERENCES app.scientific_executions (id) ON DELETE
    RESTRICT, CONSTRAINT fk_automated_classifications_ruleset_id FOREIGN KEY(ruleset_id)
    REFERENCES app.interpretation_rulesets (id) ON DELETE RESTRICT, CONSTRAINT
    fk_automated_classifications_project_id FOREIGN KEY(project_id) REFERENCES app.projects (id)
    ON DELETE RESTRICT, CONSTRAINT ck_automated_classifications_classification_valid CHECK
    (classification IN ('pathogenic', 'likely_pathogenic', 'uncertain_significance',
    'likely_benign', 'benign', 'not_classified')), CONSTRAINT
    fk_automated_classifications_evaluation_id FOREIGN KEY(evaluation_id) REFERENCES
    app.classification_evaluations (id) ON DELETE RESTRICT, CONSTRAINT
    fk_automated_classifications_engine_resource_id FOREIGN KEY(engine_resource_id) REFERENCES
    app.scientific_resources (id) ON DELETE RESTRICT, CONSTRAINT
    fk_automated_classifications_variant_id FOREIGN KEY(variant_id) REFERENCES app.variants (id)
    ON DELETE RESTRICT )
    """,
    """
    CREATE INDEX ix_automated_classifications_engine_resource_id ON
    app.automated_classifications (engine_resource_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_evaluation_id ON app.automated_classifications
    (evaluation_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_project_id ON app.automated_classifications
    (project_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_ruleset_id ON app.automated_classifications
    (ruleset_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_scientific_execution_id ON
    app.automated_classifications (scientific_execution_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_variant_id ON app.automated_classifications
    (variant_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_variant_id_ruleset_id ON
    app.automated_classifications (variant_id, ruleset_id)
    """,
    """
    CREATE INDEX ix_automated_classifications_workspace_id ON app.automated_classifications
    (workspace_id)
    """,
    """
    ALTER TABLE app.criterion_evaluations ADD COLUMN ruleset_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.criterion_evaluations ADD COLUMN classification_evaluation_id VARCHAR(64)
    """,
    """
    ALTER TABLE app.criterion_evaluations ADD COLUMN family VARCHAR(16)
    """,
    """
    ALTER TABLE app.criterion_evaluations ADD CONSTRAINT
    fk_criterion_evaluations_classification_evaluation_id FOREIGN KEY
    (classification_evaluation_id) REFERENCES app.classification_evaluations (id)
    """,
    """
    ALTER TABLE app.criterion_evaluations ADD CONSTRAINT fk_criterion_evaluations_ruleset_id
    FOREIGN KEY (ruleset_id) REFERENCES app.interpretation_rulesets (id)
    """,
    """
    CREATE INDEX ix_criterion_evaluations_classification_evaluation_id ON
    app.criterion_evaluations (classification_evaluation_id)
    """,
)

#: Exact inverse of ``UPGRADE_STATEMENTS``, in reverse dependency order.
DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """
    DROP INDEX app.ix_criterion_evaluations_classification_evaluation_id
    """,
    """
    ALTER TABLE app.criterion_evaluations DROP CONSTRAINT fk_criterion_evaluations_ruleset_id
    """,
    """
    ALTER TABLE app.criterion_evaluations DROP CONSTRAINT
    fk_criterion_evaluations_classification_evaluation_id
    """,
    """
    ALTER TABLE app.criterion_evaluations DROP COLUMN family
    """,
    """
    ALTER TABLE app.criterion_evaluations DROP COLUMN classification_evaluation_id
    """,
    """
    ALTER TABLE app.criterion_evaluations DROP COLUMN ruleset_id
    """,
    """
    DROP TABLE app.automated_classifications
    """,
    """
    DROP TABLE app.classification_evaluations
    """,
    """
    DROP TABLE app.ruleset_benchmark_runs
    """,
    """
    DROP TABLE app.ruleset_benchmark_cases
    """,
    """
    DROP TABLE app.interpretation_criteria
    """,
    """
    DROP TABLE app.interpretation_combination_rules
    """,
    """
    DROP TABLE app.interpretation_rulesets
    """,
)

def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
