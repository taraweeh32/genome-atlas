"""Arrangement for the Package 7 filtering and ranking tests.

Deliberately runs against a **real Parquet file through the real DuckDB engine**.
A stub that answered filter questions in Python would prove nothing about the
predicates the platform actually executes, about pushdown, or about how DuckDB
treats a missing value — which is precisely what these tests are for.

The rows below are fixture-declared claims, not scientific output: the values
stand for "this is what the engine recorded", nothing more.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from app.application.repositories import Page
from app.application.use_cases.query.dependencies import QueryServices
from app.core.app_config import ApplicationSettings
from app.core.environment import AnalyticsSettings
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.analytics.query_engine import DuckDbQueryEngine
from app.domain.query.fields import DEFAULT_FIELD_REGISTRY
from tests.results.support import available_result, execution_for

PAGE = Page(number=1, size=25)

#: Physical columns the fixture surface carries, named exactly as the field
#: dictionary maps them.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("contig", "VARCHAR"),
    ("position", "BIGINT"),
    ("reference_allele", "VARCHAR"),
    ("alternate_allele", "VARCHAR"),
    ("gene_symbol", "VARCHAR"),
    ("consequence_term", "VARCHAR"),
    ("allele_frequency", "DOUBLE"),
    ("read_depth", "BIGINT"),
    ("clinical_significance", "VARCHAR"),
)

#: One row per case the tests need: values present, a null frequency (never
#: reported), a zero frequency (reported as zero — a different fact), and a row
#: whose ranking inputs are entirely absent.
ROWS: tuple[tuple[Any, ...], ...] = (
    ("chr1", 1000, "A", "T", "CFTR", "missense_variant", 0.0004, 40, "uncertain"),
    ("chr1", 2000, "G", "C", "ABCA4", "synonymous_variant", 0.2, 30, None),
    ("chr2", 3000, "T", "G", "CFTR", "stop_gained", None, 25, "conflicting"),
    ("chr2", 4000, "C", "A", "BRCA2", "missense_variant", 0.0, 60, "uncertain"),
    ("chr3", 5000, "G", "A", None, None, None, None, None),
)


def write_surface(root: Path, *, name: str = "variants.parquet", rows=ROWS) -> str:
    """Materialize the fixture surface and return its location."""
    root.mkdir(parents=True, exist_ok=True)
    location = str(root / name)
    connection = duckdb.connect(database=":memory:")
    try:
        columns = ", ".join(f'"{name}" {kind}' for name, kind in COLUMNS)
        connection.execute(f"CREATE TABLE surface ({columns})")
        placeholders = ", ".join("?" for _ in COLUMNS)
        connection.executemany(
            f"INSERT INTO surface VALUES ({placeholders})", [list(row) for row in rows]
        )
        connection.execute(f"COPY surface TO '{location}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return location


def query_services(harness, root: Path, **overrides) -> QueryServices:
    """Query services wired to the real analytical engine over ``root``."""
    engine = DuckDbQueryEngine(
        AnalyticsGateway(AnalyticsSettings(parquet_root=str(root)))
    )
    values: dict[str, Any] = {
        "unit_of_work": harness.unit_of_work,
        "clock": harness.clock,
        "authorization": harness.authorization,
        "config": ApplicationSettings(),
        "query_engine": engine,
        "fields": DEFAULT_FIELD_REGISTRY,
    }
    values.update(overrides)
    return QueryServices(**values)


async def surface_result_set(harness, user_id: str, location: str):
    """A readable result set whose analytical content is the fixture surface."""
    from tests.results.support import result_payload

    _, execution, _ = await execution_for(harness, user_id)
    harness.analytics.register(
        location,
        columns=tuple(name for name, _ in COLUMNS),
        rows=ROWS,
    )
    view = await available_result(
        harness,
        user_id,
        execution.id,
        payload=result_payload(
            analysis_execution_id=execution.id,
            analytical_location=location,
            row_count=len(ROWS),
        ),
        register_surface=False,
    )
    return view.result_set


def condition(
    field_id: str,
    operator: str,
    *values: Any,
    negated: bool = False,
) -> dict[str, Any]:
    return {
        "kind": "condition",
        "field_id": field_id,
        "operator": operator,
        "values": list(values),
        "negated": negated,
    }


def group(*children: dict[str, Any], operator: str = "and") -> dict[str, Any]:
    return {"kind": "group", "operator": operator, "children": list(children)}


__all__ = [
    "COLUMNS",
    "PAGE",
    "ROWS",
    "condition",
    "group",
    "query_services",
    "surface_result_set",
    "write_surface",
]
