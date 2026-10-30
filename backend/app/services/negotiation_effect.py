"""Compare committed terms against the same trusted rules used for scoring."""

from copy import deepcopy
from fractions import Fraction
from math import isfinite

from backend.app.schemas.negotiation import (
    NegotiationState, NegotiationTermChange, NegotiationTurnEffect,
)
from backend.app.services.scoring import ScoringRule, progress


def _direction(before: object, after: object, rule: ScoringRule | None) -> str:
    if rule is None or not rule.applicable or rule.start == rule.target:
        return "adjusted"
    weight = rule.weight
    if (isinstance(weight, bool) or not isinstance(weight, (int, float))
            or (isinstance(weight, float) and not isfinite(weight)) or Fraction(str(weight)) <= 0):
        return "adjusted"
    # Invalid values are rejected by the critic before this comparison. Do not
    # reinterpret a malformed known numeric term as a harmless visual change.
    if not rule.accepts(before) or not rule.accepts(after):
        raise ValueError("cannot compare invalid confirmed values")
    old, new = progress(before, rule.start, rule.target), progress(after, rule.start, rule.target)
    if new > old:
        return "improved"
    if new < old:
        return "worsened"
    return "adjusted"


def describe_turn(
    before: NegotiationState, after: NegotiationState, *, round_limit: bool = False,
) -> NegotiationTurnEffect:
    """Called under the session lock before replacing the official snapshot."""
    if round_limit or after.status not in {"success", "completed"}:
        return NegotiationTurnEffect(
            kind="round_limit" if round_limit else "not_committed",
            score_before=before.trial_score, score_after=before.trial_score,
            score_delta=None, changes=[],
        )
    if not before.confirmed_terms.keys() <= after.confirmed_terms.keys():
        raise ValueError("a committed turn cannot silently remove confirmed terms")
    changes = []
    for term, value in after.confirmed_terms.items():
        if term not in before.confirmed_terms:
            changes.append(NegotiationTermChange(
                term=term, change_type="added", before=None, after=deepcopy(value), direction="adjusted",
            ))
        elif before.confirmed_terms[term] != value:
            changes.append(NegotiationTermChange(
                term=term, change_type="updated", before=deepcopy(before.confirmed_terms[term]),
                after=deepcopy(value), direction=_direction(before.confirmed_terms[term], value,
                                                          before.scoring_rules.get(term)),
            ))
    if not changes:
        kind = "unchanged"
    elif not before.confirmed_terms:
        kind = "first_confirmation"
    else:
        directions = {change.direction for change in changes}
        kind = next(iter(directions)) if len(directions) == 1 else "adjusted"
    return NegotiationTurnEffect(
        kind=kind, score_before=before.trial_score, score_after=after.trial_score,
        score_delta=(after.trial_score - before.trial_score
                     if before.trial_score is not None and after.trial_score is not None else None),
        changes=changes,
    )
