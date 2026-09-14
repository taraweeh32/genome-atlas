"""Filtering, ranking, saved view and variant query use cases.

Filtering and ranking are two independent capabilities that meet only in the
execution pipeline, and this package keeps them that way: separate registries,
separate definitions, separate permissions, separate execution records. A ranking
can never reintroduce a row the filter excluded, and a filter never produces a
score.
"""

from app.application.use_cases.query.definitions import (
    FilterPresetService,
    RankingPresetService,
    SavedFilterService,
    SavedRankingService,
    ValidateFilterExpression,
)
from app.application.use_cases.query.dependencies import QueryServices
from app.application.use_cases.query.execution import ExecuteVariantQuery
from app.application.use_cases.query.fields import (
    DescribeFilterFields,
    GetFilterField,
    SearchFieldValues,
)
from app.application.use_cases.query.views import SavedViewService

__all__ = [
    "DescribeFilterFields",
    "ExecuteVariantQuery",
    "FilterPresetService",
    "GetFilterField",
    "QueryServices",
    "RankingPresetService",
    "SavedFilterService",
    "SavedRankingService",
    "SavedViewService",
    "SearchFieldValues",
    "ValidateFilterExpression",
]
