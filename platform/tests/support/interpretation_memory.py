"""In-memory doubles for the interpretation-engine repositories.

They mirror the SQL repositories' *semantics*, which for this package means:

* a ruleset version is identified by ``(ruleset_key, version)``, its criteria and
  combination rules are written once and never rewritten, and only lifecycle state
  moves;
* automated classifications are append-only: a newer suggestion is a new row that
  points at the one it supersedes, and the earlier row stays readable;
* listings apply the same workspace clause the SQL builds, so a test that leaks
  across tenants in memory would leak in PostgreSQL too;
* an idempotency key is unique per workspace, exactly as the unique index enforces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.application.repositories import Page, Paged
from app.domain.errors import ConflictError
from app.domain.interpretation.entities import (
    AutomatedClassificationRecord,
    BenchmarkCaseRecord,
    BenchmarkRunRecord,
    ClassificationEvaluationRecord,
    CriterionEvaluationRecord,
    RulesetRecord,
)
from app.domain.value_objects.enums import (
    BenchmarkValidationKind,
    ClassificationEvaluationState,
    ScientificResourceState,
)

_USABLE = {ScientificResourceState.ACTIVE, ScientificResourceState.DEPRECATED}


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


@dataclass
class MemoryRulesets:
    items: dict[str, RulesetRecord] = field(default_factory=dict)

    async def add(self, ruleset: RulesetRecord) -> RulesetRecord:
        for existing in self.items.values():
            if (
                existing.ruleset_key == ruleset.ruleset_key
                and existing.version == ruleset.version
            ):
                raise ConflictError("this ruleset version already exists")
        self.items[ruleset.id] = ruleset
        return ruleset

    async def get(self, ruleset_id: str) -> RulesetRecord | None:
        return self.items.get(ruleset_id)

    async def get_by_version(
        self, *, ruleset_key: str, version: str
    ) -> RulesetRecord | None:
        for ruleset in self.items.values():
            if ruleset.ruleset_key == ruleset_key and ruleset.version == version:
                return ruleset
        return None

    async def save_lifecycle(self, ruleset: RulesetRecord) -> RulesetRecord:
        current = self.items[ruleset.id]
        # Declared content is immutable; only lifecycle fields are carried over.
        self.items[ruleset.id] = replace(
            current,
            state=ruleset.state,
            activated_at=ruleset.activated_at,
            deprecated_at=ruleset.deprecated_at,
            retired_at=ruleset.retired_at,
            invalidated_at=ruleset.invalidated_at,
            invalidation_reason=ruleset.invalidation_reason,
            record_version=current.record_version + 1,
        )
        return self.items[ruleset.id]

    async def list_rulesets(
        self,
        *,
        page: Page,
        ruleset_key: str | None = None,
        gene_symbol: str | None = None,
        usable_only: bool = False,
    ) -> Paged[RulesetRecord]:
        rows = [
            row
            for row in self.items.values()
            if (ruleset_key is None or row.ruleset_key == ruleset_key)
            and (gene_symbol is None or row.gene_symbol == gene_symbol)
            and (not usable_only or row.state in _USABLE)
        ]
        rows.sort(key=lambda row: (row.ruleset_key, row.version))
        return _paged(rows, page)


@dataclass
class MemoryClassificationEvaluations:
    items: dict[str, ClassificationEvaluationRecord] = field(default_factory=dict)
    classifications: dict[str, AutomatedClassificationRecord] = field(
        default_factory=dict
    )
    criteria: list[CriterionEvaluationRecord] = field(default_factory=list)

    async def add(
        self, evaluation: ClassificationEvaluationRecord
    ) -> ClassificationEvaluationRecord:
        if evaluation.idempotency_key:
            existing = await self.get_by_idempotency_key(
                workspace_id=evaluation.workspace_id,
                idempotency_key=evaluation.idempotency_key,
            )
            if existing is not None:
                raise ConflictError("this evaluation was already requested")
        self.items[evaluation.id] = evaluation
        return evaluation

    async def get(self, evaluation_id: str) -> ClassificationEvaluationRecord | None:
        return self.items.get(evaluation_id)

    async def get_by_idempotency_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> ClassificationEvaluationRecord | None:
        for row in self.items.values():
            if (
                row.workspace_id == workspace_id
                and row.idempotency_key == idempotency_key
            ):
                return row
        return None

    async def save(
        self, evaluation: ClassificationEvaluationRecord
    ) -> ClassificationEvaluationRecord:
        current = self.items[evaluation.id]
        self.items[evaluation.id] = replace(
            evaluation, record_version=current.record_version + 1
        )
        return self.items[evaluation.id]

    async def list_evaluations(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        variant_id: str | None = None,
        ruleset_id: str | None = None,
        project_id: str | None = None,
        state: ClassificationEvaluationState | None = None,
    ) -> Paged[ClassificationEvaluationRecord]:
        rows = [
            row
            for row in self.items.values()
            if (workspace_ids is None or row.workspace_id in workspace_ids)
            and (variant_id is None or row.variant_id == variant_id)
            and (ruleset_id is None or row.ruleset_id == ruleset_id)
            and (project_id is None or row.project_id == project_id)
            and (state is None or row.state is state)
        ]
        rows.sort(key=lambda row: (row.requested_at or row.created_at, row.id))
        return _paged(rows, page)

    async def add_classification(
        self, classification: AutomatedClassificationRecord
    ) -> AutomatedClassificationRecord:
        self.classifications[classification.id] = classification
        return classification

    async def get_classification(
        self, classification_id: str
    ) -> AutomatedClassificationRecord | None:
        return self.classifications.get(classification_id)

    async def mark_superseded(
        self, *, classification_id: str, superseded_by_id: str
    ) -> None:
        current = self.classifications.get(classification_id)
        if current is None:
            return
        self.classifications[classification_id] = replace(
            current, superseded_by_id=superseded_by_id
        )

    async def current_classification(
        self,
        *,
        variant_id: str,
        ruleset_id: str,
        condition_identifier: str | None = None,
    ) -> AutomatedClassificationRecord | None:
        rows = [
            row
            for row in self.classifications.values()
            if row.variant_id == variant_id
            and row.ruleset_id == ruleset_id
            and row.condition_identifier == condition_identifier
            and row.superseded_by_id is None
        ]
        rows.sort(key=lambda row: row.version_number)
        return rows[-1] if rows else None

    async def classification_history(
        self,
        *,
        variant_id: str,
        workspace_ids: frozenset[str] | None = None,
        ruleset_id: str | None = None,
        limit: int = 100,
    ) -> tuple[AutomatedClassificationRecord, ...]:
        rows = [
            row
            for row in self.classifications.values()
            if row.variant_id == variant_id
            and (workspace_ids is None or row.workspace_id in workspace_ids)
            and (ruleset_id is None or row.ruleset_id == ruleset_id)
        ]
        rows.sort(key=lambda row: (row.produced_at or row.created_at, row.version_number))
        return tuple(rows[-limit:])

    async def add_criterion_evaluations(
        self, evaluations: tuple[CriterionEvaluationRecord, ...]
    ) -> None:
        self.criteria.extend(evaluations)

    async def list_criterion_evaluations(
        self, *, classification_evaluation_id: str
    ) -> tuple[CriterionEvaluationRecord, ...]:
        return tuple(
            row
            for row in self.criteria
            if row.classification_evaluation_id == classification_evaluation_id
        )


@dataclass
class MemoryRulesetBenchmarks:
    cases: dict[str, BenchmarkCaseRecord] = field(default_factory=dict)
    runs: dict[str, BenchmarkRunRecord] = field(default_factory=dict)

    async def add_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord:
        existing = await self.get_case_by_key(
            ruleset_id=case.ruleset_id, case_key=case.case_key
        )
        if existing is not None:
            raise ConflictError("this benchmark case already exists")
        self.cases[case.id] = case
        return case

    async def get_case(self, case_id: str) -> BenchmarkCaseRecord | None:
        return self.cases.get(case_id)

    async def get_case_by_key(
        self, *, ruleset_id: str, case_key: str
    ) -> BenchmarkCaseRecord | None:
        for row in self.cases.values():
            if row.ruleset_id == ruleset_id and row.case_key == case_key:
                return row
        return None

    async def list_cases(
        self,
        *,
        ruleset_id: str,
        validation_kind: BenchmarkValidationKind | None = None,
        active_only: bool = True,
    ) -> tuple[BenchmarkCaseRecord, ...]:
        rows = [
            row
            for row in self.cases.values()
            if row.ruleset_id == ruleset_id
            and (validation_kind is None or row.validation_kind is validation_kind)
            and (not active_only or row.is_active)
        ]
        rows.sort(key=lambda row: row.case_key)
        return tuple(rows)

    async def add_run(self, run: BenchmarkRunRecord) -> BenchmarkRunRecord:
        self.runs[run.id] = run
        return run

    async def get_run(self, run_id: str) -> BenchmarkRunRecord | None:
        return self.runs.get(run_id)

    async def list_runs(self, *, ruleset_id: str, page: Page) -> Paged[BenchmarkRunRecord]:
        rows = [row for row in self.runs.values() if row.ruleset_id == ruleset_id]
        rows.sort(key=lambda row: (row.executed_at or row.created_at, row.id))
        return _paged(rows, page)


__all__ = [
    "MemoryClassificationEvaluations",
    "MemoryRulesetBenchmarks",
    "MemoryRulesets",
]
