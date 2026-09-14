"""Registering, governing and reading interpretation ruleset versions.

A ruleset version is registered once, with its criteria and combination rules, and
is then immutable. Nothing in this module edits a registered version: a corrected
guideline, a modified criterion strength, a ClinGen gene/disease specification or a
different combination strategy is a *new* version of the same ruleset key. That is
the whole mechanism by which a classification produced last year remains
explainable — the rule text it named still exists, unchanged.

Lifecycle is the only mutation, and it is validated by the shared scientific
resource lifecycle so a ruleset cannot silently leave or re-enter usable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.interpretation.dependencies import (
    InterpretationServices,
    readable_workspace_scope,
    require_platform_administration,
    require_platform_read,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.interpretation.entities import (
    CombinationRule,
    CriterionDefinition,
    RulesetRecord,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    RulesetCombinationStrategy,
    RulesetSpecificationScope,
    ScientificResourceState,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class RegisterRulesetCommand:
    actor: ActorContext
    request: RequestContext
    ruleset_key: str
    version: str
    display_name: str
    guideline_source: str
    criteria: tuple[CriterionDefinition, ...]
    combination_rules: tuple[CombinationRule, ...]
    description: str | None = None
    guideline_citation: str | None = None
    publication_reference: str | None = None
    publication_year: int | None = None
    specification_scope: RulesetSpecificationScope = RulesetSpecificationScope.GENERAL
    gene_symbol: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    combination_strategy: RulesetCombinationStrategy = (
        RulesetCombinationStrategy.CRITERIA_COMBINATION
    )
    effective_from: Any | None = None
    effective_to: Any | None = None
    capability_id: str | None = None
    capability_version: str | None = None
    engine_resource_id: str | None = None
    genome_assembly: str | None = None
    provenance: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TransitionRulesetCommand:
    actor: ActorContext
    request: RequestContext
    ruleset_id: str
    state: ScientificResourceState
    reason: str | None = None


class RegisterRuleset:
    """Register one immutable ruleset version. Platform governance only."""

    def __init__(self, services: InterpretationServices) -> None:
        self._services = services

    async def execute(self, command: RegisterRulesetCommand) -> RulesetRecord:
        now = self._services.clock.now()
        if not command.criteria:
            raise ValidationError(
                "a ruleset version must declare at least one criterion",
                details={"field": "criteria"},
            )
        if not command.combination_rules:
            # Without combination rules the version could never explain how it
            # reached a classification, which is exactly what must not happen.
            raise ValidationError(
                "a ruleset version must declare how criteria combine into a "
                "classification",
                details={"field": "combination_rules"},
            )
        duplicate_criteria = _first_duplicate(
            item.criterion_key for item in command.criteria
        )
        if duplicate_criteria is not None:
            raise ValidationError(
                "a criterion key is declared twice in this ruleset version",
                details={"criterion_key": duplicate_criteria},
            )
        duplicate_rule = _first_duplicate(
            rule.rule_key for rule in command.combination_rules
        )
        if duplicate_rule is not None:
            raise ValidationError(
                "a combination rule key is declared twice in this ruleset version",
                details={"rule_key": duplicate_rule},
            )
        if command.specification_scope in {
            RulesetSpecificationScope.GENE_SPECIFIC,
            RulesetSpecificationScope.GENE_DISEASE_SPECIFIC,
        } and not (command.gene_symbol or "").strip():
            raise ValidationError(
                "a gene-scoped specification must name its gene",
                details={"field": "gene_symbol"},
            )

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await require_platform_administration(
                self._services, command.actor, recorder=recorder, occurred_at=now
            )
            existing = await repositories.rulesets.get_by_version(
                ruleset_key=command.ruleset_key, version=command.version
            )
            if existing is not None:
                # Re-registering an identity would make two different rule texts
                # answer to the same version. Refused, never merged.
                raise ConflictError(
                    "this ruleset version is already registered",
                    details={
                        "ruleset_key": command.ruleset_key,
                        "version": command.version,
                    },
                )

            record = RulesetRecord(
                id=new_id("rst"),
                ruleset_key=command.ruleset_key,
                version=command.version,
                display_name=command.display_name,
                guideline_source=command.guideline_source,
                state=ScientificResourceState.REGISTERED,
                description=command.description,
                guideline_citation=command.guideline_citation,
                publication_reference=command.publication_reference,
                publication_year=command.publication_year,
                specification_scope=command.specification_scope,
                gene_symbol=command.gene_symbol,
                condition_identifier=command.condition_identifier,
                condition_term=command.condition_term,
                combination_strategy=command.combination_strategy,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                capability_id=command.capability_id,
                capability_version=command.capability_version,
                engine_resource_id=command.engine_resource_id,
                genome_assembly=command.genome_assembly,
                criteria=tuple(command.criteria),
                combination_rules=tuple(command.combination_rules),
                provenance=dict(command.provenance or {}),
                metadata=dict(command.metadata or {}),
                registered_by=command.actor.actor_id,
                created_at=now,
            ).with_digest()
            stored = await repositories.rulesets.add(record)

            await recorder.audit(
                action="ruleset.registered",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation_ruleset",
                resource_id=stored.id,
                new_state=stored.state.value,
                detail={
                    "ruleset_key": stored.ruleset_key,
                    "version": stored.version,
                    "guideline_source": stored.guideline_source,
                    "specification_scope": stored.specification_scope.value,
                    "configuration_digest": stored.configuration_digest,
                    "criterion_count": len(stored.criteria),
                },
            )
            await recorder.event(
                event_type=EventType.RULESET_REGISTERED,
                aggregate_type="interpretation_ruleset",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "ruleset_key": stored.ruleset_key,
                    "version": stored.version,
                    "configuration_digest": stored.configuration_digest,
                },
            )
            return stored


class TransitionRuleset:
    """Activate, deprecate, retire or invalidate a registered ruleset version.

    Historical classifications are untouched by this: they name the version they
    were produced under, and that row keeps existing in whatever state it reaches.
    """

    def __init__(self, services: InterpretationServices) -> None:
        self._services = services

    async def execute(self, command: TransitionRulesetCommand) -> RulesetRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await require_platform_administration(
                self._services, command.actor, recorder=recorder, occurred_at=now
            )
            record = await repositories.rulesets.get(command.ruleset_id)
            if record is None:
                raise NotFoundError("interpretation_ruleset", command.ruleset_id)
            if (
                command.state is ScientificResourceState.INVALIDATED
                and not (command.reason or "").strip()
            ):
                raise ValidationError(
                    "invalidating a ruleset version requires a stated reason",
                    details={"field": "reason"},
                )
            previous = record.state
            updated = record.transition_to(command.state, at=now, reason=command.reason)
            stored = await repositories.rulesets.save_lifecycle(updated)

            await recorder.audit(
                action="ruleset.state_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation_ruleset",
                resource_id=stored.id,
                previous_state=previous.value,
                new_state=stored.state.value,
                detail={
                    "ruleset_key": stored.ruleset_key,
                    "version": stored.version,
                    "reason": command.reason,
                },
            )
            await recorder.event(
                event_type=EventType.RULESET_STATE_CHANGED,
                aggregate_type="interpretation_ruleset",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "previous_state": previous.value,
                    "state": stored.state.value,
                    "ruleset_key": stored.ruleset_key,
                    "version": stored.version,
                },
            )
            return stored


@dataclass(frozen=True, slots=True)
class RulesetReader:
    """Reads of the ruleset registry.

    Ordinary users may see which ruleset versions are usable, because a reviewer
    has to know what a classification was produced under. They get no governance:
    reading the registry never implies changing it.
    """

    services: InterpretationServices

    async def list_rulesets(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        page: Page,
        ruleset_key: str | None = None,
        gene_symbol: str | None = None,
        usable_only: bool = True,
    ) -> Paged[RulesetRecord]:
        now = self.services.clock.now()
        async with self.services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            if not usable_only:
                # Seeing retired and invalidated versions is governance visibility.
                await require_platform_read(
                    self.services, actor, recorder=recorder, occurred_at=now
                )
            elif not readable_workspace_scope(actor) and not actor.platform_permissions:
                await require_platform_read(
                    self.services, actor, recorder=recorder, occurred_at=now
                )
            return await repositories.rulesets.list_rulesets(
                page=page,
                ruleset_key=ruleset_key,
                gene_symbol=gene_symbol,
                usable_only=usable_only,
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, *, ruleset_id: str
    ) -> RulesetRecord:
        now = self.services.clock.now()
        async with self.services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            record = await repositories.rulesets.get(ruleset_id)
            if record is None:
                raise NotFoundError("interpretation_ruleset", ruleset_id)
            if not record.is_usable:
                await require_platform_read(
                    self.services, actor, recorder=recorder, occurred_at=now
                )
            return record


def _first_duplicate(values) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


__all__ = [
    "RegisterRuleset",
    "RegisterRulesetCommand",
    "RulesetReader",
    "TransitionRuleset",
    "TransitionRulesetCommand",
]
