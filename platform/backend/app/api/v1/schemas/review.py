"""Transport schemas for interpretations, human review and adjudication.

Same conventions as the other schema modules: payloads forbid unknown fields,
responses expose enum values, and no internal identity is leaked to a tenant client.

Three things specific to this surface:

* **Four decision kinds stay four fields.** ``suggested_classification`` (what the
  rules engine proposed), the reviewer decisions, the adjudicated decision and the
  final ``classification`` are separate in the payload as they are in the database.
  Nothing collapses them into one "the classification" value.
* **Disagreement is part of the response.** A version carries the disagreement that
  stood when it was written, and the decision history is returned whole, including
  decisions that were overruled.
* **A finalized version says so.** ``finalized_at`` and ``decision_role`` tell a
  client that what it is looking at is closed and that a change means a new version.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel, Collection
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Payloads                                                                    #
# --------------------------------------------------------------------------- #


class OpenInterpretationPayload(ApiModel):
    """Open a decision context for one variant in one project."""

    project_id: str = Field(min_length=1, max_length=64)
    variant_id: str = Field(min_length=1, max_length=64)
    sample_id: str | None = Field(default=None, max_length=64)
    condition_identifier: str | None = Field(default=None, max_length=128)
    condition_term: str | None = Field(default=None, max_length=255)


class RecordVersionPayload(ApiModel):
    """Record an interpretation version: a decision, and what it rested on."""

    #: One of the platform's classification values, as recorded by a person.
    classification: str = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=8000)
    classification_evaluation_id: str | None = Field(default=None, max_length=64)
    automated_classification_id: str | None = Field(default=None, max_length=64)
    ruleset_id: str | None = Field(default=None, max_length=64)
    ruleset_version: str | None = Field(default=None, max_length=64)
    suggested_classification: str | None = None
    clinical_significance_statement: str | None = Field(default=None, max_length=4000)
    criterion_evaluation_ids: list[str] = Field(default_factory=list)
    evidence_item_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, object] | None = None


class AssignReviewerPayload(ApiModel):
    reviewer_user_id: str = Field(min_length=1, max_length=64)
    review_role: str = Field(default="reviewer", description="reviewer | adjudicator")
    due_at: datetime | None = None


class ReviewDecisionPayload(ApiModel):
    """One reviewer action against one interpretation version."""

    interpretation_version_id: str = Field(min_length=1, max_length=64)
    decision: str = Field(
        description="accept | reject | modify | add_criterion | remove_criterion | "
        "override | abstain"
    )
    rationale: str | None = Field(default=None, max_length=8000)
    criterion_evaluation_id: str | None = Field(default=None, max_length=64)
    proposed_classification: str | None = None
    details: dict[str, object] | None = None
    expected_current_version_number: int | None = Field(
        default=None,
        ge=0,
        description="The version number the reviewer was looking at. Sent back so a "
        "stale review cannot silently land on top of newer work.",
    )


class AdjudicatePayload(ApiModel):
    classification: str
    rationale: str = Field(min_length=1, max_length=8000)
    clinical_significance_statement: str | None = Field(default=None, max_length=4000)
    details: dict[str, object] | None = None


class FinalizePayload(ApiModel):
    rationale: str = Field(min_length=1, max_length=8000)
    expected_version_number: int | None = Field(default=None, ge=0)


class ReclassifyPayload(ApiModel):
    reason: str = Field(min_length=1, max_length=4000)


# --------------------------------------------------------------------------- #
# Responses                                                                   #
# --------------------------------------------------------------------------- #


class InterpretationResponse(ApiModel):
    id: str
    workspace_id: str
    project_id: str
    variant_id: str
    sample_id: str | None
    condition_identifier: str | None
    condition_term: str | None
    state: str
    review_state: str
    current_version_id: str | None
    current_version_number: int
    version: int
    created_by: str
    created_at: datetime | None
    updated_at: datetime | None


class InterpretationVersionResponse(ApiModel):
    id: str
    interpretation_id: str
    version_number: int
    #: The decision recorded in this version.
    classification: str
    #: What the rules engine suggested, kept separate from the decision above.
    suggested_classification: str | None
    decision_role: str
    origin: str
    rationale: str | None
    clinical_significance_statement: str | None
    ruleset_id: str | None
    ruleset_version: str | None
    classification_evaluation_id: str | None
    automated_classification_id: str | None
    criterion_evaluation_ids: list[str]
    evidence_item_ids: list[str]
    disagreement_summary: dict[str, object]
    review_round: int
    authored_by: str | None
    adjudicated_by: str | None
    adjudicated_at: datetime | None
    finalized_by: str | None
    finalized_at: datetime | None
    supersedes_version_id: str | None
    created_at: datetime | None


class ReviewAssignmentResponse(ApiModel):
    id: str
    interpretation_id: str
    reviewer_user_id: str
    review_role: str
    state: str
    review_round: int
    assigned_by: str | None
    assigned_at: datetime | None
    due_at: datetime | None
    completed_at: datetime | None


class ReviewDecisionResponse(ApiModel):
    id: str
    interpretation_id: str
    interpretation_version_id: str
    reviewer_user_id: str
    decision: str
    decision_role: str
    criterion_evaluation_id: str | None
    proposed_classification: str | None
    previous_classification: str | None
    rationale: str | None
    review_round: int
    is_adjudication: bool
    resolves_decision_id: str | None
    decided_at: datetime


class InterpretationDetailResponse(ApiModel):
    """The whole decision record: context, versions, reviewers, decisions."""

    interpretation: InterpretationResponse
    current_version: InterpretationVersionResponse | None
    versions: list[InterpretationVersionResponse]
    assignments: list[ReviewAssignmentResponse]
    decisions: list[ReviewDecisionResponse]


class InterpretationCollection(Collection[InterpretationResponse]):
    items: list[InterpretationResponse]
    page: PageMeta


__all__ = [
    "AdjudicatePayload",
    "AssignReviewerPayload",
    "FinalizePayload",
    "InterpretationCollection",
    "InterpretationDetailResponse",
    "InterpretationResponse",
    "InterpretationVersionResponse",
    "OpenInterpretationPayload",
    "ReclassifyPayload",
    "RecordVersionPayload",
    "ReviewAssignmentResponse",
    "ReviewDecisionPayload",
    "ReviewDecisionResponse",
]
