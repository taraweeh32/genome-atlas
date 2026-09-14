"""Executing bounded, parameterized analytical queries through DuckDB.

The engine reuses the Package 6 analytical boundary (``AnalyticsGateway`` over the
configured Parquet root) — there is no second analytical store and no second
connection policy.

Properties that are enforced here rather than trusted:

* **Every value is bound.** Statements are assembled from platform-authored
  identifiers plus ``?`` placeholders; caller values are passed to DuckDB as
  parameters. Predicate SQL arrives pre-compiled from ``filter_compiler``.
* **Every read is bounded.** ``limit`` is mandatory and the engine fetches one row
  beyond it to report truncation honestly, instead of guessing whether more rows
  exist.
* **Every page is deterministically ordered.** Ordering columns are appended to
  the statement in the order given; keyset continuation is derived from the same
  ordering, so a page boundary cannot drift between requests.
* **Predicate pushdown.** Filters are handed to ``read_parquet`` as a WHERE clause
  in the same statement, so DuckDB prunes row groups and columns itself. The
  platform never materializes a whole file to filter it in Python.

DuckDB is synchronous, so every call runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import time

from app.application.ports import (
    AnalyticalColumn,
    AnalyticalDescription,
    AnalyticalDistinctValue,
    AnalyticalDistinctValues,
    AnalyticalPredicate,
    AnalyticalQueryResult,
    AnalyticalQuerySpec,
)
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.analytics.filter_compiler import quote_identifier
from app.infrastructure.analytics.result_reader import validated_location as _validated

logger = get_logger(__name__)

#: Hard ceiling on one page, independent of any configured limit. A page larger
#: than this is a resource decision, not a presentation one.
MAX_QUERY_ROWS = 1000

#: Hard ceiling on a distinct-value response. A high-cardinality field can have
#: millions of values; an unbounded distinct query is never issued.
MAX_DISTINCT_VALUES = 200


def keyset_predicate(
    order_by: tuple[tuple[str, bool], ...], values: tuple[object, ...]
) -> AnalyticalPredicate:
    """Continue an ordering strictly after the given row.

    Expanded as the usual lexicographic disjunction rather than a row comparison,
    because the ordering mixes ascending and descending columns and because nulls
    must sort consistently with the ORDER BY clause below.
    """
    if not order_by or len(order_by) != len(values):
        raise InfrastructureError("cursor does not match the query ordering")

    clauses: list[str] = []
    parameters: list[object] = []
    for index in range(len(order_by)):
        parts: list[str] = []
        for earlier in range(index):
            # ``IS NOT DISTINCT FROM`` so a null ordering value still compares
            # equal to itself; ``=`` would drop the boundary row silently.
            parts.append(f"{quote_identifier(order_by[earlier][0])} IS NOT DISTINCT FROM ?")
            parameters.append(values[earlier])
        column, descending = order_by[index]
        parts.append(f"{quote_identifier(column)} {'<' if descending else '>'} ?")
        parameters.append(values[index])
        clauses.append("(" + " AND ".join(parts) + ")")
    return AnalyticalPredicate("(" + " OR ".join(clauses) + ")", tuple(parameters))


def _order_clause(order_by: tuple[tuple[str, bool], ...]) -> str:
    if not order_by:
        return ""
    parts = [
        f"{quote_identifier(column)} {'DESC' if descending else 'ASC'} NULLS LAST"
        for column, descending in order_by
    ]
    return " ORDER BY " + ", ".join(parts)


def _where_clause(*predicates: AnalyticalPredicate | None) -> tuple[str, tuple[object, ...]]:
    present = [predicate for predicate in predicates if predicate is not None]
    if not present:
        return "", ()
    parameters: tuple[object, ...] = ()
    for predicate in present:
        parameters += predicate.parameters
    return " WHERE " + " AND ".join(p.sql for p in present), parameters


class DuckDbQueryEngine:
    """``AnalyticalQueryService`` over the configured Parquet root."""

    def __init__(self, analytics: AnalyticsGateway) -> None:
        self._analytics = analytics

    async def execute(self, spec: AnalyticalQuerySpec) -> AnalyticalQueryResult:
        if not spec.columns:
            raise InfrastructureError("an analytical query must select columns")
        limit = max(1, min(int(spec.limit), MAX_QUERY_ROWS))
        return await asyncio.to_thread(self._execute, spec, limit)

    async def distinct_values(
        self,
        location: str,
        *,
        column: str,
        search: str | None,
        limit: int,
        predicate: AnalyticalPredicate | None = None,
        with_counts: bool = False,
    ) -> AnalyticalDistinctValues:
        bounded = max(1, min(int(limit), MAX_DISTINCT_VALUES))
        return await asyncio.to_thread(
            self._distinct_values,
            _validated(location),
            column,
            search,
            bounded,
            predicate,
            with_counts,
        )

    async def materialize(
        self,
        location: str,
        *,
        target: str,
        columns: tuple[str, ...],
        predicate: AnalyticalPredicate | None,
        order_by: tuple[tuple[str, bool], ...],
        max_rows: int,
    ) -> int:
        """Write the filtered, ordered rows of a query to a new Parquet artifact.

        Used by the deferred (durable job) path, where a result is too large for a
        request. ``max_rows`` is a governance ceiling, not a page: exceeding it is
        reported by the caller as a limit outcome rather than silently truncated
        into something that looks complete.
        """
        if not columns:
            raise InfrastructureError("an analytical query must select columns")
        return await asyncio.to_thread(
            self._materialize,
            _validated(location),
            _validated(target),
            columns,
            predicate,
            order_by,
            max(1, int(max_rows)),
        )

    async def describe(self, location: str) -> AnalyticalDescription:
        """Physical columns and row count of a surface, as the file declares them.

        Used to narrow the advertised field dictionary to what a surface actually
        carries, so no user is offered a condition that cannot apply.
        """
        return await asyncio.to_thread(self._describe, _validated(location))

    # -- synchronous bodies, executed off the event loop --------------------- #

    def _describe(self, location: str) -> AnalyticalDescription:
        with self._analytics.connection() as connection:
            columns = tuple(
                AnalyticalColumn(name=str(row[0]), data_type=str(row[1]))
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{location}')"
                ).fetchall()
            )
            count_row = connection.execute(
                f"SELECT count(*) FROM read_parquet('{location}')"
            ).fetchone()
        if count_row is None:
            raise InfrastructureError("analytical surface could not be read")
        return AnalyticalDescription(
            location=location, row_count=int(count_row[0]), columns=columns
        )

    def _materialize(
        self,
        location: str,
        target: str,
        columns: tuple[str, ...],
        predicate: AnalyticalPredicate | None,
        order_by: tuple[tuple[str, bool], ...],
        max_rows: int,
    ) -> int:
        selected = ", ".join(quote_identifier(name) for name in columns)
        where, parameters = _where_clause(predicate)
        order = _order_clause(order_by)
        with self._analytics.connection() as connection:
            # Both locations are platform-authored paths under the configured
            # analytical root; every caller value is still a bound parameter.
            connection.execute(
                f"COPY (SELECT {selected} FROM read_parquet('{location}')"
                f"{where}{order} LIMIT {max_rows}) TO '{target}' (FORMAT PARQUET)",
                list(parameters),
            )
            written = connection.execute(
                f"SELECT count(*) FROM read_parquet('{target}')"
            ).fetchone()
        return int(written[0]) if written else 0

    def _execute(self, spec: AnalyticalQuerySpec, limit: int) -> AnalyticalQueryResult:
        location = _validated(spec.location)
        selected = ", ".join(quote_identifier(name) for name in spec.columns)
        where, parameters = _where_clause(spec.predicate, spec.keyset)
        order = _order_clause(spec.order_by)
        started = time.monotonic()
        with self._analytics.connection() as connection:
            # One row beyond the page: truncation is observed, not inferred.
            statement = (
                f"SELECT {selected} FROM read_parquet('{location}')"
                f"{where}{order} LIMIT {limit + 1}"
            )
            result = connection.execute(statement, list(parameters))
            names = tuple(str(item[0]) for item in result.description or ())
            fetched = [tuple(row) for row in result.fetchall()]
            total: int | None = None
            if spec.count_total:
                # Counted against the filter but *not* against the cursor: the
                # total describes the filtered set, not the remainder of a page.
                count_where, count_parameters = _where_clause(spec.predicate)
                count_row = connection.execute(
                    f"SELECT count(*) FROM read_parquet('{location}'){count_where}",
                    list(count_parameters),
                ).fetchone()
                total = int(count_row[0]) if count_row else None
        duration = int((time.monotonic() - started) * 1000)
        truncated = len(fetched) > limit
        return AnalyticalQueryResult(
            columns=names,
            rows=tuple(fetched[:limit]),
            total_rows=total,
            truncated=truncated,
            duration_ms=duration,
        )

    def _distinct_values(
        self,
        location: str,
        column: str,
        search: str | None,
        limit: int,
        predicate: AnalyticalPredicate | None,
        with_counts: bool,
    ) -> AnalyticalDistinctValues:
        quoted = quote_identifier(column)
        clauses: list[AnalyticalPredicate] = []
        if predicate is not None:
            clauses.append(predicate)
        # Missing values are not offered as selectable values: "has no value" is an
        # operator (IS MISSING), not an entry in a value list.
        clauses.append(AnalyticalPredicate(f"{quoted} IS NOT NULL"))
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                AnalyticalPredicate(
                    f"lower(CAST({quoted} AS VARCHAR)) LIKE ? ESCAPE '\\'",
                    (f"%{escaped.lower()}%",),
                )
            )
        where, parameters = _where_clause(*clauses)
        projection = (
            f"{quoted} AS value, count(*) AS occurrences" if with_counts else f"{quoted} AS value"
        )
        grouping = f" GROUP BY {quoted}" if with_counts else ""
        ordering = " ORDER BY occurrences DESC, value ASC" if with_counts else f" ORDER BY {quoted}"
        distinct = "" if with_counts else "DISTINCT "
        with self._analytics.connection() as connection:
            rows = connection.execute(
                f"SELECT {distinct}{projection} FROM read_parquet('{location}')"
                f"{where}{grouping}{ordering} LIMIT {limit + 1}",
                list(parameters),
            ).fetchall()
        truncated = len(rows) > limit
        values = tuple(
            AnalyticalDistinctValue(
                value=row[0], occurrence_count=int(row[1]) if with_counts else None
            )
            for row in rows[:limit]
        )
        return AnalyticalDistinctValues(column=column, values=values, truncated=truncated)


__all__ = [
    "MAX_DISTINCT_VALUES",
    "MAX_QUERY_ROWS",
    "DuckDbQueryEngine",
    "keyset_predicate",
]
