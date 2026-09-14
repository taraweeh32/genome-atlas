"""Ruleset registry, automated evaluation and benchmark persistence.

Deliberately *not* here:

* the ruleset resource itself — a registered ruleset version is also a row in
  ``scientific_resources`` (kind ``ruleset``), so it shares the lifecycle of
  genomes, engines, annotation resources and evidence sources;
* criterion evaluations — those are ``criterion_evaluations`` rows from Package 2,
  widened by this package rather than replaced. No second criterion model exists;
* interpretations and human review — those tables already exist and belong to the
  human decision layer. Nothing here writes them.

What is added is the ruleset's own declared content (criteria, combination rules),
the record of one requested automated evaluation, the suggested classification it
produced, and the controlled benchmark cases used to check that the engine behaves
deterministically under a given ruleset version.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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
    BenchmarkCaseOutcome,
    BenchmarkValidationKind,
    Classification,
    ClassificationDecisionRole,
    ClassificationEvaluationState,
    CriterionDirection,
    CriterionFamily,
    CriterionStrength,
    RulesetCombinationStrategy,
    RulesetSpecificationScope,
    ScientificResourceState,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class InterpretationRulesetRow(Base, TimestampMixin):
    """One immutable, registered version of one interpretation ruleset.

    No optimistic-concurrency counter: ``version`` here is the *ruleset's own*
    scientific version, and a registered version is immutable. Only the lifecycle
    state changes, and that transition is validated against the current state
    rather than against a row counter.

    ``uq_interpretation_rulesets_ruleset_key_version`` is the identity a stored
    classification names. Because a version's criteria and combination rules are
    never edited, a historical result stays explainable against the exact rules it
    was produced under; a corrected guideline is registered as a new version.
    """

    __tablename__ = "interpretation_rulesets"
    __table_args__ = (
        UniqueConstraint(
            "ruleset_key", "version",
            name="uq_interpretation_rulesets_ruleset_key_version",
        ),
        state_check("state", ScientificResourceState, "state_valid"),
        state_check("specification_scope", RulesetSpecificationScope,
                    "specification_scope_valid"),
        state_check("combination_strategy", RulesetCombinationStrategy,
                    "combination_strategy_valid"),
        Index("ix_interpretation_rulesets_state", "state"),
        Index("ix_interpretation_rulesets_gene_symbol", "gene_symbol"),
    )

    id: Mapped[str] = id_column()
    ruleset_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Mandatory: a ruleset with no stated guideline source cannot be defended.
    guideline_source: Mapped[str] = mapped_column(String(255), nullable=False)
    guideline_citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ScientificResourceState.REGISTERED.value
    )
    specification_scope: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=RulesetSpecificationScope.GENERAL.value
    )
    #: Gene/disease context of a specification-scoped version (a ClinGen VCEP
    #: specification, for example). Null for a general framework version.
    gene_symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    condition_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    combination_strategy: Mapped[str] = mapped_column(
        String(64), nullable=False,
        server_default=RulesetCombinationStrategy.CRITERIA_COMBINATION.value,
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The capability the scientific rules engine must declare to evaluate it.
    capability_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capability_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Companion row in the shared scientific resource registry.
    ruleset_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    genome_assembly: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Digest over criteria, combination rules and strategy: recorded on every
    #: evaluation so a silently different configuration becomes detectable.
    configuration_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provenance: Mapped[dict | None] = json_column()
    metadata_json: Mapped[dict | None] = json_column()
    registered_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class InterpretationCriterionRow(Base, TimestampMixin):
    """One criterion a ruleset version declares.

    The permitted strengths are stored explicitly, so a specification that allows a
    criterion at a modified strength says so as data. The platform never invents a
    rule about which modifications are acceptable.
    """

    __tablename__ = "interpretation_criteria"
    __table_args__ = (
        UniqueConstraint(
            "ruleset_id", "criterion_key",
            name="uq_interpretation_criteria_ruleset_id_criterion_key",
        ),
        state_check("family", CriterionFamily, "family_valid"),
        state_check("direction", CriterionDirection, "direction_valid"),
        state_check("default_strength", CriterionStrength, "default_strength_valid"),
        Index("ix_interpretation_criteria_criterion_key", "criterion_key"),
    )

    id: Mapped[str] = id_column()
    ruleset_id: Mapped[str] = fk_column("app.interpretation_rulesets.id", ondelete="CASCADE")
    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    default_strength: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permitted_strengths: Mapped[dict | None] = json_column()
    evidence_categories: Mapped[dict | None] = json_column()
    requires_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class InterpretationCombinationRuleRow(Base, TimestampMixin):
    """One declared way a ruleset version reaches a classification.

    ``requirements`` is structured data describing the version's own stated
    conditions. The scientific component applies it; nothing in the application
    evaluates it, and there is no hidden scoring anywhere in this schema.
    """

    __tablename__ = "interpretation_combination_rules"
    __table_args__ = (
        UniqueConstraint(
            "ruleset_id", "rule_key",
            name="uq_interpretation_combination_rules_ruleset_id_rule_key",
        ),
        state_check("classification", Classification, "classification_valid"),
    )

    id: Mapped[str] = id_column()
    ruleset_id: Mapped[str] = fk_column("app.interpretation_rulesets.id", ondelete="CASCADE")
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[dict | None] = json_column()
    precedence: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ClassificationEvaluationRow(Base, TimestampMixin, ConcurrencyMixin):
    """One requested automated evaluation of one variant under one ruleset version.

    The evaluation freezes its own question: the pinned ruleset version, the exact
    evidence selection, and a digest over both. Evidence changing afterwards cannot
    alter what this evaluation claims to have considered — which is what makes a
    historical result reproducible rather than merely stored.
    """

    __tablename__ = "classification_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key",
            name="uq_classification_evaluations_workspace_id_idempotency_key",
        ),
        state_check("state", ClassificationEvaluationState, "state_valid"),
        Index("ix_classification_evaluations_workspace_id_state", "workspace_id", "state"),
        Index("ix_classification_evaluations_input_digest", "input_digest"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    variant_id: Mapped[str] = fk_column("app.variants.id")
    ruleset_id: Mapped[str] = fk_column("app.interpretation_rulesets.id")
    #: Also stored as strings, so the evaluation stays attributable if the registry
    #: row is later retired.
    ruleset_key: Mapped[str] = mapped_column(String(255), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False,
        server_default=ClassificationEvaluationState.REQUESTED.value,
    )
    gene_symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcript_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    condition_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    inheritance: Mapped[str | None] = mapped_column(String(128), nullable=True)
    genome_assembly: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    #: The exact evidence records handed to the engine.
    evidence_ids: Mapped[dict | None] = json_column()
    input_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    configuration_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capability_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capability_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_image_digest: Mapped[str | None] = mapped_column(String(256), nullable=True)
    node_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Set when a benchmark run, rather than a user, requested this evaluation.
    benchmark_case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class AutomatedClassificationRow(Base, TimestampMixin):
    """One suggested classification produced by the rules engine.

    ``decision_role`` is constrained to ``automated_suggestion``: this table cannot
    hold a reviewer decision, an adjudication or a finalized interpretation. Those
    live in the interpretation and review tables, and the distinction is enforced
    by the database rather than by convention.

    Re-evaluation never overwrites. A newer suggestion supersedes the previous one
    through ``supersedes_id`` / ``superseded_by_id`` and the older row stays
    readable exactly as produced.
    """

    __tablename__ = "automated_classifications"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "version_number",
            name="uq_automated_classifications_evaluation_id_version_number",
        ),
        state_check("classification", Classification, "classification_valid"),
        state_check("decision_role", ClassificationDecisionRole, "decision_role_valid"),
        Index("ix_automated_classifications_variant_id_ruleset_id",
              "variant_id", "ruleset_id"),
    )

    id: Mapped[str] = id_column()
    evaluation_id: Mapped[str] = fk_column("app.classification_evaluations.id")
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    variant_id: Mapped[str] = fk_column("app.variants.id")
    ruleset_id: Mapped[str] = fk_column("app.interpretation_rulesets.id")
    ruleset_key: Mapped[str] = mapped_column(String(255), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    decision_role: Mapped[str] = mapped_column(
        String(64), nullable=False,
        server_default=ClassificationDecisionRole.AUTOMATED_SUGGESTION.value,
    )
    combination_rule_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    gene_symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    condition_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    applied_criterion_keys: Mapped[dict | None] = json_column()
    criterion_evaluation_ids: Mapped[dict | None] = json_column()
    evidence_ids: Mapped[dict | None] = json_column()
    #: Strategy-specific working the engine chose to show. Stored verbatim and
    #: never recomputed by the application.
    computation: Mapped[dict | None] = json_column()
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_image_digest: Mapped[str | None] = mapped_column(String(256), nullable=True)
    node_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    contract_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    configuration_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provenance: Mapped[dict | None] = json_column()
    supersedes_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: True when a development/stand-in adapter produced it. Surfaced wherever the
    #: suggestion is shown, so it can never pass for a scientific evaluation.
    is_development_payload: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    produced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RulesetBenchmarkCaseRow(Base, TimestampMixin):
    """One controlled case used to check a ruleset version's engine behaviour.

    ``validation_kind`` is the honesty guard: a case counts as
    ``scientific_accuracy`` only when ``source_reference`` names the external
    reference corpus its expected outputs came from. Everything else validates
    determinism and contract shape and is reported as exactly that.
    """

    __tablename__ = "ruleset_benchmark_cases"
    __table_args__ = (
        UniqueConstraint(
            "ruleset_id", "case_key",
            name="uq_ruleset_benchmark_cases_ruleset_id_case_key",
        ),
        state_check("validation_kind", BenchmarkValidationKind, "validation_kind_valid"),
        Index("ix_ruleset_benchmark_cases_ruleset_id_is_active", "ruleset_id", "is_active"),
    )

    id: Mapped[str] = id_column()
    ruleset_id: Mapped[str] = fk_column("app.interpretation_rulesets.id", ondelete="CASCADE")
    case_key: Mapped[str] = mapped_column(String(255), nullable=False)
    validation_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Fixture input: variant identity, context and evidence claims. Data only,
    #: and never real patient content.
    input_snapshot: Mapped[dict | None] = json_column()
    expected_criteria: Mapped[dict | None] = json_column()
    expected_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Where the expected outputs came from. Required for accuracy cases.
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class RulesetBenchmarkRunRow(Base, TimestampMixin):
    """One execution of a ruleset version's benchmark cases.

    ``is_accuracy_run`` is only true when every executed case was an accuracy case
    with a declared reference corpus, so a contract run can never be presented as
    a clinical accuracy measurement.
    """

    __tablename__ = "ruleset_benchmark_runs"
    __table_args__ = (
        state_check("validation_kind", BenchmarkValidationKind, "validation_kind_valid"),
    )

    id: Mapped[str] = id_column()
    ruleset_id: Mapped[str] = fk_column("app.interpretation_rulesets.id")
    ruleset_key: Mapped[str] = mapped_column(String(255), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    validation_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mismatched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    not_evaluated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: Per-case comparison outcomes, using the ``BenchmarkCaseOutcome`` vocabulary.
    comparisons: Mapped[dict | None] = json_column()
    is_accuracy_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    executed_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


#: Referenced so the vocabulary stays imported alongside the rows that use it in
#: their stored comparison payloads.
BENCHMARK_OUTCOME_VOCABULARY = BenchmarkCaseOutcome

__all__ = [
    "AutomatedClassificationRow",
    "ClassificationEvaluationRow",
    "InterpretationCombinationRuleRow",
    "InterpretationCriterionRow",
    "InterpretationRulesetRow",
    "RulesetBenchmarkCaseRow",
    "RulesetBenchmarkRunRow",
]
