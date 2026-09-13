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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DeletionState,
    Classification,
    CriterionDirection,
    CriterionStrength,
    DataOrigin,
    EvidenceCategory,
    EvidenceStrength,
    InterpretationState,
    ReviewDecision as ReviewDecisionVocabulary,
    ReviewState,
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
        Index("ix_evidence_items_variant_id", "variant_id"),
        Index("ix_evidence_items_workspace_id_project_id", "workspace_id", "project_id"),
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


class CriterionEvaluation(Base, TimestampMixin, ConcurrencyMixin):
    """Evaluation of one ruleset criterion for a variant in a given context."""

    __tablename__ = "criterion_evaluations"
    __table_args__ = (
        state_check("strength", CriterionStrength, "strength_valid"),
        state_check("direction", CriterionDirection, "direction_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_criterion_evaluations_variant_id", "variant_id"),
        Index("ix_criterion_evaluations_interpretation_id", "interpretation_id"),
        Index("ix_criterion_evaluations_criterion_key", "criterion_key"),
    )

    id: Mapped[str] = id_column()
    variant_id: Mapped[str] = fk_column("app.variants.id")
    interpretation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interpretation_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Ruleset identity is mandatory: a criterion has no meaning without it.
    ruleset_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
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
        UniqueConstraint("project_id", "variant_id", "condition_identifier",
                         name="uq_interpretations_project_id_variant_id_condition_identifier"),
        state_check("state", InterpretationState, "state_valid"),
        state_check("review_state", ReviewState, "review_state_valid"),
        Index("ix_interpretations_workspace_id_state", "workspace_id", "state"),
        Index("ix_interpretations_variant_id", "variant_id"),
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
        Index("ix_interpretation_versions_interpretation_id", "interpretation_id"),
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


class ReviewDecision(Base, TimestampMixin):
    """Append-only reviewer action against an interpretation version."""

    __tablename__ = "review_decisions"
    __table_args__ = (
        state_check("decision", ReviewDecisionVocabulary, "decision_valid"),
        Index("ix_review_decisions_interpretation_version_id", "interpretation_version_id"),
        Index("ix_review_decisions_reviewer_user_id", "reviewer_user_id"),
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
