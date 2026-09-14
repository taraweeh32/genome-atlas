"""Reading materialized result surfaces out of Parquet through DuckDB.

Two properties matter more than anything this module does functionally:

* **No user input reaches SQL.** The only variable part of every statement is a
  location that the platform itself constructed under the configured Parquet root
  (``AnalyticsGateway.dataset_path``), plus integer offsets that are cast before
  interpolation. Nothing here accepts a column list, predicate or ordering from a
  request.
* **Nothing is interpreted.** ``describe`` reports the row count and physical
  column types that the file declares; ``read_page`` returns values as stored.
  Meaning stays with the engine's payload.

DuckDB is synchronous, so calls run in a worker thread rather than blocking the
event loop.
"""

from __future__ import annotations

import asyncio
import re

from app.application.ports import AnalyticalColumn, AnalyticalDescription, AnalyticalPage
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway

logger = get_logger(__name__)

#: Locations the platform generates: a URI or path under the configured root,
#: optionally ending in a single ``*`` partition glob. Anything else is refused
#: rather than escaped, because a location that does not look like ours is a bug
#: or an attack, never a query to run.
_LOCATION_PATTERN = re.compile(r"^[A-Za-z0-9:/._@=*-]{1,1024}$")

#: Upper bound on one presentation window. Large result reads go through the
#: export path (a durable job), not through a request.
MAX_PAGE_ROWS = 500


def validated_location(location: str) -> str:
    """Refuse any location that the platform did not itself construct."""
    if not _LOCATION_PATTERN.fullmatch(location) or "'" in location or ".." in location:
        raise InfrastructureError("invalid analytical location")
    return location


class DuckDbResultReader:
    """``AnalyticalReadService`` over the Parquet root."""

    def __init__(self, analytics: AnalyticsGateway) -> None:
        self._analytics = analytics

    async def describe(self, location: str) -> AnalyticalDescription:
        return await asyncio.to_thread(self._describe, validated_location(location))

    async def read_page(
        self, location: str, *, offset: int, limit: int
    ) -> AnalyticalPage:
        bounded = max(1, min(int(limit), MAX_PAGE_ROWS))
        return await asyncio.to_thread(
            self._read_page, validated_location(location), max(0, int(offset)), bounded
        )

    # -- synchronous bodies, executed off the event loop ------------------- #

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

    def _read_page(self, location: str, offset: int, limit: int) -> AnalyticalPage:
        with self._analytics.connection() as connection:
            # Stable ordering by physical row position: presentation ordering is a
            # separate, versioned concern and is not decided here.
            result = connection.execute(
                "SELECT * FROM read_parquet"
                f"('{location}') LIMIT {limit} OFFSET {offset}"
            )
            names = tuple(str(description[0]) for description in result.description or ())
            rows = tuple(tuple(row) for row in result.fetchall())
            count_row = connection.execute(
                f"SELECT count(*) FROM read_parquet('{location}')"
            ).fetchone()
        return AnalyticalPage(
            columns=names,
            rows=rows,
            total_rows=int(count_row[0]) if count_row else len(rows),
        )


__all__ = ["MAX_PAGE_ROWS", "DuckDbResultReader", "validated_location"]
