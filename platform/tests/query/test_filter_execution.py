"""Filtering executed for real: predicates, missing values, pagination, ranking.

Every assertion here goes through the API-facing use case down to DuckDB over a
real Parquet file, because the properties being asserted — pushdown, missing-value
semantics, deterministic paging — only exist at that level.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.query.execution import (
    ExecuteVariantQuery,
    FilterSelection,
    RankingSelection,
    VariantQueryCommand,
)
from app.domain.errors import ValidationError
from tests.query.support import (
    condition,
    group,
    query_services,
    surface_result_set,
    write_surface,
)
from tests.support.actors import actor_for
from tests.support.actors import create_account
from tests.support.services import build_harness


async def build_surface(tmp_path):
    """Harness, account, readable surface and query services, wired for real."""
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.org")
    location = write_surface(tmp_path / "analytics")
    result_set = await surface_result_set(harness, user_id, location)
    services = query_services(harness, tmp_path / "analytics")
    return harness, user_id, result_set, services


async def run(services, harness, user_id, result_set, **kwargs):
    return await ExecuteVariantQuery(services).execute(
        VariantQueryCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            result_set_id=result_set.id,
            **kwargs,
        )
    )


async def test_unfiltered_query_returns_every_row_in_deterministic_order(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    page = await run(services, harness, user_id, result_set, page_size=10)

    assert page.returned_count == 5
    assert [row["position"] for row in page.rows] == [1000, 2000, 3000, 4000, 5000]
    assert page.next_cursor is None
    # The execution record is the reproducibility contract, written every time.
    assert page.execution.effective_hash
    assert page.execution.field_dictionary_version


async def test_predicate_is_pushed_down_and_narrows_the_result(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    page = await run(
        services,
        harness,
        user_id,
        result_set,
        filter=FilterSelection(expression=group(condition("gene_symbol", "equals", "CFTR"))),
    )

    assert [row["position"] for row in page.rows] == [1000, 3000]


async def test_nested_and_or_group_is_evaluated_as_written(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    expression = group(
        condition("contig", "equals", "chr2"),
        group(
            condition("consequence_term", "equals", "stop_gained"),
            condition("read_depth", "greater_than_or_equal", 50),
            operator="or",
        ),
    )
    page = await run(
        services, harness, user_id, result_set, filter=FilterSelection(expression=expression)
    )

    assert sorted(row["position"] for row in page.rows) == [3000, 4000]


async def test_a_never_reported_value_is_not_treated_as_zero(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    below = await run(
        services,
        harness,
        user_id,
        result_set,
        filter=FilterSelection(
            expression=group(condition("allele_frequency", "less_than", 0.001))
        ),
    )
    missing = await run(
        services,
        harness,
        user_id,
        result_set,
        filter=FilterSelection(
            expression=group(condition("allele_frequency", "is_missing"))
        ),
    )

    # 0.0004 and 0.0 are below the threshold; the two rows with no reported
    # frequency are not, because "unreported" is not "zero".
    assert sorted(row["position"] for row in below.rows) == [1000, 4000]
    assert sorted(row["position"] for row in missing.rows) == [3000, 5000]


async def test_negation_keeps_missing_rows_out_rather_than_including_them(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    page = await run(
        services,
        harness,
        user_id,
        result_set,
        filter=FilterSelection(
            expression=group(condition("gene_symbol", "equals", "CFTR", negated=True))
        ),
    )

    # chr3:5000 has no reported gene: it is neither CFTR nor not-CFTR, so a
    # negated equality does not silently claim it.
    assert sorted(row["position"] for row in page.rows) == [2000, 4000]


async def test_keyset_pagination_walks_every_row_exactly_once(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    seen: list[int] = []
    cursor = None
    for _ in range(5):
        page = await run(
            services, harness, user_id, result_set, page_size=2, cursor=cursor
        )
        seen.extend(row["position"] for row in page.rows)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == [1000, 2000, 3000, 4000, 5000]
    assert cursor is None


async def test_a_cursor_from_another_query_is_refused(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    first = await run(services, harness, user_id, result_set, page_size=2)
    assert first.next_cursor is not None

    with pytest.raises(ValidationError):
        await run(
            services,
            harness,
            user_id,
            result_set,
            page_size=2,
            cursor=first.next_cursor,
            filter=FilterSelection(
                expression=group(condition("contig", "equals", "chr1"))
            ),
        )


async def test_total_is_absent_unless_it_was_asked_for(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    without = await run(services, harness, user_id, result_set, page_size=2)
    with_total = await run(
        services, harness, user_id, result_set, page_size=2, include_total=True
    )

    assert without.total_count is None
    assert with_total.total_count == 5


async def test_page_size_above_the_configured_maximum_is_refused(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    with pytest.raises(ValidationError):
        await run(services, harness, user_id, result_set, page_size=services.max_page_size + 1)


async def test_ranking_reorders_without_changing_the_filtered_set(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    ranking = {
        "method_id": "weighted_field_score",
        "method_version": "1.0.0",
        "direction": "descending",
        "tie_breakers": ["position"],
        "components": [
            {
                "field_id": "allele_frequency",
                "kind": "numeric_ascending",
                "weight": 1.0,
                "scale_min": 0.0,
                "scale_max": 0.01,
            }
        ],
    }
    unranked = await run(services, harness, user_id, result_set, page_size=10)
    ranked = await run(
        services,
        harness,
        user_id,
        result_set,
        page_size=10,
        ranking=RankingSelection(configuration=ranking),
    )

    assert {row["position"] for row in ranked.rows} == {
        row["position"] for row in unranked.rows
    }
    scored = [row for row in ranked.rows if row["_prioritization_score"] is not None]
    # A lower reported frequency scores higher under this configuration; the rows
    # with no reported frequency are unscored and sort last.
    assert [row["position"] for row in scored] == [4000, 1000, 2000]
    assert ranked.rows[-1]["_prioritization_score"] is None
    assert ranked.ranking_execution is not None
    assert ranked.ranking_execution.unscored_count == 2
    assert ranked.ranking_execution.filter_execution_id == ranked.execution.id


async def test_ranking_cannot_reintroduce_a_filtered_out_row(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    ranking = {
        "method_id": "weighted_field_score",
        "method_version": "1.0.0",
        "components": [
            {
                "field_id": "read_depth",
                "kind": "numeric_descending",
                "weight": 1.0,
                "scale_min": 0.0,
                "scale_max": 100.0,
            }
        ],
    }
    page = await run(
        services,
        harness,
        user_id,
        result_set,
        filter=FilterSelection(expression=group(condition("contig", "equals", "chr1"))),
        ranking=RankingSelection(configuration=ranking),
    )

    assert sorted(row["position"] for row in page.rows) == [1000, 2000]


async def test_two_ranking_sources_at_once_are_refused(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    with pytest.raises(ValidationError):
        await run(
            services,
            harness,
            user_id,
            result_set,
            ranking=RankingSelection(
                configuration={
                    "method_id": "field_order",
                    "method_version": "1.0.0",
                    "components": [],
                },
                ranking_preset_id="rpr_missing",
            ),
        )
