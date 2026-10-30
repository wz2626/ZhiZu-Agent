"""V3 factual turn comparisons and their atomic, request-scoped replay."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.negotiation import get_negotiation_service
from backend.app.main import app
from backend.app.schemas.negotiation import NegotiationState, NegotiationTurnEffect
from backend.app.services.negotiation_effect import describe_turn
from backend.app.services.negotiation_graph import build_negotiation_graph, scenario_landlord_responder
from backend.app.services.negotiation_service import NegotiationConflict, NegotiationService
from backend.app.services.scoring import ScoringRule, calculate_score


def snapshots(before, after, rules):
    initial = NegotiationState(
        session_id="comparison", confirmed_terms=before, scoring_rules=rules,
        trial_score=calculate_score(before, rules), round_count=1,
    )
    final = initial.model_copy(deep=True, update={
        "confirmed_terms": after, "trial_score": calculate_score(after, rules),
        "round_count": 2, "status": "success",
    })
    return initial, final


def practice_service(responder=scenario_landlord_responder):
    return NegotiationService(build_negotiation_graph(landlord_responder=responder), public_api=True)


@pytest.mark.parametrize("term,before,after,rule,direction", [
    ("deposit_refund", 1000, 1500, ScoringRule(0, 2000), "improved"),
    ("deposit_refund", 1500, 1000, ScoringRule(0, 2000), "worsened"),
    ("termination_fee", 1000, 500, ScoringRule(2000, 0), "improved"),
    ("termination_fee", 500, 1000, ScoringRule(2000, 0), "worsened"),
    ("repair_cost_share", 50, 75, ScoringRule(0, 100), "improved"),
    ("repair_cost_share", 75, 50, ScoringRule(0, 100), "worsened"),
])
def test_direction_follows_trusted_target_not_raw_amount(term, before, after, rule, direction):
    old, new = snapshots({term: before}, {term: after}, {term: rule})
    effect = describe_turn(old, new)
    assert effect.kind == effect.changes[0].direction == direction
    assert effect.changes[0].before == before and effect.changes[0].after == after
    assert effect.changes[0].change_type == "updated"
    assert effect.score_delta == (25 if direction == "improved" else -25)


def test_direction_uses_unrounded_progress_even_when_integer_score_is_unchanged():
    old, new = snapshots({"amount": 1000}, {"amount": 1001}, {"amount": ScoringRule(0, 10000)})
    effect = describe_turn(old, new)
    assert effect.score_before == effect.score_after == 10 and effect.score_delta == 0
    assert effect.kind == effect.changes[0].direction == "improved"


@pytest.mark.parametrize("before,after", [(120, 150), (-20, -10)])
def test_changes_outside_target_interval_do_not_claim_extra_scored_progress(before, after):
    old, new = snapshots({"amount": before}, {"amount": after}, {"amount": ScoringRule(0, 100)})
    effect = describe_turn(old, new)
    assert effect.kind == effect.changes[0].direction == "adjusted" and effect.score_delta == 0


@pytest.mark.parametrize("rule", [
    ScoringRule(0, 100, applicable=False), ScoringRule(0, 0),
    ScoringRule(0, 100, weight=0), ScoringRule(0, 100, weight=-1),
    ScoringRule(0, 100, weight=True), ScoringRule(0, 100, weight="1"),
    ScoringRule(0, 100, weight=float("nan")), ScoringRule(0, 100, weight=float("inf")),
])
def test_inapplicable_items_remain_adjustments_without_invented_score(rule):
    old, new = snapshots({"amount": 25}, {"amount": 50}, {"amount": rule})
    effect = describe_turn(old, new)
    assert effect.kind == "adjusted" and effect.changes[0].direction == "adjusted"
    assert effect.score_before is effect.score_after is effect.score_delta is None


def test_first_confirmation_has_no_invented_previous_value_or_delta():
    old, new = snapshots({}, {"deposit_refund": 1000}, {"deposit_refund": ScoringRule(0, 2000)})
    effect = describe_turn(old, new)
    assert effect.kind == "first_confirmation"
    assert effect.score_before is None and effect.score_after == 50 and effect.score_delta is None
    assert effect.changes[0].model_dump() == {
        "term": "deposit_refund", "change_type": "added", "before": None,
        "after": 1000, "direction": "adjusted",
    }


def test_new_scored_item_does_not_turn_total_score_drop_into_inferred_setback():
    rules = {"a": ScoringRule(0, 100), "b": ScoringRule(0, 100)}
    old, new = snapshots({"a": 100}, {"a": 100, "b": 0}, rules)
    effect = describe_turn(old, new)
    assert effect.kind == "adjusted" and effect.score_delta == -50
    assert effect.changes[0].term == "b" and effect.changes[0].change_type == "added"


def test_mixed_changes_do_not_hide_a_worsened_term_behind_positive_total_score():
    rules = {"a": ScoringRule(0, 100), "b": ScoringRule(0, 100)}
    old, new = snapshots({"a": 25, "b": 75}, {"a": 100, "b": 50}, rules)
    effect = describe_turn(old, new)
    assert effect.kind == "adjusted" and effect.score_delta == 25
    assert [change.direction for change in effect.changes] == ["improved", "worsened"]


def test_non_numeric_arrangement_change_is_reported_without_scoring_it():
    old, new = snapshots({"handover": {"arrangement": ["周一"]}}, {"handover": {"arrangement": ["周二"]}}, {})
    effect = describe_turn(old, new)
    assert effect.kind == "adjusted" and effect.score_delta is None
    assert effect.changes[0].before == {"arrangement": ["周一"]}
    effect.changes[0].after["arrangement"].append("仅污染返回对象")
    assert new.confirmed_terms == {"handover": {"arrangement": ["周二"]}}


@pytest.mark.parametrize("terms,rules", [({}, {}), ({"deposit_refund": 2000}, {"deposit_refund": ScoringRule(0, 2000)})])
def test_unchanged_terms_have_no_changes_even_at_target(terms, rules):
    old, new = snapshots(terms, terms.copy(), rules)
    effect = describe_turn(old, new)
    assert effect.kind == "unchanged" and effect.changes == []


def test_silent_removal_is_not_presented_as_an_unchanged_success():
    old, new = snapshots({"a": 1}, {}, {})
    with pytest.raises(ValueError, match="remove"):
        describe_turn(old, new)


def test_failed_comparison_cannot_publish_candidate_changes_or_score():
    old, new = snapshots({"deposit_refund": 1000}, {"deposit_refund": 2000}, {"deposit_refund": ScoringRule(0, 2000)})
    new.status = "needs_review"
    effect = describe_turn(old, new)
    assert effect.kind == "not_committed" and effect.changes == [] and effect.score_delta is None
    assert effect.score_before == effect.score_after == 50


def test_each_request_keeps_original_baseline_after_later_rounds_and_detaches_results():
    service = practice_service()
    first = service.negotiate_with_effect("A", "请求", request_id="r1")
    second = service.negotiate_with_effect("A", "请求", request_id="r2")
    assert first.turn_effect.kind == "first_confirmation"
    assert second.turn_effect.kind == "improved" and second.turn_effect.score_delta == 25
    second.turn_effect.changes.clear()
    second.state.confirmed_terms.clear()
    replay = service.negotiate_with_effect("A", "请求", request_id="r1")
    assert replay.state.replayed and replay.state.round_count == 1
    assert replay.turn_effect == first.turn_effect
    replay2 = service.negotiate_with_effect("A", "请求", request_id="r2")
    assert replay2.turn_effect.changes[0].before == 1000
    assert replay2.turn_effect.changes[0].after == 1500
    assert service.get_session("A").round_count == 2
    assert service.get_session("A").confirmed_terms == {"deposit_refund": 1500}
    with pytest.raises(NegotiationConflict):
        service.negotiate_with_effect("A", "不同请求", request_id="r1")


def test_round_limit_returns_new_request_outcome_without_reusing_last_round_delta():
    service = practice_service()
    results = [service.negotiate_with_effect("A", "请求", request_id=f"r{n}") for n in range(1, 6)]
    assert [result.turn_effect.kind for result in results] == [
        "first_confirmation", "improved", "improved", "unchanged", "unchanged",
    ]
    before = service.get_session("A")
    sixth = service.negotiate_with_effect("A", "请求", request_id="r6")
    assert sixth.state.request_id == "r6" and sixth.state.trace == []
    assert sixth.turn_effect.kind == "round_limit" and sixth.turn_effect.score_delta is None
    assert sixth.turn_effect.score_before == sixth.turn_effect.score_after == 100
    assert sixth.turn_effect.changes == [] and service.get_session("A") == before
    assert service.negotiate_with_effect("A", "请求", request_id="r6").turn_effect == sixth.turn_effect


def test_failure_keeps_old_state_and_cached_failure_effect_even_after_next_success():
    calls = []
    def responder(state):
        calls.append(state.request_id)
        return "【模拟房东】隐私13800000000" if state.request_id == "bad" else scenario_landlord_responder(state)
    service = practice_service(responder)
    service.negotiate_with_effect("A", "请求", request_id="first")
    before = service.get_session("A")
    failed = service.negotiate_with_effect("A", "请求", request_id="bad")
    assert service.get_session("A") == before
    assert failed.turn_effect.kind == "not_committed" and failed.turn_effect.changes == []
    assert failed.turn_effect.score_before == failed.turn_effect.score_after == 50
    assert "13800000000" not in str(failed)
    service.negotiate_with_effect("A", "请求", request_id="next")
    replay = service.negotiate_with_effect("A", "请求", request_id="bad")
    assert replay.state.replayed and replay.turn_effect == failed.turn_effect
    assert calls.count("bad") == 3 and service.get_session("A").trial_score == 75


def test_concurrent_duplicate_turns_share_one_effect_and_sessions_are_isolated():
    calls = []
    def responder(state):
        calls.append(state.session_id)
        return scenario_landlord_responder(state)
    service = practice_service(responder)
    def run(sid):
        return service.negotiate_with_effect(sid, "请求", request_id="same")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, ["A", "B"] * 4))
    assert calls.count("A") == calls.count("B") == 1
    assert all(result.turn_effect.kind == "first_confirmation" for result in results)
    assert all(result.turn_effect.score_delta is None for result in results)
    assert sum(not result.state.replayed for result in results) == 2


def test_http_response_publishes_effect_and_replay_uses_request_snapshot():
    service = practice_service()
    app.dependency_overrides[get_negotiation_service] = lambda: service
    def post(client, rid):
        return client.post("/api/negotiation/turn", json={
            "session_id": "http-effect", "request_id": rid, "user_input": "请核对条件。",
        })
    try:
        with TestClient(app) as client:
            first = post(client, "r1").json()
            second = post(client, "r2").json()
            replay = post(client, "r1").json()
        assert first["turn_effect"]["kind"] == "first_confirmation"
        assert second["turn_effect"]["kind"] == "improved"
        assert second["turn_effect"]["changes"][0]["direction"] == "improved"
        assert replay["turn_effect"] == first["turn_effect"] and replay["round_count"] == 1
        assert replay["replayed"] is True
    finally:
        app.dependency_overrides.pop(get_negotiation_service, None)


@pytest.mark.parametrize("update", [
    {"score_delta": 1}, {"score_delta": True}, {"stance": "strong"},
    {"kind": "not_committed", "score_delta": 0},
])
def test_effect_schema_rejects_inconsistent_or_invented_metrics(update):
    data = dict(kind="unchanged", score_before=50, score_after=50, score_delta=0, changes=[])
    with pytest.raises(ValidationError):
        NegotiationTurnEffect(**{**data, **update})
