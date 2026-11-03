"""Privacy regressions for decoded negotiation drafts and cached failures."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.services import negotiation_graph as graph_module
from backend.app.services.negotiation_service import NegotiationService


PHONE = "138\t0000\t0147"  # Synthetic; tabs are supported by the shared masker.


@pytest.mark.parametrize("location", ["coach", "landlord", "arrangement", "term_key"])
def test_tab_separated_phone_cannot_commit_or_escape_failure_cache(monkeypatch, location):
    calls = []

    def coach(state):
        return {"coach_advice": f"请联系{PHONE}。" if location == "coach" else "请说明诉求。"}

    def landlord(state):
        calls.append(state.retry_count)
        if location == "landlord":
            return {"landlord_response": f"【模拟房东】请联系{PHONE}。", "candidate_terms": {}}
        if location in {"arrangement", "term_key"}:
            arrangement = f"请联系{PHONE}" if location == "arrangement" else "明天核对交接记录"
            key = PHONE if location == "term_key" else "handover"
            return {
                "landlord_response": f"【模拟房东】确认本轮安排：{arrangement}",
                "candidate_terms": {key: {"arrangement": [arrangement]}},
                "landlord_confirmed": True,
            }
        return {
            "landlord_response": "【模拟房东】我确认返还押金1000元。",
            "candidate_terms": {"deposit_refund": 1000},
            "landlord_confirmed": True,
        }

    monkeypatch.setattr(graph_module, "tenant_coach_node", coach)
    monkeypatch.setattr(graph_module, "landlord_node", landlord)
    service = NegotiationService(graph_module.build_negotiation_graph(), public_api=True)
    before = service.get_session("privacy-session")
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(
            lambda _: service.negotiate_with_effect("privacy-session", "核对押金返还安排", request_id="same"),
            range(4),
        ))

    assert calls == [0, 1, 2]
    assert service.get_session("privacy-session") == before
    assert sum(not response.state.replayed for response in responses) == 1
    for response in responses:
        state = response.state
        assert state.status == "needs_review"
        assert state.round_count == 0 and state.trial_score is None
        assert state.confirmed_terms == {} and state.history == []
        assert state.coach_advice == "" and state.landlord_response == ""
        assert state.candidate_terms == {} and state.candidate_score is None
        assert response.turn_effect.kind == "not_committed"
        assert response.turn_effect.changes == []
        assert PHONE not in str(state.model_dump())
        assert "138\\t0000\\t0147" not in state.model_dump_json()
        assert "138" not in " ".join(state.errors)


def test_valid_arrangement_preserves_tabs_and_detached_cached_snapshot(monkeypatch):
    arrangement = "周五\t核对水电与交接记录"
    monkeypatch.setattr(graph_module, "landlord_node", lambda state: {
        "landlord_response": f"【模拟房东】确认本轮安排：{arrangement}",
        "candidate_terms": {"round_1": {"arrangement": [arrangement]}},
        "landlord_confirmed": True,
    })
    service = NegotiationService(graph_module.build_negotiation_graph(), public_api=True)
    response = service.negotiate_with_effect("safe-session", "核对交接安排", request_id="same")
    assert response.state.status == "success" and response.state.round_count == 1
    assert response.state.confirmed_terms == {"round_1": {"arrangement": [arrangement]}}
    response.state.confirmed_terms["round_1"]["arrangement"].clear()
    replay = service.negotiate_with_effect("safe-session", "核对交接安排", request_id="same")
    assert replay.state.replayed and replay.state.round_count == 1
    assert replay.state.confirmed_terms == {"round_1": {"arrangement": [arrangement]}}
