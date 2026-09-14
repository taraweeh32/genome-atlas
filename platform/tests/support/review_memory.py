"""In-memory doubles for the interpretation, review and adjudication repositories.

They mirror the SQL repositories' *semantics*, which for this package means:

* interpretation versions are append-only, and ``finalize_version`` refuses a row
  that already carries ``finalized_at`` — the same guard the UPDATE clause applies;
* review decisions are append-only: nothing updates or removes a decision row, so
  an adjudication cannot erase the decision it resolved;
* definitions and assignments move forward through version-checked updates, so a
  stale reviewer raises the concurrency conflict a database would raise;
* listings apply the same workspace clause the SQL builds, so a tenant leak in
  memory would be a tenant leak in PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.application.repositories import Page, Paged
from app.domain.errors import ConcurrencyConflictError, ConflictError
from app.domain.review.entities import (
    InterpretationRecord,
    InterpretationVersionRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)
from app.domain.value_objects.enums import InterpretationState, ReviewState


#: Mirrors the partial unique index the schema declares.
_CLOSED_CONTEXT_STATES = frozenset(
    {InterpretationState.SUPERSEDED, InterpretationState.WITHDRAWN}
)


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


@dataclass
class MemoryInterpretations:
    items: dict[str, InterpretationRecord] = field(default_factory=dict)
    versions: dict[str, InterpretationVersionRecord] = field(default_factory=dict)
    #: Set by ``MemoryRepositories`` so reviewer filtering can see assignments.
    reviews: MemoryReviews | None = None

    async def add(self, record: InterpretationRecord) -> InterpretationRecord:
        for existing in self.items.values():
            if existing.state in _CLOSED_CONTEXT_STATES:
                # A superseded or withdrawn record keeps its row but no longer owns
                # the question: a reclassification may open a fresh context.
                continue
            if (
                existing.project_id == record.project_id
                and existing.variant_id == record.variant_id
                and existing.condition_identifier == record.condition_identifier
            ):
                raise ConflictError(
                    "an interpretation already exists for this variant and condition"
                )
        self.items[record.id] = record
        return record

    async def get(self, interpretation_id: str) -> InterpretationRecord | None:
        return self.items.get(interpretation_id)

    async def find_for_context(
        self,
        *,
        project_id: str,
        variant_id: str,
        condition_identifier: str | None = None,
        sample_id: str | None = None,
    ) -> InterpretationRecord | None:
        for record in self.items.values():
            if (
                record.project_id == project_id
                and record.variant_id == variant_id
                and record.condition_identifier == condition_identifier
                and (sample_id is None or record.sample_id == sample_id)
                and record.state
                not in {InterpretationState.SUPERSEDED, InterpretationState.WITHDRAWN}
            ):
                return record
        return None

    async def save(self, record: InterpretationRecord) -> InterpretationRecord:
        current = self.items[record.id]
        if current.version != record.version:
            raise ConcurrencyConflictError(
                "the interpretation changed since it was read; re-read and retry",
                details={"resource_id": record.id},
            )
        updated = replace(record, version=record.version + 1)
        self.items[record.id] = updated
        return updated

    async def list_interpretations(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        project_id: str | None = None,
        variant_id: str | None = None,
        state: InterpretationState | None = None,
        review_state: ReviewState | None = None,
        reviewer_user_id: str | None = None,
    ) -> Paged[InterpretationRecord]:
        assigned: set[str] = set()
        if reviewer_user_id is not None and self.reviews is not None:
            assigned = {
                assignment.interpretation_id
                for assignment in self.reviews.assignments.values()
                if assignment.reviewer_user_id == reviewer_user_id
            }
        rows = [
            row
            for row in self.items.values()
            if (workspace_ids is None or row.workspace_id in workspace_ids)
            and (project_id is None or row.project_id == project_id)
            and (variant_id is None or row.variant_id == variant_id)
            and (state is None or row.state is state)
            and (review_state is None or row.review_state is review_state)
            and (reviewer_user_id is None or row.id in assigned)
        ]
        rows.sort(key=lambda row: row.id)
        return _paged(rows, page)

    async def add_version(
        self, version: InterpretationVersionRecord
    ) -> InterpretationVersionRecord:
        for existing in self.versions.values():
            if (
                existing.interpretation_id == version.interpretation_id
                and existing.version_number == version.version_number
            ):
                raise ConflictError("this interpretation version already exists")
        self.versions[version.id] = version
        return version

    async def get_version(self, version_id: str) -> InterpretationVersionRecord | None:
        return self.versions.get(version_id)

    async def finalize_version(
        self, version: InterpretationVersionRecord
    ) -> InterpretationVersionRecord:
        current = self.versions[version.id]
        if current.finalized_at is not None:
            raise ConflictError(
                "this interpretation version is already finalized; "
                "record a new version instead",
                details={"interpretation_version_id": version.id},
            )
        self.versions[version.id] = version
        return version

    async def list_versions(
        self, *, interpretation_id: str, limit: int = 100
    ) -> tuple[InterpretationVersionRecord, ...]:
        rows = [
            row
            for row in self.versions.values()
            if row.interpretation_id == interpretation_id
        ]
        rows.sort(key=lambda row: row.version_number, reverse=True)
        return tuple(rows[:limit])


@dataclass
class MemoryReviews:
    assignments: dict[str, ReviewAssignmentRecord] = field(default_factory=dict)
    decisions: list[ReviewDecisionRecord] = field(default_factory=list)

    async def add_assignment(
        self, assignment: ReviewAssignmentRecord
    ) -> ReviewAssignmentRecord:
        for existing in self.assignments.values():
            if (
                existing.interpretation_id == assignment.interpretation_id
                and existing.reviewer_user_id == assignment.reviewer_user_id
                and existing.review_round == assignment.review_round
            ):
                raise ConflictError(
                    "this reviewer is already assigned for this review round"
                )
        self.assignments[assignment.id] = assignment
        return assignment

    async def get_assignment(self, assignment_id: str) -> ReviewAssignmentRecord | None:
        return self.assignments.get(assignment_id)

    async def find_assignment(
        self, *, interpretation_id: str, reviewer_user_id: str, review_round: int
    ) -> ReviewAssignmentRecord | None:
        for assignment in self.assignments.values():
            if (
                assignment.interpretation_id == interpretation_id
                and assignment.reviewer_user_id == reviewer_user_id
                and assignment.review_round == review_round
            ):
                return assignment
        return None

    async def save_assignment(
        self, assignment: ReviewAssignmentRecord
    ) -> ReviewAssignmentRecord:
        current = self.assignments[assignment.id]
        if current.version != assignment.version:
            raise ConcurrencyConflictError(
                "the review assignment changed since it was read; re-read and retry",
                details={"resource_id": assignment.id},
            )
        updated = replace(assignment, version=assignment.version + 1)
        self.assignments[assignment.id] = updated
        return updated

    async def list_assignments(
        self, *, interpretation_id: str, review_round: int | None = None
    ) -> tuple[ReviewAssignmentRecord, ...]:
        rows = [
            row
            for row in self.assignments.values()
            if row.interpretation_id == interpretation_id
            and (review_round is None or row.review_round == review_round)
        ]
        rows.sort(key=lambda row: (row.review_round, row.id))
        return tuple(rows)

    async def add_decision(self, decision: ReviewDecisionRecord) -> ReviewDecisionRecord:
        self.decisions.append(decision)
        return decision

    async def get_decision(self, decision_id: str) -> ReviewDecisionRecord | None:
        for decision in self.decisions:
            if decision.id == decision_id:
                return decision
        return None

    async def list_decisions(
        self,
        *,
        interpretation_id: str,
        review_round: int | None = None,
        interpretation_version_id: str | None = None,
    ) -> tuple[ReviewDecisionRecord, ...]:
        rows = [
            row
            for row in self.decisions
            if row.interpretation_id == interpretation_id
            and (review_round is None or row.review_round == review_round)
            and (
                interpretation_version_id is None
                or row.interpretation_version_id == interpretation_version_id
            )
        ]
        rows.sort(key=lambda row: row.decided_at)
        return tuple(rows)


__all__ = ["MemoryInterpretations", "MemoryReviews"]
