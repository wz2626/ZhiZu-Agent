"""Deterministic progress and weight boundaries (entirely offline)."""

import pytest

from backend.app.services.scoring import (
    ScoringRule, calculate_score, default_scoring_rules, progress, score_item,
)


@pytest.mark.parametrize("confirmed,expected", [
    (-100, 0), (0, 0), (1000, 50), (1500, 75), (2000, 100), (3000, 100),
])
def test_deposit_formula_and_clipping(confirmed, expected):
    assert score_item(confirmed, 0, 2000) == expected
    assert calculate_score({"deposit_refund": confirmed}, default_scoring_rules()) == expected


@pytest.mark.parametrize("confirmed,expected", [(15, 0), (10, 0), (5, 50), (0, 100), (-2, 100)])
def test_decreasing_target(confirmed, expected):
    assert score_item(confirmed, 10, 0) == expected


@pytest.mark.parametrize("confirmed", [-1, 0, 1, 2000])
def test_equal_target_and_start_is_inapplicable(confirmed):
    assert progress(confirmed, 0, 0) is None
    assert score_item(confirmed, 0, 0) is None
    assert calculate_score({"same": confirmed}, {"same": ScoringRule(0, 0)}) is None


@pytest.mark.parametrize("confirmed,expected", [(1, 0), (3, 2), (5, 2), (7, 4)])
def test_half_even_rounding_is_explicit(confirmed, expected):
    assert score_item(confirmed, 0, 200) == expected


@pytest.mark.parametrize("scale", [0.001, 1, 100, 1e308])
def test_weight_normalization_is_scale_invariant(scale):
    rules = {"a": ScoringRule(0, 100, weight=scale), "b": ScoringRule(0, 100, weight=scale)}
    assert calculate_score({"a": 100, "b": 0}, rules) == 50


def test_unequal_weights_and_decreasing_goal():
    rules = {"a": ScoringRule(0, 2000, weight=1), "b": ScoringRule(10, 0, weight=3)}
    assert calculate_score({"a": 2000, "b": 10}, rules) == 25
    assert calculate_score({"a": 1000, "b": 5}, rules) == 50


def test_aggregate_unrounded_progress_before_rounding():
    rules = {"a": ScoringRule(0, 1000), "b": ScoringRule(0, 1000)}
    # Individual values round to 0 and 1; their raw mean is 0.6 -> 1.
    assert calculate_score({"a": 4, "b": 8}, rules) == 1


@pytest.mark.parametrize("weight", [0, -1, float("nan"), float("inf"), True, "1"])
def test_invalid_weights_do_not_enter_denominator(weight):
    rules = {"a": ScoringRule(0, 100), "b": ScoringRule(0, 100, weight=weight)}
    assert calculate_score({"a": 50, "b": 100}, rules) == 50
    assert calculate_score({"b": 100}, rules) is None


def test_missing_disabled_and_degenerate_rules_do_not_enter_denominator():
    rules = {
        "valid": ScoringRule(0, 100), "missing": ScoringRule(0, 100, weight=99),
        "disabled": ScoringRule(0, 100, weight=99, applicable=False),
        "equal": ScoringRule(100, 100, weight=99),
    }
    terms = {"valid": 50, "disabled": 0, "equal": 100, "unknown": 100}
    assert calculate_score(terms, rules) == 50


@pytest.mark.parametrize("terms,rules", [({}, {}), ({}, default_scoring_rules()), ({"unknown": 2000}, default_scoring_rules())])
def test_no_applicable_items_is_unscorable(terms, rules):
    assert calculate_score(terms, rules) is None


@pytest.mark.parametrize("invalid", [True, "1000", None, float("nan"), float("inf"), float("-inf")])
def test_invalid_values_are_rejected(invalid):
    with pytest.raises(ValueError, match="finite numeric"):
        score_item(invalid, 0, 2000)
    assert not ScoringRule(0, 2000).accepts(invalid)


def test_same_state_same_score_and_inputs_are_not_mutated():
    rules = default_scoring_rules()
    terms = {"deposit_refund": 1000, "evidence_ids": ["LAW-709", "LAW-709"]}
    assert [calculate_score(terms, rules) for _ in range(10)] == [50] * 10
    assert terms == {"deposit_refund": 1000, "evidence_ids": ["LAW-709", "LAW-709"]}


def test_fractional_amount_and_large_numbers_do_not_overflow():
    assert score_item(0.3, 0.1, 0.5) == 50
    assert score_item(10**400, 0, 2 * 10**400) == 50


@pytest.mark.parametrize("value,expected", [(-1, False), (0, True), (1000, True), (2000, True), (2001, False)])
def test_configured_bottom_lines_are_inclusive(value, expected):
    assert default_scoring_rules()["deposit_refund"].accepts(value) is expected


def test_invalid_rule_configuration_is_rejected():
    with pytest.raises(ValueError):
        ScoringRule(float("nan"), 2000)
    with pytest.raises(ValueError):
        ScoringRule(0, 2000, minimum=1500, maximum=1000)
