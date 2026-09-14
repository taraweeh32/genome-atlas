"""Executing a variant query: filter, then rank, then page — in that order.

The pipeline is fixed and each stage is independent of the next:

``resolve surface → resolve filter sources → validate → compile → execute
bounded page → validate ranking → score → deterministic order → record``

Properties the implementation is responsible for:

* **Filtering never depends on ranking.** The predicate is compiled and pushed
  down before any score exists. A ranking cannot return a variant the filter
  excluded, because ranking only ever reorders rows already fetched.
* **A preset stays identifiable.** When a caller applies a preset and adds their
  own conditions, three expressions are recorded: the preset's exact version, the
  caller's own conditions, and the effective combination. Editing the preset
  tomorrow cannot change what this execution meant.
* **Nothing is fabricated.** A total is recorded only when it was computed;
  otherwise it is absent, never zero. A row whose ranking fields were never
  reported is unscored, never scored zero.
* **Pages are bounded and deterministic.** Unranked pages use keyset
  continuation over the declared ordering. Ranked pages are scored over a bounded
  window (a weighted score is not expressible as an index-friendly predicate);
  when the filtered set exceeds that window the response says so, and the caller
  is directed to the durable job path rather than being handed a silently partial
  ranking.

Reproducibility is recorded, not promised: every execution writes a filter
execution record and, when ranked, a ranking execution record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.ports import AnalyticalQuerySpec
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.query.dependencies import (
    FILTER_PRESET,
    QUERY_EXECUTE,
    RANKING_PRESET,
    SAVED_FILTER,
    SAVED_RANKING,
    QueryServices,
    require_configuration_access,
    resolve_workspace_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.query.canonical import canonical_payload
from app.domain.query.entities import FilterExecutionRecord, RankingExecutionRecord
from app.domain.query.expressions import FilterGroup, group_from_payload
from app.domain.query.pagination import PageCursor, decode_cursor, query_fingerprint
from app.domain.query.ranking import (
    RankingConfigurationSpec,
    prioritize_row,
    ranking_sort_key,
    spec_from_payload,
    validate_ranking,
)
from app.domain.query.validation import combine_expressions, validate_filter
from app.domain.value_objects.enums import AuditOutcome, QueryExecutionOutcome
from app.infrastructure.persistence.repositories.base import new_id

#: Rows scored for a ranked page. A weighted prioritization score cannot be pushed
#: into the scan, so a ranked request scores a bounded window rather than a whole
#: surface. Exceeding it is reported, never hidden.
RANKING_WINDOW_ROWS = 1000

#: Ordering used when the caller requests none. Chosen because it is the physical
#: identity of a variant and therefore always present and always total.
DEFAULT_ORDER_FIELD_IDS = ("contig", "position", "reference_allele", "alternate_allele")


@dataclass(frozen=True, slots=True)
class FilterSelection:
    """What the caller wants filtered, expressed as sources rather than SQL."""

    #: Ad-hoc conditions written in the builder.
    expression: dict[str, Any] | None = None
    #: A saved filter to apply. Resolved to its latest version unless a version
    #: number is named, which is how an analysis re-runs exactly what it ran.
    filter_definition_id: str | None = None
    filter_version_number: int | None = None
    #: A preset to apply, optionally combined with ``expression``.
    filter_preset_id: str | None = None
    filter_preset_version_number: int | None = None


@dataclass(frozen=True, slots=True)
class RankingSelection:
    configuration: dict[str, Any] | None = None
    ranking_definition_id: str | None = None
    ranking_version_number: int | None = None
    ranking_preset_id: str | None = None
    ranking_preset_version_number: int | None = None


@dataclass(frozen=True, slots=True)
class VariantQueryCommand:
    actor: ActorContext
    request: RequestContext
    result_set_id: str
    filter: FilterSelection = FilterSelection()
    ranking: RankingSelection = RankingSelection()
    #: Field identifiers to return. Empty means the surface's advertised fields.
    field_ids: tuple[str, ...] = ()
    page_size: int = 50
    cursor: str | None = None
    #: Table sort, applied only when no ranking is active. Sorting is presentation;
    #: ranking is prioritization. They are never mixed.
    sort_field_id: str | None = None
    sort_descending: bool = False
    #: Totals cost a second scan, so they are opt-in.
    include_total: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """One resolved definition/version pair, or nothing."""

    definition_id: str | None = None
    version_id: str | None = None
    version_number: int | None = None
    canonical: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class VariantQueryPage:
    result_set_id: str
    columns: tuple[str, ...]
    field_ids: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    returned_count: int
    total_count: int | None
    next_cursor: str | None
    #: Everything needed to explain and reproduce this page.
    execution: FilterExecutionRecord
    ranking_execution: RankingExecutionRecord | None
    #: True when a ranked request could not score the whole filtered set.
    ranking_window_exceeded: bool = False
    ranking_window_rows: int | None = None


class ExecuteVariantQuery:
    """The single server-side entry point for reading filtered variant rows."""

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(self, command: VariantQueryCommand) -> VariantQueryPage:
        services = self._services
        if services.query_engine is None:
            raise ConflictError("analytical querying is not available")
        now = services.clock.now()
        page_size = self._page_size(command.page_size)
        # Ambiguity is refused before anything is resolved: a request naming two
        # ranking sources is malformed, not a lookup of either one.
        self._assert_single_ranking_source(command.ranking)


        async with services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            result_set = await repositories.result_sets.get(command.result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", command.result_set_id)
            await resolve_workspace_scope(
                services,
                repositories,
                command.actor,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                action=QUERY_EXECUTE,
                recorder=recorder,
                occurred_at=now,
            )
            if not result_set.is_readable or result_set.analytical_location is None:
                raise ConflictError(
                    "this result surface has no readable content",
                    details={"state": result_set.state.value},
                )
            saved_filter = await self._resolve_filter_definition(
                repositories, command, recorder=recorder, at=now
            )
            preset = await self._resolve_filter_preset(
                repositories, command, recorder=recorder, at=now
            )
            ranking_definition = await self._resolve_ranking_definition(
                repositories, command, recorder=recorder, at=now
            )
            ranking_preset = await self._resolve_ranking_preset(
                repositories, command, recorder=recorder, at=now
            )

        location = result_set.analytical_location
        description = await services.query_engine.describe(location)
        columns_present = frozenset(column.name for column in description.columns)
        available = services.fields.available_for_columns(columns_present)
        available_ids = frozenset(definition.id for definition in available)

        # -- filtering ------------------------------------------------------- #
        custom = self._custom_expression(command.filter)
        parts: list[FilterGroup] = []
        for source in (saved_filter, preset):
            if source.canonical is not None:
                parts.append(group_from_payload(source.canonical))
        if custom is not None:
            parts.append(custom)
        # An empty combination is a real, distinct case: "no filter" is not the
        # same request as "a filter that matched everything".
        effective_expression = combine_expressions(*parts)
        validated = validate_filter(
            effective_expression,
            registry=services.fields,
            limits=services.limits,
            available_field_ids=available_ids,
            allow_empty=True,
        )

        predicate = None
        if effective_expression is not None and validated.condition_count:
            from app.infrastructure.analytics.filter_compiler import compile_filter

            predicate = compile_filter(validated.expression, services.fields)

        # -- ranking --------------------------------------------------------- #
        ranking_spec: RankingConfigurationSpec | None = None
        ranking_validated = None
        ranking_source = ResolvedSource()
        ranking_payload = self._ranking_payload(
            command.ranking, ranking_definition, ranking_preset
        )
        if ranking_payload is not None:
            ranking_spec = spec_from_payload(ranking_payload)
            ranking_validated = validate_ranking(
                ranking_spec,
                methods=services.methods,
                registry=services.fields,
                available_field_ids=available_ids,
            )
            ranking_source = (
                ranking_definition
                if ranking_definition.definition_id
                else ranking_preset
            )

        selected_ids, selected_columns = self._projection(
            command.field_ids, available, validated, ranking_spec
        )
        order_by = self._order_by(command, available_ids, ranked=ranking_spec is not None)

        fingerprint = query_fingerprint(
            location=location,
            effective_hash=validated.canonical_hash,
            order_by=order_by,
            ranking_hash=ranking_validated.canonical_hash if ranking_validated else None,
        )
        cursor = (
            decode_cursor(command.cursor, expected_fingerprint=fingerprint)
            if command.cursor
            else None
        )


        # -- execution ------------------------------------------------------- #
        if ranking_spec is None:
            outcome = await self._unranked_page(
                location,
                selected_columns,
                predicate=predicate,
                order_by=order_by,
                cursor=cursor,
                page_size=page_size,
                include_total=command.include_total,
                fingerprint=fingerprint,
            )
        else:
            outcome = await self._ranked_page(
                location,
                selected_columns,
                predicate=predicate,
                order_by=order_by,
                cursor=cursor,
                page_size=page_size,
                include_total=command.include_total,
                fingerprint=fingerprint,
                spec=ranking_spec,
            )

        rows = tuple(
            {
                definition.id: row.get(definition.column)
                for definition in available
                if definition.id in selected_ids
            }
            | (
                {"_prioritization_score": row["_prioritization_score"]}
                if "_prioritization_score" in row
                else {}
            )
            for row in outcome.rows
        )

        # -- recording ------------------------------------------------------- #
        async with services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            execution = FilterExecutionRecord(
                id=new_id("fex"),
                workspace_id=result_set.workspace_id,
                executed_by=command.actor.actor_id,
                executed_at=now,
                result_set_id=result_set.id,
                effective_canonical=validated.canonical,
                effective_hash=validated.canonical_hash,
                field_dictionary_version=validated.field_dictionary_version,
                outcome=QueryExecutionOutcome.COMPLETED,
                project_id=result_set.project_id,
                dataset_version_id=getattr(result_set, "dataset_version_id", None),
                filter_definition_id=saved_filter.definition_id,
                filter_version_id=saved_filter.version_id,
                filter_version_number=saved_filter.version_number,
                filter_preset_id=preset.definition_id,
                filter_preset_version_id=preset.version_id,
                filter_preset_version_number=preset.version_number,
                custom_canonical=canonical_payload(custom) if custom else None,
                returned_count=len(rows),
                total_count=outcome.total,
                page_size=page_size,
                cursor=command.cursor,
                next_cursor=outcome.next_cursor,
                duration_ms=outcome.duration_ms,
                software_version=services.software_version,
                correlation_id=command.request.correlation_id,
                metadata={
                    "ranking_window_exceeded": outcome.window_exceeded,
                    "field_ids": list(selected_ids),
                },
            )
            await repositories.query_executions.add_filter_execution(execution)
            ranking_execution: RankingExecutionRecord | None = None
            if ranking_validated is not None and ranking_spec is not None:
                ranking_execution = RankingExecutionRecord(
                    id=new_id("rex"),
                    filter_execution_id=execution.id,
                    workspace_id=result_set.workspace_id,
                    executed_by=command.actor.actor_id,
                    executed_at=now,
                    method_id=ranking_validated.method.id,
                    method_version=ranking_validated.method.version,
                    method_implementation_id=ranking_validated.method.implementation_id,
                    effective_canonical=ranking_validated.canonical,
                    effective_hash=ranking_validated.canonical_hash,
                    field_dictionary_version=ranking_validated.field_dictionary_version,
                    direction=ranking_spec.direction.value,
                    tie_breakers=ranking_spec.tie_breakers,
                    project_id=result_set.project_id,
                    ranking_definition_id=(
                        ranking_source.definition_id
                        if ranking_definition.definition_id
                        else None
                    ),
                    ranking_version_id=(
                        ranking_definition.version_id
                        if ranking_definition.definition_id
                        else None
                    ),
                    ranking_version_number=(
                        ranking_definition.version_number
                        if ranking_definition.definition_id
                        else None
                    ),
                    ranking_preset_id=ranking_preset.definition_id,
                    ranking_preset_version_id=ranking_preset.version_id,
                    ranking_preset_version_number=ranking_preset.version_number,
                    scored_count=outcome.scored_count,
                    unscored_count=outcome.unscored_count,
                    duration_ms=outcome.duration_ms,
                    software_version=services.software_version,
                    correlation_id=command.request.correlation_id,
                    metadata={"window_rows": outcome.window_rows},
                )
                await repositories.query_executions.add_ranking_execution(
                    ranking_execution
                )
            await recorder.audit(
                action="variant_query.executed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="result_set",
                resource_id=result_set.id,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                detail={
                    "filter_execution_id": execution.id,
                    "effective_hash": validated.canonical_hash,
                    "returned_count": len(rows),
                    "ranked": ranking_execution is not None,
                },
            )

        return VariantQueryPage(
            result_set_id=result_set.id,
            columns=tuple(selected_columns),
            field_ids=tuple(selected_ids),
            rows=rows,
            returned_count=len(rows),
            total_count=outcome.total,
            next_cursor=outcome.next_cursor,
            execution=execution,
            ranking_execution=ranking_execution,
            ranking_window_exceeded=outcome.window_exceeded,
            ranking_window_rows=outcome.window_rows,
        )

    # -- shared resolution, also used by the deferred (job) path ------------ #

    async def resolve_sources(
        self,
        repositories,
        command: VariantQueryCommand,
        *,
        recorder: ActivityRecorder,
        at: datetime,
    ) -> tuple[ResolvedSource, ResolvedSource, ResolvedSource, ResolvedSource]:
        """Resolve saved filter, preset and ranking sources for a command.

        Public because the deferred (durable job) path must resolve exactly the
        same sources under exactly the same authorization: there is one
        resolution rule for a query, not one per transport.
        """
        return (
            await self._resolve_filter_definition(
                repositories, command, recorder=recorder, at=at
            ),
            await self._resolve_filter_preset(
                repositories, command, recorder=recorder, at=at
            ),
            await self._resolve_ranking_definition(
                repositories, command, recorder=recorder, at=at
            ),
            await self._resolve_ranking_preset(
                repositories, command, recorder=recorder, at=at
            ),
        )

    def projection_for(
        self,
        requested: tuple[str, ...],
        available: tuple[Any, ...],
        validated: Any,
        ranking: RankingConfigurationSpec | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return self._projection(requested, available, validated, ranking)

    def ordering_for(
        self,
        command: VariantQueryCommand,
        available_ids: frozenset[str],
        *,
        ranked: bool,
    ) -> tuple[tuple[str, bool], ...]:
        return self._order_by(command, available_ids, ranked=ranked)

    @staticmethod
    def assert_single_ranking_source(selection: RankingSelection) -> None:
        ExecuteVariantQuery._assert_single_ranking_source(selection)

    def custom_expression_of(self, selection: FilterSelection) -> FilterGroup | None:
        return self._custom_expression(selection)

    # -- pipeline stages ---------------------------------------------------- #

    def _page_size(self, requested: int) -> int:
        size = int(requested)
        if size < 1:
            raise ValidationError("a page must contain at least one row")
        if size > self._services.max_page_size:
            # Refused rather than silently reduced: a caller that asked for 50 000
            # rows needs the export path, not a quietly different answer.
            raise ValidationError(
                "the requested page size exceeds the configured maximum",
                details={"maximum": self._services.max_page_size, "requested": size},
            )
        return size

    def _custom_expression(self, selection: FilterSelection) -> FilterGroup | None:
        if selection.expression is None:
            return None
        return group_from_payload(selection.expression)

    def _projection(
        self,
        requested: tuple[str, ...],
        available: tuple[Any, ...],
        validated: Any,
        ranking: RankingConfigurationSpec | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        by_id = {definition.id: definition for definition in available}
        wanted = list(requested) if requested else list(by_id)
        for field_id in validated.field_ids:
            if field_id not in wanted and field_id in by_id:
                wanted.append(field_id)
        if ranking is not None:
            for component in ranking.components:
                if component.field_id not in wanted and component.field_id in by_id:
                    wanted.append(component.field_id)
            for field_id in ranking.tie_breakers:
                if field_id not in wanted and field_id in by_id:
                    wanted.append(field_id)
        for field_id in DEFAULT_ORDER_FIELD_IDS:
            if field_id not in wanted and field_id in by_id:
                wanted.append(field_id)
        unknown = [field_id for field_id in wanted if field_id not in by_id]
        if unknown:
            raise ValidationError(
                "the requested fields are not available on this surface",
                details={"field_ids": unknown},
            )
        return tuple(wanted), tuple(by_id[field_id].column for field_id in wanted)

    def _order_by(
        self,
        command: VariantQueryCommand,
        available_ids: frozenset[str],
        *,
        ranked: bool,
    ) -> tuple[tuple[str, bool], ...]:
        """The physical ordering, which is always total and never engine-dependent."""
        registry = self._services.fields
        columns: list[tuple[str, bool]] = []
        if command.sort_field_id and not ranked:
            definition = registry.get(command.sort_field_id)
            if definition is None or definition.id not in available_ids:
                raise ValidationError(
                    "the requested sort field is not available on this surface",
                    details={"field_id": command.sort_field_id},
                )
            if not definition.sortable:
                raise ValidationError(
                    "this field cannot be sorted",
                    details={"field_id": definition.id},
                )
            columns.append((definition.column, command.sort_descending))
        for field_id in DEFAULT_ORDER_FIELD_IDS:
            definition = registry.get(field_id)
            if definition is None or definition.id not in available_ids:
                continue
            if any(column == definition.column for column, _ in columns):
                continue
            columns.append((definition.column, False))
        if not columns:
            raise ConflictError(
                "this surface carries no column that can order a page deterministically"
            )
        return tuple(columns)

    async def _unranked_page(
        self,
        location: str,
        columns: tuple[str, ...],
        *,
        predicate: Any,
        order_by: tuple[tuple[str, bool], ...],
        cursor: PageCursor | None,
        page_size: int,
        include_total: bool,
        fingerprint: str,
    ) -> _Outcome:
        from app.infrastructure.analytics.query_engine import keyset_predicate

        keyset = (
            keyset_predicate(order_by, cursor.values) if cursor is not None else None
        )
        result = await self._services.query_engine.execute(
            AnalyticalQuerySpec(
                location=location,
                columns=columns,
                limit=page_size,
                predicate=predicate,
                order_by=order_by,
                keyset=keyset,
                count_total=include_total,
            )
        )
        rows = tuple(dict(zip(result.columns, row, strict=True)) for row in result.rows)
        next_cursor = None
        if result.truncated and rows:
            next_cursor = PageCursor(
                query_fingerprint=fingerprint,
                values=tuple(rows[-1][column] for column, _ in order_by),
            ).encode()
        return _Outcome(
            rows=rows,
            total=result.total_rows,
            next_cursor=next_cursor,
            duration_ms=result.duration_ms,
        )

    async def _ranked_page(
        self,
        location: str,
        columns: tuple[str, ...],
        *,
        predicate: Any,
        order_by: tuple[tuple[str, bool], ...],
        cursor: PageCursor | None,
        page_size: int,
        include_total: bool,
        fingerprint: str,
        spec: RankingConfigurationSpec,
    ) -> _Outcome:
        """Score a bounded window, order it deterministically, return one page.

        The window exists because a weighted score is not a predicate: it cannot be
        pushed into the scan, so the rows to be ordered must be read. When the
        filtered set is larger than the window the caller is told, rather than shown
        a ranking of an arbitrary subset as if it were complete.
        """
        window = min(RANKING_WINDOW_ROWS, self._services.max_page_size * 10)
        offset = int(cursor.values[0]) if cursor is not None else 0
        result = await self._services.query_engine.execute(
            AnalyticalQuerySpec(
                location=location,
                columns=columns,
                limit=window,
                predicate=predicate,
                order_by=order_by,
                keyset=None,
                count_total=include_total,
            )
        )
        window_rows = tuple(
            dict(zip(result.columns, row, strict=True)) for row in result.rows
        )
        registry = self._services.fields
        scored = [
            (prioritize_row(spec, row, registry=registry), row) for row in window_rows
        ]
        scored.sort(key=lambda pair: ranking_sort_key(pair[0], pair[1], spec, registry=registry))
        page = scored[offset : offset + page_size]
        rows = tuple(
            row | {"_prioritization_score": score.score} for score, row in page
        )
        next_cursor = None
        if offset + page_size < len(scored):
            next_cursor = PageCursor(
                query_fingerprint=fingerprint, values=(offset + page_size,)
            ).encode()
        return _Outcome(
            rows=rows,
            total=result.total_rows,
            next_cursor=next_cursor,
            duration_ms=result.duration_ms,
            scored_count=sum(1 for score, _ in scored if score.score is not None),
            unscored_count=sum(1 for score, _ in scored if score.score is None),
            window_exceeded=result.truncated,
            window_rows=window,
        )

    # -- source resolution -------------------------------------------------- #

    async def _resolve_filter_definition(
        self, repositories: Any, command: VariantQueryCommand, *, recorder: Any, at: datetime
    ) -> ResolvedSource:
        selection = command.filter
        if selection.filter_definition_id is None:
            return ResolvedSource()
        return await self._resolve(
            repositories,
            command.actor,
            repository=repositories.filter_definitions,
            kind=SAVED_FILTER,
            definition_id=selection.filter_definition_id,
            version_number=selection.filter_version_number,
            recorder=recorder,
            at=at,
        )

    async def _resolve_filter_preset(
        self, repositories: Any, command: VariantQueryCommand, *, recorder: Any, at: datetime
    ) -> ResolvedSource:
        selection = command.filter
        if selection.filter_preset_id is None:
            return ResolvedSource()
        return await self._resolve(
            repositories,
            command.actor,
            repository=repositories.filter_presets,
            kind=FILTER_PRESET,
            definition_id=selection.filter_preset_id,
            version_number=selection.filter_preset_version_number,
            recorder=recorder,
            at=at,
        )

    async def _resolve_ranking_definition(
        self, repositories: Any, command: VariantQueryCommand, *, recorder: Any, at: datetime
    ) -> ResolvedSource:
        selection = command.ranking
        if selection.ranking_definition_id is None:
            return ResolvedSource()
        return await self._resolve(
            repositories,
            command.actor,
            repository=repositories.ranking_definitions,
            kind=SAVED_RANKING,
            definition_id=selection.ranking_definition_id,
            version_number=selection.ranking_version_number,
            recorder=recorder,
            at=at,
        )

    async def _resolve_ranking_preset(
        self, repositories: Any, command: VariantQueryCommand, *, recorder: Any, at: datetime
    ) -> ResolvedSource:
        selection = command.ranking
        if selection.ranking_preset_id is None:
            return ResolvedSource()
        return await self._resolve(
            repositories,
            command.actor,
            repository=repositories.ranking_presets,
            kind=RANKING_PRESET,
            definition_id=selection.ranking_preset_id,
            version_number=selection.ranking_preset_version_number,
            recorder=recorder,
            at=at,
        )

    async def _resolve(
        self,
        repositories: Any,
        actor: ActorContext,
        *,
        repository: Any,
        kind: Any,
        definition_id: str,
        version_number: int | None,
        recorder: Any,
        at: datetime,
    ) -> ResolvedSource:
        """Authorize the definition, then pin the exact version being applied."""
        definition = await repository.get(definition_id)
        if definition is None:
            raise NotFoundError(kind.name, definition_id)
        await require_configuration_access(
            self._services,
            repositories,
            actor,
            definition,
            kind=kind,
            manage=False,
            recorder=recorder,
            occurred_at=at,
        )
        if not definition.is_usable:
            raise ConflictError(
                "this configuration is not available for execution",
                details={"state": definition.state.value},
            )
        if version_number is None:
            version = await repository.latest_version(definition.id)
        else:
            version = await repository.find_version(
                definition_id=definition.id, version_number=version_number
            )
        if version is None:
            raise NotFoundError(f"{kind.name}_version", str(version_number or "latest"))
        # Marking the version referenced is what makes it permanently immutable:
        # from here on an edit must append a new version.
        await repository.mark_version_referenced(version.id)
        return ResolvedSource(
            definition_id=definition.id,
            version_id=version.id,
            version_number=version.version_number,
            canonical=version.canonical,
        )

    @staticmethod
    def _assert_single_ranking_source(selection: RankingSelection) -> None:
        named = [
            value
            for value in (
                selection.configuration,
                selection.ranking_definition_id,
                selection.ranking_preset_id,
            )
            if value is not None
        ]
        if len(named) > 1:
            raise ValidationError(
                "a query applies exactly one ranking configuration",
                details={"supplied": len(named)},
            )

    def _ranking_payload(
        self,
        selection: RankingSelection,
        definition: ResolvedSource,
        preset: ResolvedSource,
    ) -> dict[str, Any] | None:
        """A ranking comes from exactly one source. Combining two would be ambiguous."""
        sources = [
            source
            for source in (selection.configuration, definition.canonical, preset.canonical)
            if source is not None
        ]
        if not sources:
            return None
        if len(sources) > 1:
            raise ValidationError(
                "a query applies exactly one ranking configuration",
                details={"supplied": len(sources)},
            )
        return sources[0]


@dataclass(frozen=True, slots=True)
class _Outcome:
    rows: tuple[dict[str, Any], ...]
    total: int | None
    next_cursor: str | None
    duration_ms: int | None
    scored_count: int = 0
    unscored_count: int = 0
    window_exceeded: bool = False
    window_rows: int | None = None


__all__ = [
    "DEFAULT_ORDER_FIELD_IDS",
    "RANKING_WINDOW_ROWS",
    "ExecuteVariantQuery",
    "FilterSelection",
    "RankingSelection",
    "ResolvedSource",
    "VariantQueryCommand",
    "VariantQueryPage",
]
