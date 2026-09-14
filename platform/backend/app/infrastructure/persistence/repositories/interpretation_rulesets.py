"""Persistence for rulesets, automated evaluations and benchmark cases.

Properties enforced by the statements themselves:

* **A registered version is immutable.** The only UPDATE against a ruleset row
  changes its lifecycle state and the timestamps of that change. Criteria and
  combination rules are inserted once with the version and never rewritten, so a
  historical classification can always be read against the exact rules it was
  produced under.
* **Nothing is overwritten.** A re-evaluation inserts a new suggestion and marks
  the previous one superseded; the earlier row keeps its content byte for byte.
* **A suggestion stays a suggestion.** Every insert into
  ``automated_classifications`` writes ``automated_suggestion``, and a CHECK
  constraint refuses anything else. Reviewer and adjudicated decisions are written
  by the interpretation layer against different tables.
* **One criterion model.** Criterion evaluations are ``criterion_evaluations``
  rows, and their evidence links are ``criterion_evaluation_evidence`` rows — the
  tables Package 2 established.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import Select, insert, select, update

from app.application.repositories import Page, Paged
from app.domain.errors import NotFoundError
from app.domain.interpretation.entities import (
    AutomatedClassificationRecord,
    BenchmarkCaseRecord,
    BenchmarkComparison,
    BenchmarkRunRecord,
    ClassificationEvaluationRecord,
    CombinationRule,
    CriterionDefinition,
    CriterionEvaluationRecord,
    RulesetRecord,
)
from app.domain.value_objects.enums import (
    BenchmarkCaseOutcome,
    BenchmarkValidationKind,
    Classification,
    ClassificationDecisionRole,
    ClassificationEvaluationState,
    CriterionDirection,
    CriterionFamily,
    CriterionStrength,
    DataOrigin,
    RulesetCombinationStrategy,
    RulesetSpecificationScope,
    ScientificResourceState,
    ValidationSeverity,
)
from app.infrastructure.persistence.models.interpretation import (
    CriterionEvaluation,
    CriterionEvaluationEvidence,
)
from app.infrastructure.persistence.models.interpretation_rulesets import (
    AutomatedClassificationRow,
    ClassificationEvaluationRow,
    InterpretationCombinationRuleRow,
    InterpretationCriterionRow,
    InterpretationRulesetRow,
    RulesetBenchmarkCaseRow,
    RulesetBenchmarkRunRow,
)
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_RULESETS = InterpretationRulesetRow.__table__
_CRITERIA = InterpretationCriterionRow.__table__
_RULES = InterpretationCombinationRuleRow.__table__
_EVALUATIONS = ClassificationEvaluationRow.__table__
_CLASSIFICATIONS = AutomatedClassificationRow.__table__
_CASES = RulesetBenchmarkCaseRow.__table__
_RUNS = RulesetBenchmarkRunRow.__table__
_CRITERION_EVALUATIONS = CriterionEvaluation.__table__
_CRITERION_EVIDENCE = CriterionEvaluationEvidence.__table__

_USABLE = (
    ScientificResourceState.ACTIVE.value,
    ScientificResourceState.DEPRECATED.value,
)


def _string_list(value: Any) -> tuple[str, ...]:
    """Read a JSON list column back as a tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Mapping):
        value = value.get("values", [])
    return tuple(str(item) for item in value)


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return dict(json.loads(value))
    return dict(value)


def _to_criterion(row: Mapping[str, Any]) -> CriterionDefinition:
    return CriterionDefinition(
        criterion_key=row["criterion_key"],
        family=CriterionFamily(row["family"]),
        direction=CriterionDirection(row["direction"]),
        default_strength=CriterionStrength(row["default_strength"]),
        description=row["description"],
        permitted_strengths=tuple(
            CriterionStrength(item) for item in _string_list(row["permitted_strengths"])
        ),
        evidence_categories=_string_list(row["evidence_categories"]),
        requires_evidence=bool(row["requires_evidence"]),
        display_order=row["display_order"],
        metadata=_mapping(row["metadata_json"]),
    )


def _to_rule(row: Mapping[str, Any]) -> CombinationRule:
    return CombinationRule(
        rule_key=row["rule_key"],
        classification=Classification(row["classification"]),
        description=row["description"],
        requirements=_mapping(row["requirements"]),
        precedence=row["precedence"],
    )


def _to_ruleset(
    row: Mapping[str, Any],
    *,
    criteria: Sequence[CriterionDefinition] = (),
    rules: Sequence[CombinationRule] = (),
) -> RulesetRecord:
    return RulesetRecord(
        id=row["id"],
        ruleset_key=row["ruleset_key"],
        version=row["version"],
        display_name=row["display_name"],
        guideline_source=row["guideline_source"],
        state=ScientificResourceState(row["state"]),
        description=row["description"],
        guideline_citation=row["guideline_citation"],
        publication_reference=row["publication_reference"],
        publication_year=row["publication_year"],
        specification_scope=RulesetSpecificationScope(row["specification_scope"]),
        gene_symbol=row["gene_symbol"],
        condition_identifier=row["condition_identifier"],
        condition_term=row["condition_term"],
        combination_strategy=RulesetCombinationStrategy(row["combination_strategy"]),
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        capability_id=row["capability_id"],
        capability_version=row["capability_version"],
        engine_resource_id=row["engine_resource_id"],
        genome_assembly=row["genome_assembly"],
        criteria=tuple(criteria),
        combination_rules=tuple(rules),
        configuration_digest=row["configuration_digest"],
        provenance=_mapping(row["provenance"]),
        metadata=_mapping(row["metadata_json"]),
        registered_by=row["registered_by"],
        activated_at=row["activated_at"],
        deprecated_at=row["deprecated_at"],
        retired_at=row["retired_at"],
        invalidated_at=row["invalidated_at"],
        invalidation_reason=row["invalidation_reason"],
        created_at=row["created_at"],
    )


class SqlRulesetRepository(SqlRepository):
    """Registered ruleset versions and the content each version declares."""

    async def add(self, ruleset: RulesetRecord) -> RulesetRecord:
        await self._session.execute(
            insert(_RULESETS).values(
                id=ruleset.id,
                ruleset_key=ruleset.ruleset_key,
                version=ruleset.version,
                display_name=ruleset.display_name,
                description=ruleset.description,
                guideline_source=ruleset.guideline_source,
                guideline_citation=ruleset.guideline_citation,
                publication_reference=ruleset.publication_reference,
                publication_year=ruleset.publication_year,
                state=ruleset.state.value,
                specification_scope=ruleset.specification_scope.value,
                gene_symbol=ruleset.gene_symbol,
                condition_identifier=ruleset.condition_identifier,
                condition_term=ruleset.condition_term,
                combination_strategy=ruleset.combination_strategy.value,
                effective_from=ruleset.effective_from,
                effective_to=ruleset.effective_to,
                capability_id=ruleset.capability_id,
                capability_version=ruleset.capability_version,
                engine_resource_id=ruleset.engine_resource_id,
                genome_assembly=ruleset.genome_assembly,
                configuration_digest=ruleset.configuration_digest,
                provenance=ruleset.provenance or None,
                metadata_json=ruleset.metadata or None,
                registered_by=ruleset.registered_by,
                activated_at=ruleset.activated_at,
            )
        )
        if ruleset.criteria:
            await self._session.execute(
                insert(_CRITERIA),
                [
                    {
                        "id": new_id("rcr"),
                        "ruleset_id": ruleset.id,
                        "criterion_key": item.criterion_key,
                        "family": item.family.value,
                        "direction": item.direction.value,
                        "default_strength": item.default_strength.value,
                        "description": item.description,
                        "permitted_strengths": [
                            strength.value for strength in item.allowed_strengths
                        ],
                        "evidence_categories": list(item.evidence_categories),
                        "requires_evidence": item.requires_evidence,
                        "display_order": item.display_order,
                        "metadata_json": item.metadata or None,
                    }
                    for item in ruleset.criteria
                ],
            )
        if ruleset.combination_rules:
            await self._session.execute(
                insert(_RULES),
                [
                    {
                        "id": new_id("rcb"),
                        "ruleset_id": ruleset.id,
                        "rule_key": rule.rule_key,
                        "classification": rule.classification.value,
                        "description": rule.description,
                        "requirements": rule.requirements or None,
                        "precedence": rule.precedence,
                    }
                    for rule in ruleset.combination_rules
                ],
            )
        return ruleset

    async def _hydrate(self, row: Mapping[str, Any]) -> RulesetRecord:
        criteria = await self._fetch_all(
            select(_CRITERIA)
            .where(_CRITERIA.c.ruleset_id == row["id"])
            .order_by(_CRITERIA.c.display_order.asc(), _CRITERIA.c.criterion_key.asc())
        )
        rules = await self._fetch_all(
            select(_RULES)
            .where(_RULES.c.ruleset_id == row["id"])
            .order_by(_RULES.c.precedence.asc(), _RULES.c.rule_key.asc())
        )
        return _to_ruleset(
            row,
            criteria=[_to_criterion(item) for item in criteria],
            rules=[_to_rule(item) for item in rules],
        )

    async def get(self, ruleset_id: str) -> RulesetRecord | None:
        row = await self._fetch_one(select(_RULESETS).where(_RULESETS.c.id == ruleset_id))
        return await self._hydrate(row) if row else None

    async def get_by_version(
        self, *, ruleset_key: str, version: str
    ) -> RulesetRecord | None:
        row = await self._fetch_one(
            select(_RULESETS).where(
                _RULESETS.c.ruleset_key == ruleset_key, _RULESETS.c.version == version
            )
        )
        return await self._hydrate(row) if row else None

    async def save_lifecycle(self, ruleset: RulesetRecord) -> RulesetRecord:
        """Persist lifecycle state only; registered content is immutable."""
        result = await self._session.execute(
            update(_RULESETS)
            .where(_RULESETS.c.id == ruleset.id)
            .values(
                state=ruleset.state.value,
                activated_at=ruleset.activated_at,
                deprecated_at=ruleset.deprecated_at,
                retired_at=ruleset.retired_at,
                invalidated_at=ruleset.invalidated_at,
                invalidation_reason=ruleset.invalidation_reason,
                effective_to=ruleset.effective_to,
            )
        )
        if result.rowcount == 0:
            raise NotFoundError("ruleset", ruleset.id)
        return ruleset

    async def list_rulesets(
        self,
        *,
        page: Page,
        ruleset_key: str | None = None,
        gene_symbol: str | None = None,
        usable_only: bool = False,
    ) -> Paged[RulesetRecord]:
        statement: Select = select(_RULESETS)
        if ruleset_key is not None:
            statement = statement.where(_RULESETS.c.ruleset_key == ruleset_key)
        if gene_symbol is not None:
            statement = statement.where(_RULESETS.c.gene_symbol == gene_symbol)
        if usable_only:
            statement = statement.where(_RULESETS.c.state.in_(_USABLE))
        statement = statement.order_by(
            _RULESETS.c.ruleset_key.asc(), _RULESETS.c.version.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        items = tuple([await self._hydrate(row) for row in rows])
        return Paged(items=items, total=total, page=page)


def _evaluation_values(record: ClassificationEvaluationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "project_id": record.project_id,
        "variant_id": record.variant_id,
        "ruleset_id": record.ruleset_id,
        "ruleset_key": record.ruleset_key,
        "ruleset_version": record.ruleset_version,
        "state": record.state.value,
        "gene_symbol": record.gene_symbol,
        "transcript_identifier": record.transcript_identifier,
        "condition_identifier": record.condition_identifier,
        "condition_term": record.condition_term,
        "inheritance": record.inheritance,
        "genome_assembly": record.genome_assembly,
        "reference_genome_resource_id": record.reference_genome_resource_id,
        "evidence_ids": list(record.evidence_ids),
        "input_digest": record.input_digest,
        "configuration_digest": record.configuration_digest,
        "capability_id": record.capability_id,
        "capability_version": record.capability_version,
        "engine_resource_id": record.engine_resource_id,
        "engine_version": record.engine_version,
        "environment_version": record.environment_version,
        "container_image_digest": record.container_image_digest,
        "node_identity": record.node_identity,
        "scientific_execution_id": record.scientific_execution_id,
        "job_id": record.job_id,
        "correlation_id": record.correlation_id,
        "idempotency_key": record.idempotency_key,
        "requested_by": record.requested_by,
        "requested_at": record.requested_at,
        "submitted_at": record.submitted_at,
        "completed_at": record.completed_at,
        "classification_id": record.classification_id,
        "failure_code": record.failure_code,
        "failure_message": record.failure_message,
        "benchmark_case_id": record.benchmark_case_id,
        "metadata_json": record.metadata or None,
    }


def _to_evaluation(row: Mapping[str, Any]) -> ClassificationEvaluationRecord:
    return ClassificationEvaluationRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        variant_id=row["variant_id"],
        ruleset_id=row["ruleset_id"],
        ruleset_key=row["ruleset_key"],
        ruleset_version=row["ruleset_version"],
        state=ClassificationEvaluationState(row["state"]),
        project_id=row["project_id"],
        gene_symbol=row["gene_symbol"],
        transcript_identifier=row["transcript_identifier"],
        condition_identifier=row["condition_identifier"],
        condition_term=row["condition_term"],
        inheritance=row["inheritance"],
        genome_assembly=row["genome_assembly"],
        reference_genome_resource_id=row["reference_genome_resource_id"],
        evidence_ids=_string_list(row["evidence_ids"]),
        input_digest=row["input_digest"],
        configuration_digest=row["configuration_digest"],
        capability_id=row["capability_id"],
        capability_version=row["capability_version"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        container_image_digest=row["container_image_digest"],
        node_identity=row["node_identity"],
        scientific_execution_id=row["scientific_execution_id"],
        job_id=row["job_id"],
        correlation_id=row["correlation_id"],
        idempotency_key=row["idempotency_key"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        submitted_at=row["submitted_at"],
        completed_at=row["completed_at"],
        classification_id=row["classification_id"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        benchmark_case_id=row["benchmark_case_id"],
        metadata=_mapping(row["metadata_json"]),
        created_at=row["created_at"],
        record_version=int(row.get("version") or 1),
    )


def _to_classification(row: Mapping[str, Any]) -> AutomatedClassificationRecord:
    return AutomatedClassificationRecord(
        id=row["id"],
        evaluation_id=row["evaluation_id"],
        workspace_id=row["workspace_id"],
        variant_id=row["variant_id"],
        ruleset_id=row["ruleset_id"],
        ruleset_key=row["ruleset_key"],
        ruleset_version=row["ruleset_version"],
        classification=Classification(row["classification"]),
        version_number=int(row["version_number"]),
        project_id=row["project_id"],
        decision_role=ClassificationDecisionRole(row["decision_role"]),
        combination_rule_key=row["combination_rule_key"],
        rationale=row["rationale"],
        condition_identifier=row["condition_identifier"],
        gene_symbol=row["gene_symbol"],
        applied_criterion_keys=_string_list(row["applied_criterion_keys"]),
        criterion_evaluation_ids=_string_list(row["criterion_evaluation_ids"]),
        evidence_ids=_string_list(row["evidence_ids"]),
        computation=_mapping(row["computation"]),
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        container_image_digest=row["container_image_digest"],
        node_identity=row["node_identity"],
        scientific_execution_id=row["scientific_execution_id"],
        contract_version=row["contract_version"],
        input_digest=row["input_digest"],
        configuration_digest=row["configuration_digest"],
        payload_digest=row["payload_digest"],
        provenance=_mapping(row["provenance"]),
        supersedes_id=row["supersedes_id"],
        superseded_by_id=row["superseded_by_id"],
        is_development_payload=bool(row["is_development_payload"]),
        produced_at=row["produced_at"],
        created_at=row["created_at"],
    )


def _to_criterion_evaluation(row: Mapping[str, Any]) -> CriterionEvaluationRecord:
    return CriterionEvaluationRecord(
        id=row["id"],
        variant_id=row["variant_id"],
        ruleset_id=row["ruleset_id"] or "",
        ruleset_version=row["ruleset_version"],
        criterion_key=row["criterion_key"],
        applied=bool(row["applied"]),
        strength=CriterionStrength(row["strength"]),
        direction=CriterionDirection(row["direction"]),
        origin=DataOrigin(row["origin"]),
        evaluated_at=row["evaluated_at"],
        family=CriterionFamily(row["family"]) if row["family"] else None,
        classification_evaluation_id=row["classification_evaluation_id"],
        interpretation_id=row["interpretation_id"],
        interpretation_version_id=row["interpretation_version_id"],
        rationale=row["rationale"],
        evaluated_by_user_id=row["evaluated_by_user_id"],
        evaluation_method=row["evaluation_method"],
        scientific_execution_id=row["scientific_execution_id"],
        supersedes_evaluation_id=row["supersedes_evaluation_id"],
        is_override=bool(row["is_override"]),
        override_reason=row["override_reason"],
        details=_mapping(row["details"]),
        created_at=row["created_at"],
    )


class SqlClassificationEvaluationRepository(SqlRepository):
    """Automated evaluations, their criterion evaluations and their suggestions."""

    async def add(
        self, evaluation: ClassificationEvaluationRecord
    ) -> ClassificationEvaluationRecord:
        await self._session.execute(insert(_EVALUATIONS).values(**_evaluation_values(evaluation)))
        return evaluation

    async def get(self, evaluation_id: str) -> ClassificationEvaluationRecord | None:
        row = await self._fetch_one(
            select(_EVALUATIONS).where(_EVALUATIONS.c.id == evaluation_id)
        )
        return _to_evaluation(row) if row else None

    async def get_by_idempotency_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> ClassificationEvaluationRecord | None:
        row = await self._fetch_one(
            select(_EVALUATIONS).where(
                _EVALUATIONS.c.workspace_id == workspace_id,
                _EVALUATIONS.c.idempotency_key == idempotency_key,
            )
        )
        return _to_evaluation(row) if row else None

    async def save(
        self, evaluation: ClassificationEvaluationRecord
    ) -> ClassificationEvaluationRecord:
        """Version-checked update: a stale writer never clobbers a newer state."""
        values = _evaluation_values(evaluation)
        values.pop("id")
        new_version = await self._versioned_update(
            _EVALUATIONS,
            entity_id=evaluation.id,
            expected_version=evaluation.record_version,
            values=values,
        )
        return replace(evaluation, record_version=new_version)

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
        statement: Select = select(_EVALUATIONS)
        if workspace_ids is not None:
            statement = statement.where(
                _EVALUATIONS.c.workspace_id.in_(tuple(workspace_ids) or ("",))
            )
        if variant_id is not None:
            statement = statement.where(_EVALUATIONS.c.variant_id == variant_id)
        if ruleset_id is not None:
            statement = statement.where(_EVALUATIONS.c.ruleset_id == ruleset_id)
        if project_id is not None:
            statement = statement.where(_EVALUATIONS.c.project_id == project_id)
        if state is not None:
            statement = statement.where(_EVALUATIONS.c.state == state.value)
        statement = statement.order_by(_EVALUATIONS.c.created_at.desc())
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(
            items=tuple(_to_evaluation(row) for row in rows), total=total, page=page
        )

    async def add_classification(
        self, classification: AutomatedClassificationRecord
    ) -> AutomatedClassificationRecord:
        await self._session.execute(
            insert(_CLASSIFICATIONS).values(
                id=classification.id,
                evaluation_id=classification.evaluation_id,
                workspace_id=classification.workspace_id,
                project_id=classification.project_id,
                variant_id=classification.variant_id,
                ruleset_id=classification.ruleset_id,
                ruleset_key=classification.ruleset_key,
                ruleset_version=classification.ruleset_version,
                classification=classification.classification.value,
                version_number=classification.version_number,
                # Fixed, never taken from the payload: this table holds suggestions.
                decision_role=ClassificationDecisionRole.AUTOMATED_SUGGESTION.value,
                combination_rule_key=classification.combination_rule_key,
                rationale=classification.rationale,
                gene_symbol=classification.gene_symbol,
                condition_identifier=classification.condition_identifier,
                applied_criterion_keys=list(classification.applied_criterion_keys),
                criterion_evaluation_ids=list(classification.criterion_evaluation_ids),
                evidence_ids=list(classification.evidence_ids),
                computation=classification.computation or None,
                engine_resource_id=classification.engine_resource_id,
                engine_version=classification.engine_version,
                environment_version=classification.environment_version,
                container_image_digest=classification.container_image_digest,
                node_identity=classification.node_identity,
                scientific_execution_id=classification.scientific_execution_id,
                contract_version=classification.contract_version,
                input_digest=classification.input_digest,
                configuration_digest=classification.configuration_digest,
                payload_digest=classification.payload_digest,
                provenance=classification.provenance or None,
                supersedes_id=classification.supersedes_id,
                is_development_payload=classification.is_development_payload,
                produced_at=classification.produced_at,
            )
        )
        return classification

    async def get_classification(
        self, classification_id: str
    ) -> AutomatedClassificationRecord | None:
        row = await self._fetch_one(
            select(_CLASSIFICATIONS).where(_CLASSIFICATIONS.c.id == classification_id)
        )
        return _to_classification(row) if row else None

    async def mark_superseded(
        self, *, classification_id: str, superseded_by_id: str
    ) -> None:
        """Point an older suggestion at its replacement. Content is untouched."""
        await self._session.execute(
            update(_CLASSIFICATIONS)
            .where(_CLASSIFICATIONS.c.id == classification_id)
            .values(superseded_by_id=superseded_by_id)
        )

    async def current_classification(
        self,
        *,
        variant_id: str,
        ruleset_id: str,
        condition_identifier: str | None = None,
    ) -> AutomatedClassificationRecord | None:
        statement: Select = select(_CLASSIFICATIONS).where(
            _CLASSIFICATIONS.c.variant_id == variant_id,
            _CLASSIFICATIONS.c.ruleset_id == ruleset_id,
            _CLASSIFICATIONS.c.superseded_by_id.is_(None),
        )
        if condition_identifier is None:
            statement = statement.where(_CLASSIFICATIONS.c.condition_identifier.is_(None))
        else:
            statement = statement.where(
                _CLASSIFICATIONS.c.condition_identifier == condition_identifier
            )
        statement = statement.order_by(_CLASSIFICATIONS.c.version_number.desc())
        row = await self._fetch_one(statement)
        return _to_classification(row) if row else None

    async def classification_history(
        self,
        *,
        variant_id: str,
        workspace_ids: frozenset[str] | None = None,
        ruleset_id: str | None = None,
        limit: int = 100,
    ) -> tuple[AutomatedClassificationRecord, ...]:
        statement: Select = select(_CLASSIFICATIONS).where(
            _CLASSIFICATIONS.c.variant_id == variant_id
        )
        if workspace_ids is not None:
            statement = statement.where(
                _CLASSIFICATIONS.c.workspace_id.in_(tuple(workspace_ids) or ("",))
            )
        if ruleset_id is not None:
            statement = statement.where(_CLASSIFICATIONS.c.ruleset_id == ruleset_id)
        statement = statement.order_by(
            _CLASSIFICATIONS.c.ruleset_key.asc(),
            _CLASSIFICATIONS.c.version_number.desc(),
        ).limit(limit)
        rows = await self._fetch_all(statement)
        return tuple(_to_classification(row) for row in rows)

    async def add_criterion_evaluations(
        self, evaluations: tuple[CriterionEvaluationRecord, ...]
    ) -> None:
        if not evaluations:
            return
        await self._session.execute(
            insert(_CRITERION_EVALUATIONS),
            [
                {
                    "id": item.id,
                    "variant_id": item.variant_id,
                    "interpretation_id": item.interpretation_id,
                    "interpretation_version_id": item.interpretation_version_id,
                    # The shared registry row, kept for the pre-existing column.
                    "ruleset_resource_id": item.ruleset_id,
                    "ruleset_id": item.ruleset_id,
                    "ruleset_version": item.ruleset_version,
                    "classification_evaluation_id": item.classification_evaluation_id,
                    "criterion_key": item.criterion_key,
                    "family": item.family.value if item.family else None,
                    "applied": item.applied,
                    "strength": item.strength.value,
                    "direction": item.direction.value,
                    "rationale": item.rationale,
                    "origin": item.origin.value,
                    "evaluated_by_user_id": item.evaluated_by_user_id,
                    "evaluation_method": item.evaluation_method,
                    "scientific_execution_id": item.scientific_execution_id,
                    "evaluated_at": item.evaluated_at,
                    "supersedes_evaluation_id": item.supersedes_evaluation_id,
                    "is_override": item.is_override,
                    "override_reason": item.override_reason,
                    "details": item.details or None,
                }
                for item in evaluations
            ],
        )
        links = [
            {
                "id": new_id("cee"),
                "criterion_evaluation_id": item.id,
                "evidence_item_id": evidence_id,
            }
            for item in evaluations
            for evidence_id in item.evidence_ids
        ]
        if links:
            await self._session.execute(insert(_CRITERION_EVIDENCE), links)

    async def list_criterion_evaluations(
        self, *, classification_evaluation_id: str
    ) -> tuple[CriterionEvaluationRecord, ...]:
        rows = await self._fetch_all(
            select(_CRITERION_EVALUATIONS)
            .where(
                _CRITERION_EVALUATIONS.c.classification_evaluation_id
                == classification_evaluation_id
            )
            .order_by(_CRITERION_EVALUATIONS.c.criterion_key.asc())
        )
        records = [_to_criterion_evaluation(row) for row in rows]
        if not records:
            return ()
        evidence_rows = await self._fetch_all(
            select(_CRITERION_EVIDENCE).where(
                _CRITERION_EVIDENCE.c.criterion_evaluation_id.in_(
                    tuple(item.id for item in records)
                )
            )
        )
        by_evaluation: dict[str, list[str]] = {}
        for row in evidence_rows:
            by_evaluation.setdefault(row["criterion_evaluation_id"], []).append(
                row["evidence_item_id"]
            )
        return tuple(
            replace(item, evidence_ids=tuple(by_evaluation.get(item.id, ())))
            for item in records
        )


def _to_case(row: Mapping[str, Any]) -> BenchmarkCaseRecord:
    expected = row["expected_classification"]
    return BenchmarkCaseRecord(
        id=row["id"],
        ruleset_id=row["ruleset_id"],
        case_key=row["case_key"],
        validation_kind=BenchmarkValidationKind(row["validation_kind"]),
        input_snapshot=_mapping(row["input_snapshot"]),
        expected_criteria=_mapping(row["expected_criteria"]),
        expected_classification=Classification(expected) if expected else None,
        description=row["description"],
        source_reference=row["source_reference"],
        is_active=bool(row["is_active"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _comparison_payload(comparison: BenchmarkComparison) -> dict[str, Any]:
    return {
        "case_id": comparison.case_id,
        "case_key": comparison.case_key,
        "outcome": comparison.outcome.value,
        "validation_kind": comparison.validation_kind.value,
        "expected_classification": comparison.expected_classification,
        "observed_classification": comparison.observed_classification,
        "criterion_differences": list(comparison.criterion_differences),
        "severity": comparison.severity.value,
        "detail": comparison.detail,
    }


def _to_comparison(payload: Mapping[str, Any]) -> BenchmarkComparison:
    return BenchmarkComparison(
        case_id=payload["case_id"],
        case_key=payload["case_key"],
        outcome=BenchmarkCaseOutcome(payload["outcome"]),
        validation_kind=BenchmarkValidationKind(payload["validation_kind"]),
        expected_classification=payload.get("expected_classification"),
        observed_classification=payload.get("observed_classification"),
        criterion_differences=tuple(payload.get("criterion_differences") or ()),
        severity=ValidationSeverity(payload.get("severity", ValidationSeverity.INFO.value)),
        detail=payload.get("detail"),
    )


def _to_run(row: Mapping[str, Any]) -> BenchmarkRunRecord:
    raw = row["comparisons"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    comparisons = tuple(_to_comparison(item) for item in (raw or ()))
    return BenchmarkRunRecord(
        id=row["id"],
        ruleset_id=row["ruleset_id"],
        ruleset_key=row["ruleset_key"],
        ruleset_version=row["ruleset_version"],
        validation_kind=BenchmarkValidationKind(row["validation_kind"]),
        case_count=int(row["case_count"]),
        matched_count=int(row["matched_count"]),
        mismatched_count=int(row["mismatched_count"]),
        not_evaluated_count=int(row["not_evaluated_count"]),
        comparisons=comparisons,
        is_accuracy_run=bool(row["is_accuracy_run"]),
        executed_by=row["executed_by"],
        executed_at=row["executed_at"],
        created_at=row["created_at"],
    )


class SqlRulesetBenchmarkRepository(SqlRepository):
    """Benchmark cases and runs for one ruleset version."""

    async def add_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord:
        await self._session.execute(
            insert(_CASES).values(
                id=case.id,
                ruleset_id=case.ruleset_id,
                case_key=case.case_key,
                validation_kind=case.validation_kind.value,
                description=case.description,
                input_snapshot=case.input_snapshot or None,
                expected_criteria=case.expected_criteria or None,
                expected_classification=case.expected_classification.value
                if case.expected_classification
                else None,
                source_reference=case.source_reference,
                is_active=case.is_active,
                created_by=case.created_by,
            )
        )
        return case

    async def get_case(self, case_id: str) -> BenchmarkCaseRecord | None:
        row = await self._fetch_one(select(_CASES).where(_CASES.c.id == case_id))
        return _to_case(row) if row else None

    async def get_case_by_key(
        self, *, ruleset_id: str, case_key: str
    ) -> BenchmarkCaseRecord | None:
        row = await self._fetch_one(
            select(_CASES).where(
                _CASES.c.ruleset_id == ruleset_id, _CASES.c.case_key == case_key
            )
        )
        return _to_case(row) if row else None

    async def list_cases(
        self,
        *,
        ruleset_id: str,
        validation_kind: BenchmarkValidationKind | None = None,
        active_only: bool = True,
    ) -> tuple[BenchmarkCaseRecord, ...]:
        statement: Select = select(_CASES).where(_CASES.c.ruleset_id == ruleset_id)
        if validation_kind is not None:
            statement = statement.where(_CASES.c.validation_kind == validation_kind.value)
        if active_only:
            statement = statement.where(_CASES.c.is_active.is_(True))
        rows = await self._fetch_all(statement.order_by(_CASES.c.case_key.asc()))
        return tuple(_to_case(row) for row in rows)

    async def add_run(self, run: BenchmarkRunRecord) -> BenchmarkRunRecord:
        await self._session.execute(
            insert(_RUNS).values(
                id=run.id,
                ruleset_id=run.ruleset_id,
                ruleset_key=run.ruleset_key,
                ruleset_version=run.ruleset_version,
                validation_kind=run.validation_kind.value,
                case_count=run.case_count,
                matched_count=run.matched_count,
                mismatched_count=run.mismatched_count,
                not_evaluated_count=run.not_evaluated_count,
                comparisons=[_comparison_payload(item) for item in run.comparisons],
                is_accuracy_run=run.is_accuracy_run,
                executed_by=run.executed_by,
                executed_at=run.executed_at,
            )
        )
        return run

    async def get_run(self, run_id: str) -> BenchmarkRunRecord | None:
        row = await self._fetch_one(select(_RUNS).where(_RUNS.c.id == run_id))
        return _to_run(row) if row else None

    async def list_runs(self, *, ruleset_id: str, page: Page) -> Paged[BenchmarkRunRecord]:
        statement: Select = (
            select(_RUNS)
            .where(_RUNS.c.ruleset_id == ruleset_id)
            .order_by(_RUNS.c.created_at.desc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_run(row) for row in rows), total=total, page=page)


__all__ = [
    "SqlClassificationEvaluationRepository",
    "SqlRulesetBenchmarkRepository",
    "SqlRulesetRepository",
]
