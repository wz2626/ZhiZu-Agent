"""Pure deterministic progress rules; no model, graph or network dependencies."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite

Number = int | float


def _number(value: object) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite numeric value")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("expected a finite numeric value")
    return Fraction(str(value))


@dataclass(frozen=True)
class ScoringRule:
    start: Number
    target: Number
    weight: Number = 1
    applicable: bool = True
    minimum: Number | None = None
    maximum: Number | None = None

    def __post_init__(self) -> None:
        _number(self.start)
        _number(self.target)
        if self.minimum is not None:
            _number(self.minimum)
        if self.maximum is not None:
            _number(self.maximum)
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("minimum must not exceed maximum")

    def accepts(self, value: object) -> bool:
        try:
            number = _number(value)
        except ValueError:
            return False
        return (
            (self.minimum is None or number >= _number(self.minimum))
            and (self.maximum is None or number <= _number(self.maximum))
        )


def default_scoring_rules() -> dict[str, ScoringRule]:
    return {"deposit_refund": ScoringRule(0, 2000, minimum=0, maximum=2000)}


def scenario_scoring_rules(scenario: str) -> dict[str, ScoringRule]:
    if scenario == "deposit":
        return default_scoring_rules()
    if scenario == "maintenance":
        return {"repair_cost_share": ScoringRule(0, 100, minimum=0, maximum=100)}
    if scenario == "early_termination":
        return {"termination_fee": ScoringRule(2000, 0, minimum=0, maximum=2000)}
    raise ValueError("unknown negotiation scenario")


def progress(confirmed: Number, start: Number, target: Number) -> Fraction | None:
    """Equal start and target is inapplicable, even when already achieved."""
    value, initial, goal = _number(confirmed), _number(start), _number(target)
    if goal == initial:
        return None
    return max(Fraction(0), min(Fraction(1), (value - initial) / (goal - initial)))


def score_item(confirmed: Number, start: Number, target: Number) -> int | None:
    value = progress(confirmed, start, target)
    return None if value is None else round(100 * value)


def calculate_score(
    confirmed_terms: Mapping[str, object], rules: Mapping[str, ScoringRule],
) -> int | None:
    weighted_progress, total_weight = Fraction(0), Fraction(0)
    for key, rule in rules.items():
        if not rule.applicable or key not in confirmed_terms:
            continue
        try:
            weight = _number(rule.weight)
        except ValueError:
            continue
        if weight <= 0 or rule.target == rule.start:
            continue
        value = progress(confirmed_terms[key], rule.start, rule.target)
        weighted_progress += weight * value
        total_weight += weight
    return None if not total_weight else round(100 * weighted_progress / total_weight)


def explain_score(score: int | None) -> str:
    if score is None:
        return "模拟协商进展分：不可评分（无适用的已确认数值项）。"
    return f"模拟协商进展分：{score}；按已确认条件的适用权重归一化计算。"
