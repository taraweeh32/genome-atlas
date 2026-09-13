"""Parquet / DuckDB analytical boundary.

INTENDED USE
------------
Large genomic result sets (variant tables, annotation matrices, per-analysis
result sets) are written as Parquet into object storage by the scientific
subsystem and queried column-wise through DuckDB. They are:

- read-oriented and analytical,
- addressed per analysis/dataset partition,
- **complementary to** PostgreSQL, never a replacement for it.

PostgreSQL remains authoritative for transactional application state (who owns
what, job state, review decisions, interpretations). Large result data is never
forced through ordinary relational tables or ordinary paginated API responses;
consumers receive filtered/aggregated slices or artifact references.

Package 1 deliberately implements only configuration and the connection
boundary. Variant query construction, filtering, ranking and result projection
belong to later packages.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import duckdb

from app.core.environment import AnalyticsSettings
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError

logger = get_logger(__name__)


class AnalyticsGateway:
    """Opens short-lived, configured DuckDB connections over the Parquet root."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self._settings = settings

    @property
    def parquet_root(self) -> str:
        return self._settings.parquet_root

    def dataset_path(self, *segments: str) -> str:
        """Resolve a partition path under the configured Parquet root."""
        if any("/" in segment or ".." in segment for segment in segments):
            raise InfrastructureError("invalid analytics path segment")
        return "/".join([self._settings.parquet_root.rstrip("/"), *segments])

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(f"SET memory_limit='{self._settings.duckdb_memory_limit}'")
            connection.execute(f"SET threads={self._settings.duckdb_threads}")
            connection.execute("INSTALL httpfs; LOAD httpfs;")
            yield connection
        except duckdb.Error as exc:
            raise InfrastructureError("analytical query engine failure") from exc
        finally:
            connection.close()
