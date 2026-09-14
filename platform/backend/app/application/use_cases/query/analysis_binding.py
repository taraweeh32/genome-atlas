"""Binding filter and ranking configurations into an analysis run.

Two separate moments, deliberately:

* **Configuration time** — the ``filtering`` and ``ranking`` sections of an
  analysis configuration version are validated *structurally*: only known keys,
  an inline expression must parse and validate, an inline ranking must name a
  registered method and supported components. Nothing is repaired.
* **Execution time** — the referenced saved filter, preset, saved ranking and
  ranking preset are resolved to *exact version numbers*, their canonical
  content is copied into the execution snapshot, and those versions are marked
  referenced so they can never be rewritten. A later edit publishes a new
  version; it cannot change what this run used.

The snapshot records the field dictionary version as well, because the meaning
of a field identifier belongs to a dictionary version, not to the code that
happens to be deployed when someone reads the run back.
"""

from __future__ import annotations

from typing import Any

from app.domain.errors import NotFoundError, ValidationError
from app.domain.query.expressions import group_from_payload
from app.domain.query.fields import (
    DEFAULT_FIELD_REGISTRY,
    FIELD_DICTIONARY_VERSION,
    FilterFieldRegistry,
)
from app.domain.query.ranking import (
    RANKING_METHOD_REGISTRY,
    RankingMethodRegistry,
    spec_from_payload,
    validate_ranking,
)
from app.domain.query.validation import FilterLimits, validate_filter

#: The one key inside an analysis configuration's ``filtering`` section that this
#: package owns. Everything else in that section is scientific engine parameters
#: and stays opaque here — reading it would be this package overstepping.
FILTER_BINDING_KEY = "variant_filter"
#: The same, inside the ``ranking`` section.
RANKING_BINDING_KEY = "variant_ranking"

#: Keys the filter binding may carry. A filter is either inline, or a reference
#: to a saved filter and/or a preset — never raw SQL and never anything executable.
FILTER_SECTION_KEYS = frozenset(
    {
        "expression",
        "filter_definition_id",
        "filter_version_number",
        "filter_preset_id",
        "filter_preset_version_number",
    }
)
#: Keys the ranking binding may carry.
RANKING_SECTION_KEYS = frozenset(
    {
        "configuration",
        "ranking_definition_id",
        "ranking_version_number",
        "ranking_preset_id",
        "ranking_preset_version_number",
    }
)


def _reject_unknown(section: dict[str, Any], allowed: frozenset[str], *, name: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValidationError(
            f"the {name} configuration contains unknown keys",
            details={"field": name, "unknown_keys": unknown},
        )


def validate_query_sections(
    filtering: dict[str, Any] | None,
    ranking: dict[str, Any] | None,
    *,
    registry: FilterFieldRegistry = DEFAULT_FIELD_REGISTRY,
    methods: RankingMethodRegistry = RANKING_METHOD_REGISTRY,
    limits: FilterLimits | None = None,
) -> None:
    """Structural validation of a configuration's filtering and ranking sections.

    Field *availability* is not checked here: which fields a surface carries is
    only known when a surface exists. Availability is enforced at query time.
    """
    filtering = (filtering or {}).get(FILTER_BINDING_KEY) or {}
    ranking = (ranking or {}).get(RANKING_BINDING_KEY) or {}
    if filtering:
        if not isinstance(filtering, dict):
            raise ValidationError(
                "the variant filter binding must be an object",
                details={"field": f"filtering.{FILTER_BINDING_KEY}"},
            )
        _reject_unknown(filtering, FILTER_SECTION_KEYS, name="filtering")
        expression = filtering.get("expression")
        if expression is not None:
            if not isinstance(expression, dict):
                raise ValidationError(
                    "the filtering expression must be a logical group",
                    details={"field": "filtering.expression"},
                )
            validate_filter(
                group_from_payload(expression),
                registry=registry,
                limits=limits or FilterLimits(),
                allow_empty=False,
            )
        if (
            filtering.get("filter_version_number") is not None
            and filtering.get("filter_definition_id") is None
        ):
            raise ValidationError(
                "a filter version number requires a saved filter reference",
                details={"field": "filtering.filter_definition_id"},
            )
        if (
            filtering.get("filter_preset_version_number") is not None
            and filtering.get("filter_preset_id") is None
        ):
            raise ValidationError(
                "a preset version number requires a preset reference",
                details={"field": "filtering.filter_preset_id"},
            )

    if ranking:
        if not isinstance(ranking, dict):
            raise ValidationError(
                "the variant ranking binding must be an object",
                details={"field": f"ranking.{RANKING_BINDING_KEY}"},
            )
        _reject_unknown(ranking, RANKING_SECTION_KEYS, name="ranking")
        named = [
            value
            for value in (
                ranking.get("configuration"),
                ranking.get("ranking_definition_id"),
                ranking.get("ranking_preset_id"),
            )
            if value is not None
        ]
        if len(named) > 1:
            raise ValidationError(
                "an analysis applies exactly one ranking configuration",
                details={"field": "ranking", "supplied": len(named)},
            )
        configuration = ranking.get("configuration")
        if configuration is not None:
            if not isinstance(configuration, dict):
                raise ValidationError(
                    "the ranking configuration must be an object",
                    details={"field": "ranking.configuration"},
                )
            validate_ranking(
                spec_from_payload(configuration),
                methods=methods,
                registry=registry,
                available_field_ids=None,
            )


async def _pin(
    repository: Any,
    *,
    kind: str,
    definition_id: str,
    version_number: int | None,
) -> dict[str, Any]:
    """Resolve one definition to an exact version and mark that version referenced."""
    definition = await repository.get(definition_id)
    if definition is None:
        raise NotFoundError(kind, definition_id)
    if version_number is None:
        version = await repository.latest_version(definition_id)
    else:
        version = await repository.find_version(
            definition_id=definition_id, version_number=version_number
        )
    if version is None:
        raise NotFoundError(f"{kind}_version", definition_id)
    # Referenced content becomes immutable: an edit from here on appends a new
    # version instead of rewriting this one.
    await repository.mark_version_referenced(version.id)
    return {
        "definition_id": definition.id,
        "name": definition.name,
        "scope": definition.scope.value,
        "version_id": version.id,
        "version_number": version.version_number,
        "canonical": version.canonical,
        "canonical_hash": version.canonical_hash,
    }


async def freeze_query_sections(
    repositories: Any,
    snapshot: dict[str, Any],
    *,
    software_version: str,
) -> dict[str, Any]:
    """Return ``snapshot`` with its filtering and ranking sections frozen.

    Called once, when an execution is requested. The result is stored verbatim on
    the execution record, so reading a historical run never re-resolves anything.
    """
    filtering_section = dict(snapshot.get("filtering") or {})
    ranking_section = dict(snapshot.get("ranking") or {})
    validate_query_sections(filtering_section, ranking_section)
    filtering = dict(filtering_section.get(FILTER_BINDING_KEY) or {})
    ranking = dict(ranking_section.get(RANKING_BINDING_KEY) or {})

    frozen_filter: dict[str, Any] = {}
    if filtering:
        if filtering.get("expression") is not None:
            validated = validate_filter(
                group_from_payload(filtering["expression"]),
                registry=DEFAULT_FIELD_REGISTRY,
                allow_empty=False,
            )
            frozen_filter["custom"] = {
                "canonical": validated.canonical,
                "canonical_hash": validated.canonical_hash,
            }
        if filtering.get("filter_definition_id"):
            frozen_filter["saved_filter"] = await _pin(
                repositories.filter_definitions,
                kind="filter_definition",
                definition_id=filtering["filter_definition_id"],
                version_number=filtering.get("filter_version_number"),
            )
        if filtering.get("filter_preset_id"):
            frozen_filter["preset"] = await _pin(
                repositories.filter_presets,
                kind="filter_preset",
                definition_id=filtering["filter_preset_id"],
                version_number=filtering.get("filter_preset_version_number"),
            )

    frozen_ranking: dict[str, Any] = {}
    if ranking:
        if ranking.get("configuration") is not None:
            validated_ranking = validate_ranking(
                spec_from_payload(ranking["configuration"]),
                registry=DEFAULT_FIELD_REGISTRY,
                available_field_ids=None,
            )
            frozen_ranking["custom"] = {
                "canonical": validated_ranking.canonical,
                "canonical_hash": validated_ranking.canonical_hash,
            }
        if ranking.get("ranking_definition_id"):
            frozen_ranking["saved_ranking"] = await _pin(
                repositories.ranking_definitions,
                kind="ranking_definition",
                definition_id=ranking["ranking_definition_id"],
                version_number=ranking.get("ranking_version_number"),
            )
        if ranking.get("ranking_preset_id"):
            frozen_ranking["preset"] = await _pin(
                repositories.ranking_presets,
                kind="ranking_preset",
                definition_id=ranking["ranking_preset_id"],
                version_number=ranking.get("ranking_preset_version_number"),
            )

    frozen = dict(snapshot)
    # The requested sections stay exactly as requested; the resolution is recorded
    # beside them, so both "what was asked for" and "what was used" stay readable.
    frozen["query_binding"] = {
        "filter": frozen_filter,
        "ranking": frozen_ranking,
        "field_dictionary_version": FIELD_DICTIONARY_VERSION,
        "software_version": software_version,
    }
    return frozen


__all__ = [
    "FILTER_BINDING_KEY",
    "FILTER_SECTION_KEYS",
    "RANKING_BINDING_KEY",
    "RANKING_SECTION_KEYS",
    "freeze_query_sections",
    "validate_query_sections",
]
