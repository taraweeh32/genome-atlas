"""State transitions, finalization immutability and disagreement detection.

Three rules this module exists to enforce:

1. **A finalized interpretation is closed.** Nothing edits it — not a reviewer, not
   an adjudicator, not a corrected ruleset. A correction is a new version.
2. **Disagreement is a fact, not an error.** When reviewers propose different
   classifications the platform records the disagreement and requires adjudication;
   it never picks a winner and never drops the losing decision.
3. **Transitions are declared, not implied.** The interpretation lifecycle and the
   review lifecycle are separate state machines and are validated separately.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.domain.errors import ConflictError, InvalidStateTransitionError
from app.domain.value_objects.enums import (
    Classification,
    InterpretationState,
    ReviewState,
)

#: Interpretation states in which the scientific content is closed.
FINAL_INTERPRETATION_STATES: frozenset[InterpretationState] = frozenset(
    {InterpretationState.FINALIZED, InterpretationState.SUPERSEDED}
)

_INTERPRETATION_TRANSITIONS: dict[InterpretationState, frozenset[InterpretationState]] = {
    InterpretationState.DRAFT: frozenset(
        {
            InterpretationState.AUTOMATED,
            InterpretationState.IN_REVIEW,
            InterpretationState.WITHDRAWN,
        }
    ),
    InterpretationState.AUTOMATED: frozenset(
        {
            InterpretationState.IN_REVIEW,
            InterpretationState.DRAFT,
            InterpretationState.WITHDRAWN,
        }
    ),
    InterpretationState.IN_REVIEW: frozenset(
        {
            InterpretationState.ADJUDICATION,
            InterpretationState.APPROVED,
            InterpretationState.DRAFT,
            InterpretationState.WITHDRAWN,
        }
    ),
    InterpretationState.ADJUDICATION: frozenset(
        {
            InterpretationState.APPROVED,
            InterpretationState.IN_REVIEW,
            InterpretationState.WITHDRAWN,
        }
    ),
    InterpretationState.APPROVED: frozenset(
        {
            InterpretationState.FINALIZED,
            InterpretationState.IN_REVIEW,
            InterpretationState.WITHDRAWN,
        }
    ),
    #: A finalized interpretation only ever becomes superseded, and only because a
    #: *new* version was recorded. It is never reopened.
    InterpretationState.FINALIZED: frozenset({InterpretationState.SUPERSEDED}),
    InterpretationState.SUPERSEDED: frozenset(),
    InterpretationState.WITHDRAWN: frozenset(),
}

_REVIEW_TRANSITIONS: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.NOT_STARTED: frozenset({ReviewState.ASSIGNED, ReviewState.WITHDRAWN}),
    ReviewState.ASSIGNED: frozenset(
        {ReviewState.IN_PROGRESS, ReviewState.SUBMITTED, ReviewState.WITHDRAWN}
    ),
    ReviewState.IN_PROGRESS: frozenset(
        {ReviewState.SUBMITTED, ReviewState.ESCALATED, ReviewState.WITHDRAWN}
    ),
    ReviewState.SUBMITTED: frozenset(
        {
            ReviewState.ACCEPTED,
            ReviewState.REJECTED,
            ReviewState.ESCALATED,
            ReviewState.WITHDRAWN,
        }
    ),
    ReviewState.ESCALATED: frozenset(
        {ReviewState.ACCEPTED, ReviewState.REJECTED, ReviewState.WITHDRAWN}
    ),
    ReviewState.ACCEPTED: frozenset({ReviewState.ESCALATED}),
    ReviewState.REJECTED: frozenset({ReviewState.ESCALATED, ReviewState.IN_PROGRESS}),
    ReviewState.WITHDRAWN: frozenset(),
}


def check_interpretation_transition(
    current: InterpretationState, target: InterpretationState
) -> None:
    if target not in _INTERPRETATION_TRANSITIONS[current]:
        raise InvalidStateTransitionError("interpretation", current.value, target.value)


def check_review_transition(current: ReviewState, target: ReviewState) -> None:
    if target not in _REVIEW_TRANSITIONS[current]:
        raise InvalidStateTransitionError("review", current.value, target.value)


def require_not_finalized(state: InterpretationState, *, interpretation_id: str) -> None:
    """Refuse any content change against a closed interpretation."""
    if state in FINAL_INTERPRETATION_STATES:
        raise ConflictError(
            "this interpretation is finalized; record a new version instead of "
            "changing it",
            details={"interpretation_id": interpretation_id, "state": state.value},
        )


def disagreement_between(
    proposals: Iterable[tuple[str, Classification | None]],
) -> dict[str, Sequence[str]]:
    """Group reviewer proposals by classification.

    Returns a mapping from classification value to the reviewers who proposed it.
    More than one key means the reviewers disagree and the interpretation needs
    adjudication. Abstentions (no proposed classification) are excluded: an
    abstention is not a competing opinion.
    """
    grouped: dict[str, list[str]] = {}
    for reviewer_id, classification in proposals:
        if classification is None:
            continue
        grouped.setdefault(classification.value, []).append(reviewer_id)
    return {key: tuple(value) for key, value in sorted(grouped.items())}


__all__ = [
    "FINAL_INTERPRETATION_STATES",
    "check_interpretation_transition",
    "check_review_transition",
    "disagreement_between",
    "require_not_finalized",
]
