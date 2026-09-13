"""An in-memory stand-in for the Parquet/DuckDB read boundary.

Registered surfaces only: asking for a location nobody produced raises the same
``InfrastructureError`` the real reader raises, because "this surface cannot be
read" is a state the platform must handle, not an empty table.

Like the real reader, it can describe a surface and return a bounded window. It
cannot filter, rank or interpret — there is no such method to call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.application.ports import AnalyticalColumn, AnalyticalDescription, AnalyticalPage
from app.domain.errors import InfrastructureError


@dataclass
class StubAnalyticalReader:
    surfaces: dict[str, tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]] = field(
        default_factory=dict
    )
    reads: list[tuple[str, int, int]] = field(default_factory=list)

    def register(
        self,
        location: str,
        *,
        columns: tuple[str, ...],
        rows: tuple[tuple[object, ...], ...] = (),
    ) -> None:
        self.surfaces[location] = (columns, rows)

    def _surface(self, location: str):
        surface = self.surfaces.get(location)
        if surface is None:
            raise InfrastructureError(f"no readable surface at {location!r}")
        return surface

    async def describe(self, location: str) -> AnalyticalDescription:
        columns, rows = self._surface(location)
        return AnalyticalDescription(
            location=location,
            columns=tuple(
                AnalyticalColumn(name=name, data_type="VARCHAR")
                for name in columns
            ),
            row_count=len(rows),
        )

    async def read_page(
        self, location: str, *, offset: int = 0, limit: int = 100
    ) -> AnalyticalPage:
        columns, rows = self._surface(location)
        self.reads.append((location, offset, limit))
        window = rows[offset : offset + limit]
        return AnalyticalPage(columns=columns, rows=window, total_rows=len(rows))


__all__ = ["StubAnalyticalReader"]
