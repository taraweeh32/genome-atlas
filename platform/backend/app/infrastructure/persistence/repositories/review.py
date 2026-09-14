"""Persistence for interpretations, their versions and human review.

Properties enforced by the statements themselves:

* **A version is append-only.** There is no UPDATE against
  ``interpretation_versions`` except the one that stamps finalization, and that one
  is guarded by ``finalized_at IS NULL`` — so a finalized version can never be
  re-finalized or edited, and a correction has to be a new row.
* **Decisions are append-only.** ``review_decisions`` is INSERT-only. An
  adjudication names the decisions it resolved through ``resolves_decision_id``;
  the resolved rows are untouched, which is how disagreement history survives.
* **No second criterion or evidence model.** What a version was decided from is
  pinned through ``interpretation_version_criteria`` and
  ``interpretation_version_evidence``, which point at the Package 2/9/10 rows.
* **Optimistic concurrency.** Interpretation definitions and assignments move
  forward through version-checked updates, so a reviewer working from a stale read
  cannot silently overwrite another reviewer's work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import Select, insert, select, update

from app.application.repositories import Page, Paged
from app.domain.errors import ConflictError
from app.domain.review.entities import (
    InterpretationRecord,
    InterpretationVersionRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)
from app.domain.value_objects.enums import (
    Classification,
    ClassificationDecisionRole,
    DataOrigin,
    DeletionState,
    InterpretationState,
    ReviewDecision,
    ReviewState,
)
from app.infrastructure.persistence.models.interpretation import (
    Interpretation,
    InterpretationVersion,
    ReviewAssignment,
)
from app.infrastructure.persistence.models.interpretation import (
    ReviewDecision as ReviewDecisionRow,
)
from app.infrastructure.persistence.models.review import (
    InterpretationVersionCriterion,
    InterpretationVersionEvidence,
)
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_INTERPRETATIONS = Interpretation.__table__
_VERSIONS = InterpretationVersion.__table__
_VERSION_CRITERIA = InterpretationVersionCriterion.__table__
_VERSION_EVIDENCE = InterpretationVersionEvidence.__table__
_ASSIGNMENTS = ReviewAssignment.__table__
_DECISIONS = ReviewDecisionRow.__table__


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return dict(json.loads(value))
    return dict(value)


def _to_interpretation(row: Mapping[str, Any]) -> InterpretationRecord:
    return InterpretationRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        variant_id=row["variant_id"],
        created_by=row["created_by"],
        state=InterpretationState(row["state"]),
        review_state=ReviewState(row["review_state"]),
        sample_id=row.get("sample_id"),
        condition_identifier=row.get("condition_identifier"),
        condition_term=row.get("condition_term"),
        current_version_id=row.get("current_version_id"),
        current_version_number=int(row.get("current_version_number") or 0),
        version=int(row.get("version") or 1),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _to_version(
    row: Mapping[str, Any],
    *,
    criterion_ids: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
) -> InterpretationVersionRecord:
    suggested = row.get("suggested_classification")
    return InterpretationVersionRecord(
        id=row["id"],
        interpretation_id=row["interpretation_id"],
        version_number=int(row["version_number"]),
        classification=Classification(row["classification"]),
        origin=DataOrigin(row["origin"]),
        decision_role=ClassificationDecisionRole(row["decision_role"]),
        suggested_classification=Classification(suggested) if suggested else None,
        rationale=row.get("rationale"),
        clinical_significance_statement=row.get("clinical_significance_statement"),
        ruleset_id=row.get("ruleset_id"),
        ruleset_version=row.get("ruleset_version"),
        classification_evaluation_id=row.get("classification_evaluation_id"),
        automated_classification_id=row.get("automated_classification_id"),
        analysis_execution_id=row.get("analysis_execution_id"),
        scientific_execution_id=row.get("scientific_execution_id"),
        criterion_evaluation_ids=criterion_ids,
        evidence_item_ids=evidence_ids,
        evaluation_snapshot=_mapping(row.get("evaluation_snapshot")),
        conflict_summary=_mapping(row.get("conflict_summary")),
        disagreement_summary=_mapping(row.get("disagreement_summary")),
        review_round=int(row.get("review_round") or 1),
        authored_by=row.get("authored_by"),
        adjudicated_by=row.get("adjudicated_by"),
        adjudicated_at=row.get("adjudicated_at"),
        finalized_by=row.get("finalized_by"),
        finalized_at=row.get("finalized_at"),
        supersedes_version_id=row.get("supersedes_version_id"),
        reclassification_reason=row.get("reclassification_reason"),
        created_at=row.get("created_at"),
    )


def _to_assignment(row: Mapping[str, Any]) -> ReviewAssignmentRecord:
    return ReviewAssignmentRecord(
        id=row["id"],
        interpretation_id=row["interpretation_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        reviewer_user_id=row["reviewer_user_id"],
        review_role=row.get("review_role") or "reviewer",
        state=ReviewState(row["state"]),
        review_round=int(row.get("review_round") or 1),
        assigned_by=row.get("assigned_by"),
        assigned_at=row.get("assigned_at"),
        due_at=row.get("due_at"),
        completed_at=row.get("completed_at"),
        version=int(row.get("version") or 1),
    )


def _to_decision(row: Mapping[str, Any]) -> ReviewDecisionRecord:
    proposed = row.get("proposed_classification")
    previous = row.get("previous_classification")
    return ReviewDecisionRecord(
        id=row["id"],
        interpretation_id=row["interpretation_id"],
        interpretation_version_id=row["interpretation_version_id"],
        reviewer_user_id=row["reviewer_user_id"],
        decision=ReviewDecision(row["decision"]),
        decided_at=row["decided_at"],
        decision_role=ClassificationDecisionRole(row["decision_role"]),
        review_assignment_id=row.get("review_assignment_id"),
        criterion_evaluation_id=row.get("criterion_evaluation_id"),
        proposed_classification=Classification(proposed) if proposed else None,
        previous_classification=Classification(previous) if previous else None,
        rationale=row.get("rationale"),
        review_round=int(row.get("review_round") or 1),
        is_adjudication=bool(row.get("is_adjudication")),
        resolves_decision_id=row.get("resolves_decision_id"),
        details=_mapping(row.get("details")),
        created_at=row.get("created_at"),
    )


class SqlInterpretationRepository(SqlRepository):
    """Interpretation definitions and their immutable versions."""

    async def add(self, record: InterpretationRecord) -> InterpretationRecord:
        identifier = record.id or new_id("intp")
        await self._session.execute(
            insert(_INTERPRETATIONS).values(
                id=identifier,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                variant_id=record.variant_id,
                sample_id=record.sample_id,
                condition_identifier=record.condition_identifier,
                condition_term=record.condition_term,
                state=record.state.value,
                review_state=record.review_state.value,
                current_version_id=record.current_version_id,
                current_version_number=record.current_version_number,
                created_by=record.created_by,
                deletion_state=DeletionState.ACTIVE.value,
            )
        )
        return replace(record, id=identifier)

    def _select(self) -> Select:
        return select(_INTERPRETATIONS).where(
            _INTERPRETATIONS.c.deletion_state == DeletionState.ACTIVE.value
        )

    async def get(self, interpretation_id: str) -> InterpretationRecord | None:
        row = await self._fetch_one(
            self._select().where(_INTERPRETATIONS.c.id == interpretation_id)
        )
        return _to_interpretation(row) if row else None

    async def find_for_context(
        self,
        *,
        project_id: str,
        variant_id: str,
        condition_identifier: str | None = None,
        sample_id: str | None = None,
    ) -> InterpretationRecord | None:
        # Superseded and withdrawn records are closed history: a reclassification
        # must be able to open a fresh decision context for the same question.
        statement = self._select().where(
            _INTERPRETATIONS.c.project_id == project_id,
            _INTERPRETATIONS.c.variant_id == variant_id,
            _INTERPRETATIONS.c.state.notin_(
                (
                    InterpretationState.SUPERSEDED.value,
                    InterpretationState.WITHDRAWN.value,
                )
            ),
        )
        statement = statement.where(
            _INTERPRETATIONS.c.condition_identifier.is_(None)
            if condition_identifier is None
            else _INTERPRETATIONS.c.condition_identifier == condition_identifier
        )
        if sample_id is not None:
            statement = statement.where(_INTERPRETATIONS.c.sample_id == sample_id)
        row = await self._fetch_one(statement)
        return _to_interpretation(row) if row else None

    async def save(self, record: InterpretationRecord) -> InterpretationRecord:
        new_version = await self._versioned_update(
            _INTERPRETATIONS,
            entity_id=record.id,
            expected_version=record.version,
            values={
                "state": record.state.value,
                "review_state": record.review_state.value,
                "current_version_id": record.current_version_id,
                "current_version_number": record.current_version_number,
                "condition_term": record.condition_term,
            },
        )
        return replace(record, version=new_version)

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
        statement = self._select()
        if workspace_ids is not None:
            statement = statement.where(
                _INTERPRETATIONS.c.workspace_id.in_(tuple(workspace_ids))
            )
        if project_id is not None:
            statement = statement.where(_INTERPRETATIONS.c.project_id == project_id)
        if variant_id is not None:
            statement = statement.where(_INTERPRETATIONS.c.variant_id == variant_id)
        if state is not None:
            statement = statement.where(_INTERPRETATIONS.c.state == state.value)
        if review_state is not None:
            statement = statement.where(
                _INTERPRETATIONS.c.review_state == review_state.value
            )
        if reviewer_user_id is not None:
            assigned = select(_ASSIGNMENTS.c.interpretation_id).where(
                _ASSIGNMENTS.c.reviewer_user_id == reviewer_user_id
            )
            statement = statement.where(_INTERPRETATIONS.c.id.in_(assigned))
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_INTERPRETATIONS.c.created_at.desc())
            .limit(page.size)
            .offset(page.offset)
        )
        return Paged(
            items=tuple(_to_interpretation(row) for row in rows), total=total, page=page
        )

    # ---- versions -------------------------------------------------------- #

    async def add_version(
        self, version: InterpretationVersionRecord
    ) -> InterpretationVersionRecord:
        identifier = version.id or new_id("intv")
        await self._session.execute(
            insert(_VERSIONS).values(
                id=identifier,
                interpretation_id=version.interpretation_id,
                version_number=version.version_number,
                classification=version.classification.value,
                suggested_classification=(
                    version.suggested_classification.value
                    if version.suggested_classification
                    else None
                ),
                origin=version.origin.value,
                decision_role=version.decision_role.value,
                rationale=version.rationale,
                clinical_significance_statement=version.clinical_significance_statement,
                ruleset_id=version.ruleset_id,
                ruleset_version=version.ruleset_version,
                classification_evaluation_id=version.classification_evaluation_id,
                automated_classification_id=version.automated_classification_id,
                analysis_execution_id=version.analysis_execution_id,
                scientific_execution_id=version.scientific_execution_id,
                evaluation_snapshot=version.evaluation_snapshot or None,
                conflict_summary=version.conflict_summary or None,
                disagreement_summary=version.disagreement_summary or None,
                review_round=version.review_round,
                authored_by=version.authored_by,
                adjudicated_by=version.adjudicated_by,
                adjudicated_at=version.adjudicated_at,
                finalized_by=version.finalized_by,
                finalized_at=version.finalized_at,
                supersedes_version_id=version.supersedes_version_id,
                reclassification_reason=version.reclassification_reason,
            )
        )
        await self._pin(
            identifier,
            criterion_ids=version.criterion_evaluation_ids,
            evidence_ids=version.evidence_item_ids,
        )
        return replace(version, id=identifier)

    async def _pin(
        self,
        version_id: str,
        *,
        criterion_ids: Sequence[str],
        evidence_ids: Sequence[str],
    ) -> None:
        """Pin the exact criterion evaluations and evidence versions used."""
        if criterion_ids:
            await self._session.execute(
                insert(_VERSION_CRITERIA),
                [
                    {
                        "id": new_id("ivc"),
                        "interpretation_version_id": version_id,
                        "criterion_evaluation_id": criterion_id,
                        "display_order": index,
                    }
                    for index, criterion_id in enumerate(criterion_ids)
                ],
            )
        if evidence_ids:
            await self._session.execute(
                insert(_VERSION_EVIDENCE),
                [
                    {
                        "id": new_id("ive"),
                        "interpretation_version_id": version_id,
                        "evidence_item_id": evidence_id,
                        "relation": "supports",
                    }
                    for evidence_id in evidence_ids
                ],
            )

    async def _pinned(self, version_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        criteria = await self._fetch_all(
            select(_VERSION_CRITERIA.c.criterion_evaluation_id)
            .where(_VERSION_CRITERIA.c.interpretation_version_id == version_id)
            .order_by(_VERSION_CRITERIA.c.display_order)
        )
        evidence = await self._fetch_all(
            select(_VERSION_EVIDENCE.c.evidence_item_id).where(
                _VERSION_EVIDENCE.c.interpretation_version_id == version_id
            )
        )
        return (
            tuple(row["criterion_evaluation_id"] for row in criteria),
            tuple(row["evidence_item_id"] for row in evidence),
        )

    async def get_version(self, version_id: str) -> InterpretationVersionRecord | None:
        row = await self._fetch_one(select(_VERSIONS).where(_VERSIONS.c.id == version_id))
        if row is None:
            return None
        criteria, evidence = await self._pinned(version_id)
        return _to_version(row, criterion_ids=criteria, evidence_ids=evidence)

    async def finalize_version(
        self, version: InterpretationVersionRecord
    ) -> InterpretationVersionRecord:
        """Stamp finalization, refusing an already-finalized row.

        The ``finalized_at IS NULL`` guard is the immutability boundary: it is the
        only UPDATE this repository ever issues against a version row.
        """
        result = await self._session.execute(
            update(_VERSIONS)
            .where(_VERSIONS.c.id == version.id, _VERSIONS.c.finalized_at.is_(None))
            .values(
                decision_role=ClassificationDecisionRole.FINAL_INTERPRETATION.value,
                finalized_by=version.finalized_by,
                finalized_at=version.finalized_at,
            )
        )
        if result.rowcount == 0:
            raise ConflictError(
                "this interpretation version is already finalized; "
                "record a new version instead",
                details={"interpretation_version_id": version.id},
            )
        return version

    async def list_versions(
        self, *, interpretation_id: str, limit: int = 100
    ) -> tuple[InterpretationVersionRecord, ...]:
        rows = await self._fetch_all(
            select(_VERSIONS)
            .where(_VERSIONS.c.interpretation_id == interpretation_id)
            .order_by(_VERSIONS.c.version_number.desc())
            .limit(limit)
        )
        versions: list[InterpretationVersionRecord] = []
        for row in rows:
            criteria, evidence = await self._pinned(row["id"])
            versions.append(
                _to_version(row, criterion_ids=criteria, evidence_ids=evidence)
            )
        return tuple(versions)


class SqlReviewRepository(SqlRepository):
    """Reviewer assignments and the append-only decision log."""

    async def add_assignment(
        self, assignment: ReviewAssignmentRecord
    ) -> ReviewAssignmentRecord:
        identifier = assignment.id or new_id("rasg")
        await self._session.execute(
            insert(_ASSIGNMENTS).values(
                id=identifier,
                interpretation_id=assignment.interpretation_id,
                workspace_id=assignment.workspace_id,
                project_id=assignment.project_id,
                reviewer_user_id=assignment.reviewer_user_id,
                review_role=assignment.review_role,
                state=assignment.state.value,
                review_round=assignment.review_round,
                assigned_by=assignment.assigned_by,
                assigned_at=assignment.assigned_at,
                due_at=assignment.due_at,
                completed_at=assignment.completed_at,
            )
        )
        return replace(assignment, id=identifier)

    async def get_assignment(self, assignment_id: str) -> ReviewAssignmentRecord | None:
        row = await self._fetch_one(
            select(_ASSIGNMENTS).where(_ASSIGNMENTS.c.id == assignment_id)
        )
        return _to_assignment(row) if row else None

    async def find_assignment(
        self, *, interpretation_id: str, reviewer_user_id: str, review_round: int
    ) -> ReviewAssignmentRecord | None:
        row = await self._fetch_one(
            select(_ASSIGNMENTS).where(
                _ASSIGNMENTS.c.interpretation_id == interpretation_id,
                _ASSIGNMENTS.c.reviewer_user_id == reviewer_user_id,
                _ASSIGNMENTS.c.review_round == review_round,
            )
        )
        return _to_assignment(row) if row else None

    async def save_assignment(
        self, assignment: ReviewAssignmentRecord
    ) -> ReviewAssignmentRecord:
        new_version = await self._versioned_update(
            _ASSIGNMENTS,
            entity_id=assignment.id,
            expected_version=assignment.version,
            values={
                "state": assignment.state.value,
                "completed_at": assignment.completed_at,
                "due_at": assignment.due_at,
            },
        )
        return replace(assignment, version=new_version)

    async def list_assignments(
        self, *, interpretation_id: str, review_round: int | None = None
    ) -> tuple[ReviewAssignmentRecord, ...]:
        statement = select(_ASSIGNMENTS).where(
            _ASSIGNMENTS.c.interpretation_id == interpretation_id
        )
        if review_round is not None:
            statement = statement.where(_ASSIGNMENTS.c.review_round == review_round)
        rows = await self._fetch_all(
            statement.order_by(_ASSIGNMENTS.c.review_round, _ASSIGNMENTS.c.created_at)
        )
        return tuple(_to_assignment(row) for row in rows)

    async def add_decision(self, decision: ReviewDecisionRecord) -> ReviewDecisionRecord:
        identifier = decision.id or new_id("rdec")
        await self._session.execute(
            insert(_DECISIONS).values(
                id=identifier,
                interpretation_id=decision.interpretation_id,
                interpretation_version_id=decision.interpretation_version_id,
                review_assignment_id=decision.review_assignment_id,
                reviewer_user_id=decision.reviewer_user_id,
                decision=decision.decision.value,
                decision_role=decision.decision_role.value,
                criterion_evaluation_id=decision.criterion_evaluation_id,
                proposed_classification=(
                    decision.proposed_classification.value
                    if decision.proposed_classification
                    else None
                ),
                previous_classification=(
                    decision.previous_classification.value
                    if decision.previous_classification
                    else None
                ),
                rationale=decision.rationale,
                review_round=decision.review_round,
                is_adjudication=decision.is_adjudication,
                resolves_decision_id=decision.resolves_decision_id,
                decided_at=decision.decided_at,
                details=decision.details or None,
            )
        )
        return replace(decision, id=identifier)

    async def get_decision(self, decision_id: str) -> ReviewDecisionRecord | None:
        row = await self._fetch_one(
            select(_DECISIONS).where(_DECISIONS.c.id == decision_id)
        )
        return _to_decision(row) if row else None

    async def list_decisions(
        self,
        *,
        interpretation_id: str,
        review_round: int | None = None,
        interpretation_version_id: str | None = None,
    ) -> tuple[ReviewDecisionRecord, ...]:
        statement = select(_DECISIONS).where(
            _DECISIONS.c.interpretation_id == interpretation_id
        )
        if review_round is not None:
            statement = statement.where(_DECISIONS.c.review_round == review_round)
        if interpretation_version_id is not None:
            statement = statement.where(
                _DECISIONS.c.interpretation_version_id == interpretation_version_id
            )
        rows = await self._fetch_all(statement.order_by(_DECISIONS.c.decided_at))
        return tuple(_to_decision(row) for row in rows)


__all__ = [
    "SqlInterpretationRepository",
    "SqlReviewRepository",
]
