"""Unit-level guarantees of the filter domain: parsing, validation, canonical form.

These tests touch no database, no engine and no HTTP layer. They exist because
the properties asserted here — a type-aware operator set, a value that keeps its
declared type, an expression that is refused rather than repaired, a canonical
form that two equivalent expressions agree on — are the foundation every higher
layer depends on for reproducibility.
"""

from __future__ import annotations

import pytest

from app.domain.errors import ValidationError
from app.domain.query.canonical import canonical_hash, canonical_payload, canonicalize
from app.domain.query.expressions import (
    group_from_payload,
    iter_conditions,
    node_count,
    node_depth,
)
from app.domain.query.fields import DEFAULT_FIELD_REGISTRY, FIELD_DICTIONARY_VERSION
from app.domain.query.operators import FilterDataType, FilterOperator, operators_for
from app.domain.query.validation import (
    FilterLimits,
    combine_expressions,
    validate_filter,
)
from tests.query.support import condition, group

REGISTRY = DEFAULT_FIELD_REGISTRY


def validated(payload: dict, **kwargs):
    return validate_filter(group_from_payload(payload), registry=REGISTRY, **kwargs)


def issues(error: ValidationError) -> list[dict]:
    return list(error.details.get("issues", ()))


def codes(error: ValidationError) -> set[str]:
    return {issue["code"] for issue in issues(error)}


class TestStructuralParsing:
    def test_a_bare_condition_is_wrapped_rather_than_rejected(self) -> None:
        node = group_from_payload(condition("gene_symbol", "equals", "CFTR"))
        assert node_count(node) == 2
        assert len(iter_conditions(node)) == 1

    def test_an_unknown_key_is_refused_with_its_position(self) -> None:
        payload = group(
            {
                "kind": "condition",
                "field_id": "gene_symbol",
                "operator": "equals",
                "values": ["CFTR"],
                "weight": 0.4,
            }
        )
        with pytest.raises(ValidationError) as error:
            group_from_payload(payload)
        # A weight is a ranking concept. Accepting it silently inside a filter is
        # exactly how the two would start to blur.
        assert "children[0]" in str(error.value.details)

    def test_an_unknown_operator_token_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            group_from_payload(group(condition("gene_symbol", "sounds_like", "CFTR")))

    def test_a_filter_is_never_a_string_expression(self) -> None:
        with pytest.raises(ValidationError):
            group_from_payload("gene_symbol = 'CFTR'")

    def test_nesting_depth_is_reported_as_written(self) -> None:
        payload = group(
            group(
                group(condition("contig", "equals", "chr1"), operator="or"),
                operator="and",
            )
        )
        assert node_depth(group_from_payload(payload)) == 4


class TestTypeAwareValidation:
    def test_an_unknown_field_is_reported_and_never_dropped(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(group(condition("pathogenicity_verdict", "equals", "yes")))
        assert "unknown_field" in codes(error.value)

    def test_an_operator_the_data_type_does_not_support_is_reported(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(group(condition("read_depth", "starts_with", "4")))
        assert "unsupported_operator" in codes(error.value)

    def test_a_numeric_field_keeps_a_numeric_value(self) -> None:
        result = validated(group(condition("allele_frequency", "less_than", "0.01")))
        condition_node = iter_conditions(result.expression)[0]
        assert condition_node.values == (0.01,)
        assert condition_node.value_type is FilterDataType.DECIMAL

    def test_a_value_that_is_not_of_the_declared_type_is_refused(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(group(condition("allele_frequency", "less_than", "rare")))
        assert "type_mismatch" in codes(error.value)

    def test_a_boolean_is_not_inferred_from_an_arbitrary_string(self) -> None:
        with pytest.raises(ValidationError):
            validated(group(condition("read_depth", "equals", "deep")))

    def test_a_presence_test_carries_no_value(self) -> None:
        result = validated(group(condition("allele_frequency", "is_missing")))
        assert iter_conditions(result.expression)[0].values == ()

    def test_a_presence_test_with_a_value_is_refused(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(group(condition("allele_frequency", "is_missing", 0)))
        assert "unexpected_value" in codes(error.value)

    def test_a_range_operator_needs_both_bounds(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(group(condition("position", "between", 100)))
        assert "wrong_value_count" in codes(error.value)

    def test_a_list_operator_with_no_value_is_refused(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(group(condition("gene_symbol", "in")))
        assert "wrong_value_count" in codes(error.value)

    def test_every_issue_is_reported_at_once_not_one_at_a_time(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(
                group(
                    condition("pathogenicity_verdict", "equals", "yes"),
                    condition("read_depth", "starts_with", "4"),
                )
            )
        assert len(issues(error.value)) >= 2

    def test_the_field_dictionary_version_travels_with_the_result(self) -> None:
        result = validated(group(condition("gene_symbol", "equals", "CFTR")))
        assert result.field_dictionary_version == FIELD_DICTIONARY_VERSION

    def test_a_field_absent_from_the_surface_is_refused_for_that_surface(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(
                group(condition("gene_symbol", "equals", "CFTR")),
                available_field_ids=frozenset({"contig", "position"}),
            )
        assert "field_not_in_context" in codes(error.value)


class TestResourceLimits:
    def test_an_over_deep_expression_is_refused(self) -> None:
        payload: dict = group(condition("contig", "equals", "chr1"))
        for _ in range(10):
            payload = group(payload)
        with pytest.raises(ValidationError) as error:
            validated(payload, limits=FilterLimits(max_depth=4))
        assert "too_deep" in codes(error.value)

    def test_an_enormous_value_list_is_refused(self) -> None:
        with pytest.raises(ValidationError) as error:
            validated(
                group(condition("gene_symbol", "in", *[f"G{index}" for index in range(50)])),
                limits=FilterLimits(max_values_per_condition=10),
            )
        assert "too_many_values" in codes(error.value)

    def test_too_many_text_matches_are_refused_as_the_expensive_case(self) -> None:
        children = [condition("hgvs_coding", "contains", "del") for _ in range(4)]
        with pytest.raises(ValidationError) as error:
            validated(group(*children), limits=FilterLimits(max_text_match_conditions=2))
        assert "too_many_text_matches" in codes(error.value)

    def test_too_many_conditions_are_refused(self) -> None:
        children = [condition("contig", "equals", f"chr{index}") for index in range(20)]
        with pytest.raises(ValidationError) as error:
            validated(group(*children, operator="or"), limits=FilterLimits(max_conditions=5))
        assert "too_many_conditions" in codes(error.value)


class TestCanonicalForm:
    def test_condition_order_does_not_change_the_hash(self) -> None:
        first = group_from_payload(
            group(
                condition("contig", "equals", "chr1"),
                condition("gene_symbol", "equals", "CFTR"),
            )
        )
        second = group_from_payload(
            group(
                condition("gene_symbol", "equals", "CFTR"),
                condition("contig", "equals", "chr1"),
            )
        )
        assert canonical_hash(first) == canonical_hash(second)

    def test_a_shuffled_value_list_does_not_change_the_hash(self) -> None:
        first = group_from_payload(group(condition("gene_symbol", "in", "CFTR", "ABCA4")))
        second = group_from_payload(group(condition("gene_symbol", "in", "ABCA4", "CFTR", "CFTR")))
        assert canonical_hash(first) == canonical_hash(second)

    def test_a_redundant_single_child_wrapper_collapses(self) -> None:
        wrapped = group_from_payload(group(group(condition("contig", "equals", "chr1"))))
        plain = group_from_payload(group(condition("contig", "equals", "chr1")))
        assert canonical_payload(wrapped) == canonical_payload(plain)

    def test_and_and_or_remain_different_filters(self) -> None:
        conjunction = group_from_payload(
            group(
                condition("contig", "equals", "chr1"),
                condition("gene_symbol", "equals", "CFTR"),
                operator="and",
            )
        )
        disjunction = group_from_payload(
            group(
                condition("contig", "equals", "chr1"),
                condition("gene_symbol", "equals", "CFTR"),
                operator="or",
            )
        )
        assert canonical_hash(conjunction) != canonical_hash(disjunction)

    def test_negation_survives_canonicalization_untouched(self) -> None:
        node = group_from_payload(
            group(condition("gene_symbol", "equals", "CFTR", negated=True), operator="not")
        )
        canonical = canonicalize(node)
        # No De Morgan rewriting: the tree the user saved is the tree that runs.
        assert canonical.to_payload()["operator"] == "not"
        assert canonical.to_payload()["children"][0]["negated"] is True

    def test_a_missing_test_and_an_equals_zero_are_different_filters(self) -> None:
        missing = group_from_payload(group(condition("allele_frequency", "is_missing")))
        zero = group_from_payload(group(condition("allele_frequency", "equals", 0)))
        assert canonical_hash(missing) != canonical_hash(zero)


class TestCombination:
    def test_a_preset_and_custom_conditions_both_survive_verbatim(self) -> None:
        preset = group_from_payload(group(condition("allele_frequency", "less_than", 0.01)))
        custom = group_from_payload(group(condition("gene_symbol", "in", "CFTR")))
        combined = combine_expressions(preset, custom)

        assert len(combined.children) == 2
        assert combined.children[0].to_payload() == preset.to_payload()
        assert combined.children[1].to_payload() == custom.to_payload()

    def test_an_empty_side_contributes_nothing(self) -> None:
        preset = group_from_payload(group(condition("gene_symbol", "in", "CFTR")))
        combined = combine_expressions(preset, group_from_payload(group()), None)
        assert combined.children == (preset,)

    def test_an_empty_filter_is_allowed_but_stays_empty(self) -> None:
        result = validated(group())
        assert result.is_empty
        assert result.condition_count == 0

    def test_an_empty_filter_is_refused_where_one_is_required(self) -> None:
        with pytest.raises(ValidationError):
            validated(group(), allow_empty=False)


def test_every_registered_field_publishes_only_operators_its_type_supports() -> None:
    for definition in REGISTRY.definitions:
        for operator in definition.supported_operators:
            assert isinstance(operator, FilterOperator)
            assert operator in operators_for(definition.data_type), (
                f"{definition.id} publishes {operator} which {definition.data_type} "
                "does not support"
            )
