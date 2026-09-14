"""Evidence, criterion evaluations, interpretations and human review.

Separation enforced by the schema:

* ``evidence_items`` — a discrete piece of evidence with its own origin.
* ``criterion_evaluations`` — an evaluation of one ruleset criterion, always
  labelled automated or human, never merged.
* ``interpretations`` / ``interpretation_versions`` — the definition and its
  immutable versions; a reclassification creates a new version.
* ``review_assignments`` / ``review_decisions`` — the human review workflow,
  including override and adjudication, each recorded separately.

The ACMG/AMP ruleset logic itself lives in the scientific subsystem; this schema
stores what was evaluated, by whom or by what, under which ruleset version.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    Classification,
    ClassificationDecisionRole,
    CriterionDirection,
    CriterionStrength,
    DataOrigin,
    DeletionState,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceRecordState,
    EvidenceStrength,
    InterpretationState,
    ReviewState,
)
from app.domain.value_objects.enums import (
    ReviewDecision as ReviewDecisionVocabulary,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    RetentionMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class EvidenceItem(Base, TimestampMixin, ConcurrencyMixin):
    """A discrete piece of evidence attached to a variant (optionally scoped)."""

    __tablename__ = "evidence_items"
    __table_args__ = (
        state_check("category", EvidenceCategory, "category_valid"),
        state_check("strength", EvidenceStrength, "strength_valid"),
        state_check("direction", CriterionDirection, "direction_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        state_check("applicability", EvidenceApplicability, "applicability_valid"),
        state_check("state", EvidenceRecordState, "state_valid"),
        Index("ix_evidence_items_workspace_id_project_id", "workspace_id", "project_id"),
        Index("ix_evidence_items_source_key_source_version", "source_key", "source_version"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    #: Personal/organization scope; platform-wide evidence leaves these null.
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    strength: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=EvidenceStrength.NOT_APPLICABLE.value
    )
    direction: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=CriterionDirection.NEUTRAL.value
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Where the evidence came from: source resource, external assertion, human.
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    source_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    clinical_assertion_id: Mapped[str | None] = fk_column(
        "app.clinical_assertions.id", nullable=True
    )
    external_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict | None] = json_column()

    # ---- Package 9: source identity, context, lifecycle and versioning ----
    #: Source identity as strings as well as by foreign key, so a record stays
    #: readable and attributable even if the registry row is later retired.
    source_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: The source's own identifier for this statement (accession, PMID, record id).
    source_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Retrieval/import time, which is not the source's release time.
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gene_symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gene_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcript_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    condition_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    inheritance: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Stated by the source or a curator; never inferred by the platform.
    applicability: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=EvidenceApplicability.UNDETERMINED.value
    )
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=EvidenceRecordState.RECORDED.value
    )
    #: How the value was obtained (assay, curation protocol, computation name).
    method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Stable key for "the same statement" within one source across releases.
    evidence_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    #: A newer version links back; the older row is never rewritten in content.
    supersedes_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingestion_batch_id: Mapped[str | None] = fk_column(
        "app.evidence_ingestion_batches.id", nullable=True
    )
    #: Digest of the claim as delivered: the unit of duplicate detection.
    payload_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provenance: Mapped[dict | None] = json_column()


class CriterionEvaluation(Base, TimestampMixin, ConcurrencyMixin):
    """Evaluation of one ruleset criterion for a variant in a given context."""

    __tablename__ = "criterion_evaluations"
    __table_args__ = (
        state_check("strength", CriterionStrength, "strength_valid"),
        state_check("direction", CriterionDirection, "direction_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_criterion_evaluations_interpretation_id", "interpretation_id"),
        Index("ix_criterion_evaluations_criterion_key", "criterion_key"),
        Index("ix_criterion_evaluations_classification_evaluation_id",
              "classification_evaluation_id"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    interpretation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interpretation_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Ruleset identity is mandatory: a criterion has no meaning without it.
    ruleset_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Package 10: the registered ruleset version and the automated evaluation this
    #: criterion came out of. Both nullable, because a human evaluation is recorded
    #: without any automated evaluation behind it.
    ruleset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app.interpretation_rulesets.id", ondelete="RESTRICT"), nullable=True
    )
    classification_evaluation_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app.classification_evaluations.id", ondelete="RESTRICT"), nullable=True
    )
    #: Criterion family, denormalized from the ruleset version so a stored
    #: evaluation stays readable on its own.
    family: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    strength: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=CriterionStrength.NOT_APPLICABLE.value
    )
    direction: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=CriterionDirection.NEUTRAL.value
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Automated suggestion vs human evaluation stays distinguishable forever.
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_by_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    evaluation_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: A human evaluation that supersedes an automated suggestion links to it.
    supersedes_evaluation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = json_column()


class CriterionEvaluationEvidence(Base, TimestampMixin):
    """Links an evaluation to the evidence it rests on."""

    __tablename__ = "criterion_evaluation_evidence"
    __table_args__ = (
        UniqueConstraint("criterion_evaluation_id", "evidence_item_id",
                         name="uq_criterion_evaluation_evidence_evaluation_id_evidence_id"),
    )

    id: Mapped[str] = id_column()
    criterion_evaluation_id: Mapped[str] = fk_column(
        "app.criterion_evaluations.id", ondelete="CASCADE"
    )
    evidence_item_id: Mapped[str] = fk_column("app.evidence_items.id")
    #: ``supports`` | ``contradicts`` | ``context``. Conflicts are retained.
    relation: Mapped[str] = mapped_column(String(64), nullable=False, server_default="supports")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Interpretation(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """Interpretation definition for a variant within a project context."""

    __tablename__ = "interpretations"
    __table_args__ = (
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        # One *open* decision context per variant and condition. A superseded or
        # withdrawn record must stay in place — a reclassification opens a new
        # context for the same question and the old one remains citable.
        Index(
            "uq_interpretations_open_context",
            "project_id", "variant_id", "condition_identifier",
            unique=True,
            postgresql_where=text("state NOT IN ('superseded', 'withdrawn')"),
        ),
        state_check("state", InterpretationState, "state_valid"),
        state_check("review_state", ReviewState, "review_state_valid"),
        Index("ix_interpretations_workspace_id_state", "workspace_id", "state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    variant_id: Mapped[str] = fk_column("app.variants.id")
    sample_id: Mapped[str | None] = fk_column("app.samples.id", nullable=True)
    condition_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    condition_term: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Operational lifecycle, separate from the review lifecycle.
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InterpretationState.DRAFT.value
    )
    review_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ReviewState.NOT_STARTED.value
    )
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_by: Mapped[str] = fk_column("app.users.id")


class InterpretationVersion(Base, TimestampMixin):
    """Immutable interpretation version. Reclassification adds a new row."""

    __tablename__ = "interpretation_versions"
    __table_args__ = (
        UniqueConstraint("interpretation_id", "version_number",
                         name="uq_interpretation_versions_interpretation_id_version_number"),
        state_check("classification", Classification, "classification_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        state_check("decision_role", ClassificationDecisionRole, "decision_role_valid"),
    )

    id: Mapped[str] = id_column()
    interpretation_id: Mapped[str] = fk_column("app.interpretations.id")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=Classification.NOT_CLASSIFIED.value
    )
    #: Automated suggestion that this version accepted, modified or rejected.
    suggested_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinical_significance_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    ruleset_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    ruleset_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reference_genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    provenance_manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Full snapshot: criteria, evidence, conflicts, resource identities.
    evaluation_snapshot: Mapped[dict | None] = json_column()
    #: Conflicting evidence is recorded, never discarded.
    conflict_summary: Mapped[dict | None] = json_column()
    authored_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    finalized_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reclassification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Package 11: which decision this version *is*, and what it came from ----
    #: An automated suggestion, a reviewer decision, an adjudicated decision and a
    #: finalized interpretation are four different things and stay distinguishable.
    decision_role: Mapped[str] = mapped_column(
        String(64), nullable=False,
        server_default=ClassificationDecisionRole.REVIEWER_DECISION.value,
    )
    #: The registered ruleset version and the automated evaluation this decision
    #: context was built on. Nullable: a version may be authored without one.
    ruleset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app.interpretation_rulesets.id", ondelete="RESTRICT"), nullable=True
    )
    classification_evaluation_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app.classification_evaluations.id", ondelete="RESTRICT"), nullable=True
    )
    automated_classification_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app.automated_classifications.id", ondelete="RESTRICT"), nullable=True
    )
    #: Review round this version closed, so successive rounds stay separable.
    review_round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    adjudicated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    adjudicated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Reviewer decisions that disagreed, kept for the record even after
    #: adjudication chose one of them.
    disagreement_summary: Mapped[dict | None] = json_column()


class ReviewAssignment(Base, TimestampMixin, ConcurrencyMixin):
    """Assignment of an interpretation to a reviewer or adjudicator."""

    __tablename__ = "review_assignments"
    __table_args__ = (
        UniqueConstraint("interpretation_id", "reviewer_user_id", "review_role",
                         name="uq_review_assignments_interpretation_reviewer_role"),
        state_check("state", ReviewState, "state_valid"),
        Index("ix_review_assignments_reviewer_user_id_state", "reviewer_user_id", "state"),
    )

    id: Mapped[str] = id_column()
    interpretation_id: Mapped[str] = fk_column("app.interpretations.id")
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    reviewer_user_id: Mapped[str] = fk_column("app.users.id")
    #: ``reviewer`` | ``adjudicator``. Distinct from administrative roles.
    review_role: Mapped[str] = mapped_column(String(64), nullable=False,
                                             server_default="reviewer")
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ReviewState.NOT_STARTED.value
    )
    assigned_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Package 11: assignments are per review round, so a re-review after an
    #: adjudication does not overwrite the previous round's assignment history.
    review_round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ReviewDecision(Base, TimestampMixin):
    """Append-only reviewer action against an interpretation version."""

    __tablename__ = "review_decisions"
    __table_args__ = (
        state_check("decision", ReviewDecisionVocabulary, "decision_valid"),
        state_check("decision_role", ClassificationDecisionRole, "decision_role_valid"),
        Index(
            "ix_review_decisions_interpretation_id_review_round",
            "interpretation_id",
            "review_round",
        ),
    )

    id: Mapped[str] = id_column()
    interpretation_id: Mapped[str] = fk_column("app.interpretations.id")
    interpretation_version_id: Mapped[str] = fk_column("app.interpretation_versions.id")
    review_assignment_id: Mapped[str | None] = fk_column(
        "app.review_assignments.id", nullable=True
    )
    reviewer_user_id: Mapped[str] = fk_column("app.users.id")
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Populated when the decision changes or overrides a criterion evaluation.
    criterion_evaluation_id: Mapped[str | None] = fk_column(
        "app.criterion_evaluations.id", nullable=True
    )
    proposed_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_adjudication: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                  server_default="false")
    details: Mapped[dict | None] = json_column()

    # ---- Package 11: attribution, rounds and retained disagreement ----
    #: What this decision is. A reviewer decision is never an adjudicated one.
    decision_role: Mapped[str] = mapped_column(
        String(64), nullable=False,
        server_default=ClassificationDecisionRole.REVIEWER_DECISION.value,
    )
    review_round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    #: The classification standing when the reviewer acted, so a disagreement is
    #: readable without replaying the whole history.
    previous_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: An adjudication names the reviewer decisions it resolved; it never deletes
    #: them, and the losing decision keeps its own row unchanged.
    resolves_decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
