"""Unit-level guarantees of the prioritization domain.

Ranking is deliberately dull: a declared transformation of recorded fields,
declared weights, a declared direction and declared tie-breakers. These tests
assert exactly that — a stated arithmetic with a total order — and that nothing
about the method infers, predicts or concludes anything scientific.
"""

from __future__ import annotations

import pytest

from app.domain.errors import ValidationError
from app.domain.query.fields import DEFAULT_FIELD_REGISTRY
from app.domain.query.ranking import (
    RANKING_METHOD_REGISTRY,
    RankingComponent,
    RankingComponentKind,
    RankingConfigurationSpec,
    RankingDirection,
    RankingMissingBehaviour,
    canonical_ranking_hash,
    prioritize_row,
    ranking_sort_key,
    spec_from_payload,
    validate_ranking,
)

REGISTRY = DEFAULT_FIELD_REGISTRY


def frequency_component(**overrides) -> RankingComponent:
    values: dict = {
        "field_id": "allele_frequency",
        "kind": RankingComponentKind.NUMERIC_ASCENDING,
        "weight": 1.0,
        "scale_min": 0.0,
        "scale_max": 0.01,
    }
    values.update(overrides)
    return RankingComponent(**values)


def spec(*components: RankingComponent, **overrides) -> RankingConfigurationSpec:
    values: dict = {
        "method_id": "weighted_field_score",
        "method_version": "1.0.0",
        "components": components or (frequency_component(),),
    }
    values.update(overrides)
    return RankingConfigurationSpec(**values)


def row(**values) -> dict:
    base = {
        "contig": "chr1",
        "position": 1000,
        "reference_allele": "A",
        "alternate_allele": "T",
        "allele_frequency": None,
        "consequence_term": None,
        "read_depth": None,
    }
    base.update(values)
    return base


class TestRegistry:
    def test_every_shipped_method_is_prioritization_only(self) -> None:
        for method in RANKING_METHOD_REGISTRY.available_methods():
            assert method.deterministic
            # A method claiming scientific validity would need its own validation
            # and governance, which is outside this package by design.
            assert method.scientifically_validated is False

    def test_an_unknown_method_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_ranking(spec(method_id="pathogenicity_oracle"), registry=REGISTRY)

    def test_a_configuration_written_for_another_version_is_refused(self) -> None:
        with pytest.raises(ValidationError) as error:
            validate_ranking(spec(method_version="0.9.0"), registry=REGISTRY)
        assert "method_version_mismatch" in str(error.value.details)

    def test_an_unsupported_parameter_is_refused(self) -> None:
        with pytest.raises(ValidationError) as error:
            validate_ranking(spec(parameters={"boost_pathogenic": True}), registry=REGISTRY)
        assert "unsupported_parameters" in str(error.value.details)

    def test_a_component_naming_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_ranking(
                spec(frequency_component(field_id="pathogenicity_score")), registry=REGISTRY
            )

    def test_a_numeric_component_without_a_declared_scale_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_ranking(
                spec(frequency_component(scale_min=None, scale_max=None)), registry=REGISTRY
            )

    def test_a_field_absent_from_the_surface_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_ranking(
                spec(),
                registry=REGISTRY,
                available_field_ids=frozenset({"contig", "position"}),
            )

    def test_a_validated_configuration_carries_a_canonical_hash(self) -> None:
        validated = validate_ranking(spec(), registry=REGISTRY)
        assert validated.canonical_hash.startswith("sha256:")
        assert validated.field_ids == ("allele_frequency",)


class TestScoring:
    def test_a_rarer_value_scores_higher_on_an_ascending_component(self) -> None:
        configuration = spec()
        rare = prioritize_row(configuration, row(allele_frequency=0.0001), registry=REGISTRY)
        common = prioritize_row(configuration, row(allele_frequency=0.009), registry=REGISTRY)
        assert rare.score is not None and common.score is not None
        assert rare.score > common.score

    def test_a_value_beyond_the_declared_scale_is_clamped_not_extrapolated(self) -> None:
        configuration = spec()
        beyond = prioritize_row(configuration, row(allele_frequency=0.9), registry=REGISTRY)
        at_bound = prioritize_row(configuration, row(allele_frequency=0.01), registry=REGISTRY)
        assert beyond.score == at_bound.score

    def test_a_never_reported_value_is_not_scored_as_zero(self) -> None:
        configuration = spec()
        missing = prioritize_row(configuration, row(allele_frequency=None), registry=REGISTRY)
        reported_zero = prioritize_row(configuration, row(allele_frequency=0.0), registry=REGISTRY)

        # Absent means no score at all; a reported zero is a value and scores.
        assert missing.score is None
        assert missing.missing_field_ids == ("allele_frequency",)
        assert reported_zero.score == pytest.approx(1.0)

    def test_a_declared_floor_is_applied_only_when_the_author_asked(self) -> None:
        configuration = spec(
            frequency_component(
                missing_behaviour=RankingMissingBehaviour.FLOOR, missing_floor=0.25
            )
        )
        scored = prioritize_row(configuration, row(allele_frequency=None), registry=REGISTRY)
        assert scored.score == pytest.approx(0.25)
        # The row is still reported as missing that input, so the gap is visible.
        assert scored.missing_field_ids == ("allele_frequency",)

    def test_a_category_order_comes_from_the_configuration_alone(self) -> None:
        configuration = spec(
            RankingComponent(
                field_id="consequence_term",
                kind=RankingComponentKind.CATEGORY_PRIORITY,
                weight=1.0,
                category_priority=("stop_gained", "missense_variant", "synonymous_variant"),
            )
        )
        first = prioritize_row(
            configuration, row(consequence_term="stop_gained"), registry=REGISTRY
        )
        last = prioritize_row(
            configuration, row(consequence_term="synonymous_variant"), registry=REGISTRY
        )
        unlisted = prioritize_row(
            configuration, row(consequence_term="intron_variant"), registry=REGISTRY
        )
        assert first.score is not None and last.score is not None
        assert first.score > last.score
        # A term the author never ranked is treated as an input the configuration
        # cannot score, not as a low value guessed into the order.
        assert unlisted.score is None
        assert unlisted.missing_field_ids == ("consequence_term",)

    def test_weights_are_applied_exactly_as_declared(self) -> None:
        configuration = spec(
            frequency_component(weight=0.4),
            RankingComponent(
                field_id="read_depth",
                kind=RankingComponentKind.NUMERIC_DESCENDING,
                weight=0.6,
                scale_min=0.0,
                scale_max=100.0,
            ),
        )
        scored = prioritize_row(
            configuration, row(allele_frequency=0.0, read_depth=50), registry=REGISTRY
        )
        assert scored.score == pytest.approx(0.4 * 1.0 + 0.6 * 0.5)

    def test_the_same_row_and_configuration_always_produce_the_same_score(self) -> None:
        configuration = spec()
        sample = row(allele_frequency=0.002)
        scores = {
            prioritize_row(configuration, sample, registry=REGISTRY).score for _ in range(5)
        }
        assert len(scores) == 1


class TestOrdering:
    def test_an_unscored_row_sorts_last_in_both_directions(self) -> None:
        for direction in (RankingDirection.DESCENDING, RankingDirection.ASCENDING):
            configuration = spec(direction=direction)
            rows = [row(allele_frequency=None), row(allele_frequency=0.001)]
            ordered = sorted(
                rows,
                key=lambda candidate: ranking_sort_key(
                    prioritize_row(configuration, candidate, registry=REGISTRY),
                    candidate,
                    configuration,
                    registry=REGISTRY,
                ),
            )
            assert ordered[-1]["allele_frequency"] is None

    def test_equal_scores_are_broken_by_the_declared_tie_breakers(self) -> None:
        configuration = spec()
        rows = [
            row(position=3000, allele_frequency=0.001),
            row(position=1000, allele_frequency=0.001),
            row(position=2000, allele_frequency=0.001),
        ]
        ordered = sorted(
            rows,
            key=lambda candidate: ranking_sort_key(
                prioritize_row(configuration, candidate, registry=REGISTRY),
                candidate,
                configuration,
                registry=REGISTRY,
            ),
        )
        assert [candidate["position"] for candidate in ordered] == [1000, 2000, 3000]

    def test_direction_reverses_the_score_order_only(self) -> None:
        rows = [row(allele_frequency=0.009), row(allele_frequency=0.0001)]
        descending = sorted(
            rows,
            key=lambda candidate: ranking_sort_key(
                prioritize_row(spec(), candidate, registry=REGISTRY),
                candidate,
                spec(),
                registry=REGISTRY,
            ),
        )
        ascending_spec = spec(direction=RankingDirection.ASCENDING)
        ascending = sorted(
            rows,
            key=lambda candidate: ranking_sort_key(
                prioritize_row(ascending_spec, candidate, registry=REGISTRY),
                candidate,
                ascending_spec,
                registry=REGISTRY,
            ),
        )
        assert descending == list(reversed(ascending))


class TestSerialization:
    def test_a_payload_round_trips_without_changing_its_hash(self) -> None:
        configuration = spec()
        payload = configuration.to_payload()
        restored = spec_from_payload(payload)
        assert canonical_ranking_hash(payload) == canonical_ranking_hash(restored.to_payload())

    def test_a_filter_expression_is_not_accepted_as_a_ranking(self) -> None:
        with pytest.raises(ValidationError):
            spec_from_payload({"kind": "group", "operator": "and", "children": []})

    def test_an_unknown_key_in_a_component_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            spec_from_payload(
                {
                    "method_id": "weighted_field_score",
                    "method_version": "1.0.0",
                    "components": [
                        {
                            "field_id": "allele_frequency",
                            "kind": "numeric_ascending",
                            "weight": 1.0,
                            "operator": "less_than",
                        }
                    ],
                }
            )
