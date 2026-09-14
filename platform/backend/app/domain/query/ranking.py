"""Ranking: deterministic prioritization, kept apart from filtering.

Ranking answers "in what order should the variants that survived the filter be
presented", and nothing else. It never adds a variant back, never removes one,
and never produces a scientific statement. The score it computes is a
**prioritization score**: a transparent, versioned, weighted combination of values
that the scientific data layer already recorded. It is not a pathogenicity
estimate, not a clinical conclusion and not evidence.

Three rules make that claim defensible:

* **No hidden priority.** Every component is declared in the configuration —
  which field, which transformation, which weight, and for a categorical
  component the full ordered list of terms. The platform ships no built-in
  opinion that "rare means important" or that a consequence term is severe.
* **Missing stays missing.** A component whose value was never reported does not
  contribute, and is reported as missing. It is never scored as zero, because
  "unreported" and "reported as zero" mean different things.
* **Determinism.** The same configuration over the same rows yields the same
  scores and the same order, with an explicit tie-breaker so equal scores never
  depend on the engine's row order.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.domain.errors import ValidationError
from app.domain.query.fields import (
    FilterFieldDefinition,
    FilterFieldRegistry,
)
from app.domain.query.operators import NUMERIC_DATA_TYPES, FilterDataType
from app.domain.value_objects.enums import StrEnum, ValueSemantics


class RankingDirection(StrEnum):
    """Whether a higher score is presented first."""

    DESCENDING = "descending"
    ASCENDING = "ascending"


class RankingComponentKind(StrEnum):
    """The declared transformation from a stored value to a 0..1 component.

    Each is a *stated* transformation supplied by the configuration author. None
    of them encodes a scientific judgement of its own.
    """

    #: Lower stored value yields a higher component, over a declared scale.
    NUMERIC_ASCENDING = "numeric_ascending"
    #: Higher stored value yields a higher component, over a declared scale.
    NUMERIC_DESCENDING = "numeric_descending"
    #: Position in an explicitly ordered list of terms supplied by the author.
    CATEGORY_PRIORITY = "category_priority"
    #: 1.0 when a value was reported at all, 0.0 when it was reported as absent.
    PRESENCE = "presence"


class RankingMissingBehaviour(StrEnum):
    """What happens when a component's value was not reported."""

    #: The component contributes nothing and is reported as missing.
    EXCLUDE = "exclude"
    #: The component contributes a declared floor value, stated by the author.
    FLOOR = "floor"


@dataclass(frozen=True, slots=True)
class RankingComponent:
    """One weighted contribution to a prioritization score."""

    field_id: str
    kind: RankingComponentKind
    weight: float
    #: Declared numeric scale for the numeric kinds. Both bounds are required so
    #: the normalization is reproducible and inspectable.
    scale_min: float | None = None
    scale_max: float | None = None
    #: Ordered terms, highest priority first, for ``CATEGORY_PRIORITY``.
    category_priority: tuple[str, ...] = ()
    missing_behaviour: RankingMissingBehaviour = RankingMissingBehaviour.EXCLUDE
    missing_floor: float = 0.0
    label: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "field_id": self.field_id,
            "kind": self.kind.value,
            "weight": self.weight,
            "missing_behaviour": self.missing_behaviour.value,
        }
        if self.scale_min is not None:
            payload["scale_min"] = self.scale_min
        if self.scale_max is not None:
            payload["scale_max"] = self.scale_max
        if self.category_priority:
            payload["category_priority"] = list(self.category_priority)
        if self.missing_behaviour is RankingMissingBehaviour.FLOOR:
            payload["missing_floor"] = self.missing_floor
        if self.label:
            payload["label"] = self.label
        return payload


@dataclass(frozen=True, slots=True)
class RankingConfigurationSpec:
    """A complete, executable ranking configuration."""

    method_id: str
    method_version: str
    components: tuple[RankingComponent, ...] = ()
    direction: RankingDirection = RankingDirection.DESCENDING
    #: Field identifiers applied in order when scores are equal. A deterministic
    #: order is a correctness property, not a nicety.
    tie_breakers: tuple[str, ...] = ("contig", "position", "reference_allele", "alternate_allele")
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "method_version": self.method_version,
            "direction": self.direction.value,
            "tie_breakers": list(self.tie_breakers),
            "components": [component.to_payload() for component in self.components],
            "parameters": dict(sorted(self.parameters.items())),
        }


@dataclass(frozen=True, slots=True)
class RankingMethodDefinition:
    """A registered ranking method."""

    id: str
    name: str
    description: str
    version: str
    #: Implementation this identifier resolves to. Recorded on every execution so
    #: a historical ranking can be traced to the code that produced it.
    implementation_id: str
    supported_component_kinds: tuple[RankingComponentKind, ...]
    requires_components: bool = True
    min_components: int = 1
    max_components: int = 12
    supported_parameters: tuple[str, ...] = ()
    #: Data contexts the method applies to, matching the field dictionary's
    #: context vocabulary.
    supported_contexts: tuple[str, ...] = ("result_set",)
    deterministic: bool = True
    available: bool = True
    #: Whether the method makes a claim requiring separate scientific validation.
    #: Every shipped method is prioritization only, so this is false throughout.
    scientifically_validated: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "implementation_id": self.implementation_id,
            "supported_component_kinds": [
                kind.value for kind in self.supported_component_kinds
            ],
            "requires_components": self.requires_components,
            "min_components": self.min_components,
            "max_components": self.max_components,
            "supported_parameters": list(self.supported_parameters),
            "supported_contexts": list(self.supported_contexts),
            "deterministic": self.deterministic,
            "available": self.available,
            "scientifically_validated": self.scientifically_validated,
        }


WEIGHTED_FIELD_SCORE = RankingMethodDefinition(
    id="weighted_field_score",
    name="Weighted field score",
    description=(
        "Sums declared components, each a transformation of one recorded field "
        "multiplied by its declared weight. Every component, scale and category "
        "order is supplied by the configuration; the method itself holds no "
        "scientific assumption. The result is a prioritization score, not a "
        "clinical or pathogenicity conclusion."
    ),
    version="1.0.0",
    implementation_id="app.domain.query.ranking:weighted_field_score",
    supported_component_kinds=(
        RankingComponentKind.NUMERIC_ASCENDING,
        RankingComponentKind.NUMERIC_DESCENDING,
        RankingComponentKind.CATEGORY_PRIORITY,
        RankingComponentKind.PRESENCE,
    ),
    supported_parameters=("normalize_by_present_weight",),
)

FIELD_ORDER = RankingMethodDefinition(
    id="field_order",
    name="Field order",
    description=(
        "Orders rows by one recorded field in a declared direction, with the "
        "configured tie-breakers applied afterwards. No score is computed and no "
        "value is transformed."
    ),
    version="1.0.0",
    implementation_id="app.domain.query.ranking:field_order",
    supported_component_kinds=(
        RankingComponentKind.NUMERIC_ASCENDING,
        RankingComponentKind.NUMERIC_DESCENDING,
    ),
    min_components=1,
    max_components=1,
)


@dataclass(frozen=True, slots=True)
class RankingMethodRegistry:
    version: str
    methods: tuple[RankingMethodDefinition, ...]

    def get(self, method_id: str) -> RankingMethodDefinition | None:
        for method in self.methods:
            if method.id == method_id:
                return method
        return None

    def available_methods(self) -> tuple[RankingMethodDefinition, ...]:
        return tuple(method for method in self.methods if method.available)


RANKING_METHOD_REGISTRY = RankingMethodRegistry(
    version="1.0.0", methods=(WEIGHTED_FIELD_SCORE, FIELD_ORDER)
)


@dataclass(frozen=True, slots=True)
class ValidatedRanking:
    """A ranking configuration the platform is willing to execute."""

    spec: RankingConfigurationSpec
    method: RankingMethodDefinition
    canonical: dict[str, Any]
    canonical_hash: str
    field_dictionary_version: str
    field_ids: tuple[str, ...]


def validate_ranking(
    spec: RankingConfigurationSpec,
    *,
    methods: RankingMethodRegistry | None = None,
    registry: FilterFieldRegistry,
    available_field_ids: frozenset[str] | None = None,
) -> ValidatedRanking:
    """Validate a ranking configuration against both registries."""
    methods = methods or RANKING_METHOD_REGISTRY
    issues: list[dict[str, Any]] = []
    method = methods.get(spec.method_id)
    if method is None or not method.available:
        raise ValidationError(
            "unknown ranking method",
            details={"issues": [{"code": "unknown_method", "method_id": spec.method_id}]},
        )
    if spec.method_version != method.version:
        # A configuration written for another version of the method is not
        # silently run against this one: the score would not be comparable.
        issues.append(
            {
                "code": "method_version_mismatch",
                "requested": spec.method_version,
                "registered": method.version,
            }
        )
    if method.requires_components and len(spec.components) < method.min_components:
        issues.append(
            {
                "code": "too_few_components",
                "supplied": len(spec.components),
                "min_components": method.min_components,
            }
        )
    if len(spec.components) > method.max_components:
        issues.append(
            {
                "code": "too_many_components",
                "supplied": len(spec.components),
                "max_components": method.max_components,
            }
        )
    unsupported = sorted(set(spec.parameters) - set(method.supported_parameters))
    if unsupported:
        issues.append({"code": "unsupported_parameters", "parameters": unsupported})

    seen: set[str] = set()
    definitions: list[FilterFieldDefinition] = []
    for index, component in enumerate(spec.components):
        path = f"components[{index}]"
        definition = registry.get(component.field_id)
        if definition is None:
            issues.append(
                {"code": "unknown_field", "path": path, "field_id": component.field_id}
            )
            continue
        if not definition.available:
            issues.append(
                {"code": "field_unavailable", "path": path, "field_id": definition.id}
            )
            continue
        if available_field_ids is not None and definition.id not in available_field_ids:
            issues.append(
                {"code": "field_not_in_context", "path": path, "field_id": definition.id}
            )
            continue
        if component.kind not in method.supported_component_kinds:
            issues.append(
                {
                    "code": "unsupported_component_kind",
                    "path": path,
                    "kind": component.kind.value,
                }
            )
            continue
        if definition.id in seen:
            issues.append({"code": "duplicate_component", "path": path, "field_id": definition.id})
            continue
        seen.add(definition.id)
        if not 0.0 <= component.weight <= 1.0:
            issues.append({"code": "weight_out_of_range", "path": path})
        if component.kind in (
            RankingComponentKind.NUMERIC_ASCENDING,
            RankingComponentKind.NUMERIC_DESCENDING,
        ):
            if definition.data_type not in NUMERIC_DATA_TYPES:
                issues.append(
                    {"code": "component_requires_numeric_field", "path": path}
                )
            if component.scale_min is None or component.scale_max is None:
                issues.append({"code": "scale_required", "path": path})
            elif component.scale_min >= component.scale_max:
                issues.append({"code": "invalid_scale", "path": path})
        if component.kind is RankingComponentKind.CATEGORY_PRIORITY:
            if definition.data_type not in (
                FilterDataType.CATEGORICAL,
                FilterDataType.STRING,
                FilterDataType.IDENTIFIER,
            ):
                issues.append(
                    {"code": "component_requires_categorical_field", "path": path}
                )
            if len(component.category_priority) < 2:
                # An ordered list of one term states no order at all, and an
                # empty one would make the platform invent the ordering.
                issues.append({"code": "category_priority_required", "path": path})
            if len(set(component.category_priority)) != len(component.category_priority):
                issues.append({"code": "duplicate_category_term", "path": path})
        if component.missing_behaviour is RankingMissingBehaviour.FLOOR and not (
            0.0 <= component.missing_floor <= 1.0
        ):
            issues.append({"code": "missing_floor_out_of_range", "path": path})
        definitions.append(definition)

    for tie_breaker in spec.tie_breakers:
        if registry.get(tie_breaker) is None:
            issues.append({"code": "unknown_tie_breaker", "field_id": tie_breaker})
    if not spec.tie_breakers:
        issues.append({"code": "tie_breaker_required"})

    if issues:
        raise ValidationError(
            "ranking configuration is not valid", details={"issues": issues}
        )

    payload = spec.to_payload()
    return ValidatedRanking(
        spec=spec,
        method=method,
        canonical=payload,
        canonical_hash=_canonical_hash_of(payload),
        field_dictionary_version=registry.version,
        field_ids=tuple(sorted(definition.id for definition in definitions)),
    )


def _canonical_hash_of(payload: Mapping[str, Any]) -> str:
    import hashlib
    import json

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ComponentScore:
    field_id: str
    kind: RankingComponentKind
    weight: float
    #: Normalized 0..1 contribution before weighting, or ``None`` when missing.
    component_value: float | None
    contribution: float
    missing: bool
    semantics: ValueSemantics | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "kind": self.kind.value,
            "weight": self.weight,
            "component_value": self.component_value,
            "contribution": self.contribution,
            "missing": self.missing,
            "semantics": self.semantics.value if self.semantics else None,
        }


@dataclass(frozen=True, slots=True)
class RowScore:
    """The score for one row, with every contribution shown."""

    #: ``None`` when no component had a reported value: an unscored row is
    #: unscored, not a zero.
    score: float | None
    components: tuple[ComponentScore, ...]
    present_weight: float
    missing_field_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "present_weight": self.present_weight,
            "missing_field_ids": list(self.missing_field_ids),
            "components": [component.as_dict() for component in self.components],
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _semantics_of(row: Mapping[str, Any], definition: FilterFieldDefinition) -> ValueSemantics | None:
    if definition.semantics_column is None:
        return None
    raw = row.get(definition.semantics_column)
    if raw is None:
        return None
    try:
        return ValueSemantics(str(raw))
    except ValueError:
        return None


def _component_value(
    component: RankingComponent,
    definition: FilterFieldDefinition,
    row: Mapping[str, Any],
) -> tuple[float | None, ValueSemantics | None]:
    semantics = _semantics_of(row, definition)
    raw = row.get(definition.column)
    reported = raw is not None and (
        semantics is None or semantics is ValueSemantics.PRESENT
    )
    if component.kind is RankingComponentKind.PRESENCE:
        return (1.0 if reported else 0.0), semantics
    if not reported:
        return None, semantics
    if component.kind is RankingComponentKind.CATEGORY_PRIORITY:
        term = str(raw)
        if term not in component.category_priority:
            # A term the author did not rank is not guessed at; it is missing
            # from this component.
            return None, semantics
        index = component.category_priority.index(term)
        span = len(component.category_priority) - 1
        return (1.0 if span == 0 else (span - index) / span), semantics
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None, semantics
    minimum = component.scale_min
    maximum = component.scale_max
    if minimum is None or maximum is None or maximum <= minimum:
        return None, semantics
    normalized = (number - minimum) / (maximum - minimum)
    if component.kind is RankingComponentKind.NUMERIC_ASCENDING:
        return _clamp(1.0 - normalized), semantics
    return _clamp(normalized), semantics


def prioritize_row(
    spec: RankingConfigurationSpec,
    row: Mapping[str, Any],
    *,
    registry: FilterFieldRegistry,
) -> RowScore:
    """Compute the prioritization score for one row, deterministically."""
    components: list[ComponentScore] = []
    missing: list[str] = []
    total = 0.0
    present_weight = 0.0
    for component in spec.components:
        definition = registry.get(component.field_id)
        if definition is None:
            missing.append(component.field_id)
            continue
        value, semantics = _component_value(component, definition, row)
        if value is None:
            if component.missing_behaviour is RankingMissingBehaviour.FLOOR:
                value = component.missing_floor
                contribution = component.weight * value
                total += contribution
                present_weight += component.weight
                components.append(
                    ComponentScore(
                        field_id=component.field_id,
                        kind=component.kind,
                        weight=component.weight,
                        component_value=value,
                        contribution=contribution,
                        missing=True,
                        semantics=semantics,
                    )
                )
                missing.append(component.field_id)
                continue
            components.append(
                ComponentScore(
                    field_id=component.field_id,
                    kind=component.kind,
                    weight=component.weight,
                    component_value=None,
                    contribution=0.0,
                    missing=True,
                    semantics=semantics,
                )
            )
            missing.append(component.field_id)
            continue
        contribution = component.weight * value
        total += contribution
        present_weight += component.weight
        components.append(
            ComponentScore(
                field_id=component.field_id,
                kind=component.kind,
                weight=component.weight,
                component_value=value,
                contribution=contribution,
                missing=False,
                semantics=semantics,
            )
        )

    if present_weight <= 0.0:
        return RowScore(
            score=None,
            components=tuple(components),
            present_weight=0.0,
            missing_field_ids=tuple(missing),
        )
    score = total
    if bool(spec.parameters.get("normalize_by_present_weight")):
        # Opt-in, because renormalizing over the reported components changes what
        # the number means when data is incomplete. Off by default.
        score = total / present_weight
    return RowScore(
        score=round(score, 12),
        components=tuple(components),
        present_weight=present_weight,
        missing_field_ids=tuple(missing),
    )


def ranking_sort_key(
    scored: RowScore, row: Mapping[str, Any], spec: RankingConfigurationSpec, *,
    registry: FilterFieldRegistry,
) -> tuple[Any, ...]:
    """Deterministic sort key: score first, declared tie-breakers afterwards.

    Unscored rows sort last in both directions — an absent score is not a low
    score — and the tie-breakers guarantee a total order.
    """
    descending = spec.direction is RankingDirection.DESCENDING
    has_score = scored.score is not None
    primary = 0.0 if scored.score is None else scored.score
    ordered_primary = -primary if descending else primary
    tail: list[Any] = []
    for field_id in spec.tie_breakers:
        definition = registry.get(field_id)
        raw = row.get(definition.column) if definition else None
        if raw is None:
            tail.extend([1, ""])
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            tail.extend([0, f"{float(raw):020.6f}"])
        else:
            tail.extend([0, str(raw)])
    return (0 if has_score else 1, ordered_primary, *tail)


def canonical_ranking_hash(payload: Mapping[str, Any]) -> str:
    return _canonical_hash_of(payload)


__all__ = [
    "FIELD_ORDER",
    "RANKING_METHOD_REGISTRY",
    "WEIGHTED_FIELD_SCORE",
    "ComponentScore",
    "RankingComponent",
    "RankingComponentKind",
    "RankingConfigurationSpec",
    "RankingDirection",
    "RankingMethodDefinition",
    "RankingMethodRegistry",
    "RankingMissingBehaviour",
    "RowScore",
    "ValidatedRanking",
    "canonical_ranking_hash",
    "prioritize_row",
    "ranking_sort_key",
    "validate_ranking",
]
