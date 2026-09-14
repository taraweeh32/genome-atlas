"""Interpretation, human review and adjudication domain.

Four states that are deliberately never the same thing:

* an **automated suggestion** produced by a versioned ruleset (Package 10),
* a **reviewer decision** recorded by one identified person,
* an **adjudicated decision** resolving disagreement between reviewers,
* a **final interpretation** — the finalized, immutable version.
"""

from app.domain.review.entities import (
    InterpretationRecord,
    InterpretationVersionRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)
from app.domain.review.workflow import (
    FINAL_INTERPRETATION_STATES,
    check_interpretation_transition,
    check_review_transition,
    disagreement_between,
    require_not_finalized,
)

__all__ = [
    "FINAL_INTERPRETATION_STATES",
    "InterpretationRecord",
    "InterpretationVersionRecord",
    "ReviewAssignmentRecord",
    "ReviewDecisionRecord",
    "check_interpretation_transition",
    "check_review_transition",
    "disagreement_between",
    "require_not_finalized",
]
