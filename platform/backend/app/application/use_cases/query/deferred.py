"""Deferring an expensive variant query onto the existing durable job system.

A bounded page is answered inside the request. Anything larger — a whole
filtered surface, a ranked set wider than the scoring window, an export feeding
a downstream step — is *requested* here and *executed* by an application worker
through the Package 5 job system. No second queue, no second analytical store,
no browser-side filtering.

Two halves, deliberately separated:

* :class:`DeferVariantQuery` runs in the caller's request. It authorizes, it
  resolves and validates the filter and ranking exactly as the synchronous path
  does, and only then enqueues. A malformed or unauthorized query therefore
  fails immediately with a structured error instead of becoming a job that fails
  later out of sight.
* :class:`RunDeferredVariantQuery` runs in the worker. It resolves the
  requester's authorization context from the database — never from the payload —
  re-checks it, materializes rows into a new Parquet artifact under the
  platform's analytical root, and appends an execution record. Execution records
  are append-only, so the outcome is a new fact, not an edit of the request.

The materialized artifact is a derived, bounded read of already stored data. The
handler computes nothing scientific: it applies the same compiled predicate and
the same deterministic ordering the synchronous path would have applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.query.dependencies import (
    QUERY_EXECUTE,
    QueryServices,
    resolve_workspace_scope,
)
from app.application.use_cases.query.execution import (
    FilterSelection,
    RankingSelection,
    VariantQueryCommand,
    ExecuteVariantQuery,
)
from app.domain.analysis.policies import default_queue_for, node_class_for
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.query.canonical import canonical_payload
from app.domain.query.entities import FilterExecutionRecord, RankingExecutionRecord
from app.domain.query.expressions import FilterGroup, group_from_payload
from app.domain.query.ranking import spec_from_payload, validate_ranking
from app.domain.query.validation import combine_expressions, validate_filter
from app.domain.value_objects.enums import (
    AuditOutcome,
    JobKind,
    QueryExecutionOutcome,
)
from app.infrastructure.persistence.repositories.base import new_id

#: The job kind an expensive query runs as. It is an existing application-worker
#: kind registered in the Package 5 policy tables, not a new queue.
QUERY_JOB_KIND = JobKind.VARIANT_QUERY

#: Hard ceiling on a materialized query, expressed in rows. Exceeding it is
#: reported as ``limit_exceeded`` rather than written out as a partial artifact
#: that looks complete.
DEFAULT_MAX_MATERIALIZED_ROWS = 250_000

#: Where materialized query artifacts live under the configured analytical root.
MATERIALIZED_PREFIX = "query-materializations"


@dataclass(frozen=True, slots=True)
class DeferVariantQueryCommand:
    actor: ActorContext
    request: RequestContext
    result_set_id: str
    filter: FilterSelection = FilterSelection()
    ranking: RankingSelection = RankingSelection()
    field_ids: tuple[str, ...] = ()
    sort_field_id: str | None = None
    sort_descending: bool = False
    max_rows: int = DEFAULT_MAX_MATERIALIZED_ROWS
    #: Free-form caller context recorded with the execution (for example the
    #: analysis this materialization feeds). Never interpreted as a grant.
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeferredQueryAccepted:
    job_id: str
    result_set_id: str
    effective_hash: str
    field_dictionary_version: str
    max_rows: int


@dataclass(frozen=True, slots=True)
class DeferredQueryOutcome:
    execution: FilterExecutionRecord
    ranking_execution: RankingExecutionRecord | None
    location: str | None
    row_count: int
    outcome: QueryExecutionOutcome


def _as_command(payload: dict[str, Any], actor: ActorContext, request: RequestContext):
    return VariantQueryCommand(
        actor=actor,
        request=request,
        result_set_id=str(payload["result_set_id"]),
        filter=FilterSelection(**dict(payload.get("filter") or {})),
        ranking=RankingSelection(**dict(payload.get("ranking") or {})),
        field_ids=tuple(payload.get("field_ids") or ()),
        sort_field_id=payload.get("sort_field_id"),
        sort_descending=bool(payload.get("sort_descending")),
    )


class DeferVariantQuery:
    """Validates and authorizes an expensive query, then enqueues it."""

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(
        self, command: DeferVariantQueryCommand
    ) -> DeferredQueryAccepted:
        services = self._services
        if services.query_engine is None:
            raise ConflictError("analytical querying is not available")
        now = services.clock.now()
        ExecuteVariantQuery.assert_single_ranking_source(command.ranking)
        max_rows = self._max_rows(command.max_rows)
        inner = _as_command(
            {
                "result_set_id": command.result_set_id,
                "filter": _selection_payload(command.filter),
                "ranking": _selection_payload(command.ranking),
                "field_ids": list(command.field_ids),
                "sort_field_id": command.sort_field_id,
                "sort_descending": command.sort_descending,
            },
            command.actor,
            command.request,
        )
        executor = ExecuteVariantQuery(services)

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
            saved_filter, preset, ranking_definition, ranking_preset = (
                await executor.resolve_sources(
                    repositories, inner, recorder=recorder, at=now
                )
            )

            # Validated in the request, so a bad expression is a 4xx now rather
            # than a failed job later.
            validated, _ = await self._validate(
                inner,
                result_set.analytical_location,
                saved_filter,
                preset,
                ranking_definition,
                ranking_preset,
            )

            job_id = await repositories.jobs.enqueue(
                kind=QUERY_JOB_KIND,
                payload={
                    "requested_by": command.actor.actor_id,
                    "result_set_id": result_set.id,
                    "filter": _selection_payload(command.filter),
                    "ranking": _selection_payload(command.ranking),
                    "field_ids": list(command.field_ids),
                    "sort_field_id": command.sort_field_id,
                    "sort_descending": command.sort_descending,
                    "max_rows": max_rows,
                    "context": dict(command.context),
                },
                correlation_id=command.request.correlation_id,
                queue=default_queue_for(QUERY_JOB_KIND).value,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                requested_by=command.actor.actor_id,
                node_class=node_class_for(QUERY_JOB_KIND),
            )
            await recorder.audit(
                action="variant_query.deferred",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="result_set",
                resource_id=result_set.id,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                detail={
                    "job_id": job_id,
                    "effective_hash": validated.canonical_hash,
                    "max_rows": max_rows,
                },
            )

        return DeferredQueryAccepted(
            job_id=job_id,
            result_set_id=result_set.id,
            effective_hash=validated.canonical_hash,
            field_dictionary_version=validated.field_dictionary_version,
            max_rows=max_rows,
        )

    def _max_rows(self, requested: int) -> int:
        rows = int(requested)
        if rows < 1:
            raise ValidationError("a materialization must produce at least one row")
        if rows > DEFAULT_MAX_MATERIALIZED_ROWS:
            raise ValidationError(
                "the requested row ceiling exceeds the configured maximum",
                details={
                    "maximum": DEFAULT_MAX_MATERIALIZED_ROWS,
                    "requested": rows,
                },
            )
        return rows

    async def _validate(
        self,
        inner: VariantQueryCommand,
        location: str,
        saved_filter,
        preset,
        ranking_definition,
        ranking_preset,
    ):
        return await _validate_plan(
            self._services, inner, location, saved_filter, preset,
            ranking_definition, ranking_preset,
        )


async def _validate_plan(
    services: QueryServices,
    inner: VariantQueryCommand,
    location: str,
    saved_filter,
    preset,
    ranking_definition,
    ranking_preset,
):
    """Validate filter and ranking against the surface's actual columns."""
    description = await services.query_engine.describe(location)
    available = services.fields.available_for_columns(
        frozenset(column.name for column in description.columns)
    )
    available_ids = frozenset(definition.id for definition in available)

    parts: list[FilterGroup] = []
    for source in (saved_filter, preset):
        if source.canonical is not None:
            parts.append(group_from_payload(source.canonical))
    executor = ExecuteVariantQuery(services)
    custom = executor.custom_expression_of(inner.filter)
    if custom is not None:
        parts.append(custom)
    effective = combine_expressions(*parts)
    validated = validate_filter(
        effective,
        registry=services.fields,
        limits=services.limits,
        available_field_ids=available_ids,
        allow_empty=True,
    )
    ranking_payload = None
    if inner.ranking.configuration is not None:
        ranking_payload = inner.ranking.configuration
    elif ranking_definition.canonical is not None:
        ranking_payload = ranking_definition.canonical
    elif ranking_preset.canonical is not None:
        ranking_payload = ranking_preset.canonical
    ranking_validated = None
    ranking_spec = None
    if ranking_payload is not None:
        ranking_spec = spec_from_payload(ranking_payload)
        ranking_validated = validate_ranking(
            ranking_spec,
            methods=services.methods,
            registry=services.fields,
            available_field_ids=available_ids,
        )
    return validated, _Plan(
        available=available,
        available_ids=available_ids,
        effective=effective,
        validated=validated,
        custom=custom,
        ranking_spec=ranking_spec,
        ranking_validated=ranking_validated,
    )


@dataclass(frozen=True, slots=True)
class _Plan:
    available: tuple[Any, ...]
    available_ids: frozenset[str]
    effective: FilterGroup | None
    validated: Any
    custom: FilterGroup | None
    ranking_spec: Any
    ranking_validated: Any


def _selection_payload(selection: Any) -> dict[str, Any]:
    return {
        name: getattr(selection, name)
        for name in selection.__slots__
        if getattr(selection, name) is not None
    }


class RunDeferredVariantQuery:
    """Worker half: materializes the query and records what it executed."""

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(
        self, payload: dict[str, Any], request: RequestContext
    ) -> DeferredQueryOutcome:
        services = self._services
        if services.query_engine is None:
            raise ConflictError("analytical querying is not available")
        now = services.clock.now()
        requested_by = str(payload["requested_by"])
        max_rows = int(payload.get("max_rows") or DEFAULT_MAX_MATERIALIZED_ROWS)

        async with services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            account = await repositories.users.get(requested_by)
            if account is None:
                raise NotFoundError("user", requested_by)
            # The actor is resolved from stored grants, never from the payload:
            # a job never widens the scope its requester actually had.
            actor = await services.authorization.resolve(repositories, account)
            inner = _as_command(payload, actor, request)
            result_set = await repositories.result_sets.get(inner.result_set_id)
            if result_set is None:
                raise NotFoundError("result_set", inner.result_set_id)
            await resolve_workspace_scope(
                services,
                repositories,
                actor,
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
            executor = ExecuteVariantQuery(services)
            saved_filter, preset, ranking_definition, ranking_preset = (
                await executor.resolve_sources(
                    repositories, inner, recorder=recorder, at=now
                )
            )
            location = result_set.analytical_location

        validated, plan = await _validate_plan(
            services, inner, location, saved_filter, preset,
            ranking_definition, ranking_preset,
        )
        executor = ExecuteVariantQuery(services)
        selected_ids, selected_columns = executor.projection_for(
            inner.field_ids, plan.available, validated, plan.ranking_spec
        )
        order_by = executor.ordering_for(
            inner, plan.available_ids, ranked=plan.ranking_spec is not None
        )

        predicate = None
        if plan.effective is not None and validated.condition_count:
            from app.infrastructure.analytics.filter_compiler import compile_filter

            predicate = compile_filter(validated.expression, services.fields)

        execution_id = new_id("fex")
        target = services.query_engine.artifact_path(
            MATERIALIZED_PREFIX, f"{execution_id}.parquet"
        )
        # One row over the ceiling is enough to know the ceiling was reached, so
        # the read asks for one extra rather than reporting a partial set as whole.
        written = await services.query_engine.materialize(
            location,
            target=target,
            columns=selected_columns,
            predicate=predicate,
            order_by=order_by,
            max_rows=max_rows + 1,
        )
        exceeded = written > max_rows
        outcome = (
            QueryExecutionOutcome.LIMIT_EXCEEDED
            if exceeded
            else QueryExecutionOutcome.COMPLETED
        )

        async with services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            execution = FilterExecutionRecord(
                id=execution_id,
                workspace_id=result_set.workspace_id,
                executed_by=requested_by,
                executed_at=now,
                result_set_id=result_set.id,
                effective_canonical=validated.canonical,
                effective_hash=validated.canonical_hash,
                field_dictionary_version=validated.field_dictionary_version,
                outcome=outcome,
                project_id=result_set.project_id,
                dataset_version_id=getattr(result_set, "dataset_version_id", None),
                filter_definition_id=saved_filter.definition_id,
                filter_version_id=saved_filter.version_id,
                filter_version_number=saved_filter.version_number,
                filter_preset_id=preset.definition_id,
                filter_preset_version_id=preset.version_id,
                filter_preset_version_number=preset.version_number,
                custom_canonical=(
                    canonical_payload(plan.custom) if plan.custom else None
                ),
                returned_count=min(written, max_rows),
                page_size=0,
                software_version=services.software_version,
                correlation_id=request.correlation_id,
                failure_reason=(
                    "the materialized row ceiling was reached" if exceeded else None
                ),
                metadata={
                    "deferred": True,
                    "materialized_location": target if not exceeded else None,
                    "max_rows": max_rows,
                    "field_ids": list(selected_ids),
                    "context": dict(payload.get("context") or {}),
                },
            )
            await repositories.query_executions.add_filter_execution(execution)
            ranking_execution: RankingExecutionRecord | None = None
            if plan.ranking_validated is not None and plan.ranking_spec is not None:
                ranking_execution = RankingExecutionRecord(
                    id=new_id("rex"),
                    filter_execution_id=execution.id,
                    workspace_id=result_set.workspace_id,
                    executed_by=requested_by,
                    executed_at=now,
                    method_id=plan.ranking_validated.method.id,
                    method_version=plan.ranking_validated.method.version,
                    method_implementation_id=(
                        plan.ranking_validated.method.implementation_id
                    ),
                    effective_canonical=plan.ranking_validated.canonical,
                    effective_hash=plan.ranking_validated.canonical_hash,
                    field_dictionary_version=(
                        plan.ranking_validated.field_dictionary_version
                    ),
                    direction=plan.ranking_spec.direction.value,
                    tie_breakers=plan.ranking_spec.tie_breakers,
                    project_id=result_set.project_id,
                    ranking_definition_id=ranking_definition.definition_id,
                    ranking_version_id=ranking_definition.version_id,
                    ranking_version_number=ranking_definition.version_number,
                    ranking_preset_id=ranking_preset.definition_id,
                    ranking_preset_version_id=ranking_preset.version_id,
                    ranking_preset_version_number=ranking_preset.version_number,
                    outcome=outcome,
                    software_version=services.software_version,
                    correlation_id=request.correlation_id,
                    metadata={"deferred": True},
                )
                await repositories.query_executions.add_ranking_execution(
                    ranking_execution
                )
            await recorder.audit(
                action="variant_query.materialized",
                outcome=(
                    AuditOutcome.SUCCESS if not exceeded else AuditOutcome.FAILURE
                ),
                occurred_at=now,
                actor_user_id=requested_by,
                resource_type="result_set",
                resource_id=result_set.id,
                workspace_id=result_set.workspace_id,
                project_id=result_set.project_id,
                detail={
                    "filter_execution_id": execution.id,
                    "row_count": min(written, max_rows),
                    "outcome": outcome.value,
                },
            )

        return DeferredQueryOutcome(
            execution=execution,
            ranking_execution=ranking_execution,
            location=None if exceeded else target,
            row_count=min(written, max_rows),
            outcome=outcome,
        )


__all__ = [
    "DEFAULT_MAX_MATERIALIZED_ROWS",
    "MATERIALIZED_PREFIX",
    "QUERY_JOB_KIND",
    "DeferVariantQuery",
    "DeferVariantQueryCommand",
    "DeferredQueryAccepted",
    "DeferredQueryOutcome",
    "RunDeferredVariantQuery",
]
