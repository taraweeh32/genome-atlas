"""Use cases for interpretation, human review and adjudication.

Nothing in this package evaluates a criterion, combines criteria or computes a
classification. It records *decisions*: who decided what, from which evidence and
criterion evaluations, under which ruleset version, and how a disagreement between
reviewers was resolved. The automated suggestion it starts from was produced by the
independently deployable rules engine (Package 10) and is never rewritten here.
"""

from app.application.use_cases.review.adjudication import (
    AdjudicateInterpretation,
    AdjudicateInterpretationCommand,
    FinalizeInterpretation,
    FinalizeInterpretationCommand,
)
from app.application.use_cases.review.dependencies import ReviewServices
from app.application.use_cases.review.interpretations import (
    InterpretationDetail,
    InterpretationReader,
    OpenInterpretation,
    OpenInterpretationCommand,
    ReclassifyInterpretation,
    ReclassifyInterpretationCommand,
    RecordInterpretationVersion,
    RecordInterpretationVersionCommand,
)
from app.application.use_cases.review.reviews import (
    AssignReviewer,
    AssignReviewerCommand,
    RecordReviewDecision,
    RecordReviewDecisionCommand,
    SubmitReview,
    SubmitReviewCommand,
)

__all__ = [
    "AdjudicateInterpretation",
    "AdjudicateInterpretationCommand",
    "AssignReviewer",
    "AssignReviewerCommand",
    "FinalizeInterpretation",
    "FinalizeInterpretationCommand",
    "InterpretationDetail",
    "InterpretationReader",
    "OpenInterpretation",
    "OpenInterpretationCommand",
    "ReclassifyInterpretation",
    "ReclassifyInterpretationCommand",
    "RecordInterpretationVersion",
    "RecordInterpretationVersionCommand",
    "RecordReviewDecision",
    "RecordReviewDecisionCommand",
    "ReviewServices",
    "SubmitReview",
    "SubmitReviewCommand",
]
