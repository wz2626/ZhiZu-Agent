"""Offline negotiation boundaries; never import or change the review graph."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError

from backend.app.schemas.negotiation import NegotiationState
from backend.app.services import negotiation_graph as graph_module
from backend.app.services.negotiation_service import NegotiationService


def offering_landlord(state):
    return {
        "landlord_response": f"【模拟房东】确认本轮安排：{state.user_input}",
        "candidate_terms": {
            f"round_{state.round_count + 1}": {"arrangement": [state.user_input]},
        },
        "landlord_confirmed": True,
    }


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(graph_module, "landlord_node", offering_landlord)
    return NegotiationService(graph_module.build_negotiation_graph())


@pytest.mark.parametrize("round_count", [-1, 6, True, "2"])
def test_schema_rejects_invalid_round_count(round_count):
    with pytest.raises(ValidationError):
        NegotiationState(session_id="A", round_count=round_count)


def test_state_defaults_are_independent():
    first, second = NegotiationState(session_id="A"), NegotiationState(session_id="B")
    first.confirmed_terms["nested"] = {"items": [1]}
    first.candidate_terms["offer"] = 1000
    first.errors.append("failure")
    assert second.confirmed_terms == second.candidate_terms == {}
    assert second.history == second.errors == []
    assert second.trial_score is None
    with pytest.raises(ValidationError):
        second.round_count = 6


def test_default_graph_routes_three_roles_without_accepting_user_demand():
    result = NegotiationService().negotiate("A", "我要求押金全部返还2000元")
    assert result.round_count == 1 and result.status == "success"
    assert [item.role for item in result.history] == ["user", "tenant_coach", "landlord"]
    assert result.confirmed_terms == result.candidate_terms == {}
    assert result.trial_score is None and result.retry_count == 0
    assert "模拟" in result.coach_advice and "模拟" in result.landlord_response


@pytest.mark.parametrize("concurrent", [False, True])
def test_two_sessions_two_rounds_never_cross(service, concurrent):
    for round_number in (1, 2):
        inputs = [("A", f"A安排{round_number}"), ("B", f"B安排{round_number}")]
        if concurrent:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda item: service.negotiate(*item), inputs))
        else:
            results = [service.negotiate(*item) for item in inputs]
        for result, (session_id, _) in zip(results, inputs):
            assert result.session_id == session_id
            assert result.round_count == round_number
            assert [item.content for item in result.history if item.role == "user"] == [
                f"{session_id}安排{number}" for number in range(1, round_number + 1)
            ]
            assert result.confirmed_terms == {
                f"round_{number}": {"arrangement": [f"{session_id}安排{number}"]}
                for number in range(1, round_number + 1)
            }
    service.negotiate("A", "A第三轮")
    assert service.get_session("B").round_count == 2


def test_different_sessions_can_execute_graph_at_same_time(monkeypatch):
    barrier = Barrier(2)

    def landlord(state):
        barrier.wait(timeout=5)
        return offering_landlord(state)

    monkeypatch.setattr(graph_module, "landlord_node", landlord)
    service = NegotiationService(graph_module.build_negotiation_graph())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda sid: service.negotiate(sid, sid), ["A", "B"]))
    assert [result.session_id for result in results] == ["A", "B"]


def test_fifth_round_completes_and_sixth_never_runs_nodes(service):
    for number in range(1, 6):
        result = service.negotiate("A", f"安排{number}")
        assert result.round_count == number
        assert result.status == ("completed" if number == 5 else "success")
    before = service.get_session("A")
    assert service.negotiate("A", "第六次请求") == before
    assert service.get_session("A") == before
    assert len(before.history) == 15
    assert service.negotiate("B", "另一会话第一轮").round_count == 1


def test_graph_also_guards_round_limit(monkeypatch):
    def forbidden(state):
        pytest.fail("completed session must bypass all role nodes")

    monkeypatch.setattr(graph_module, "tenant_coach_node", forbidden)
    graph = graph_module.build_negotiation_graph()
    state = NegotiationState(session_id="A", round_count=5)
    result = NegotiationState.model_validate(graph.invoke(state.model_dump()))
    assert result.round_count == 5 and result.status == "completed"
    assert result.history == []


def test_same_session_concurrent_requests_stop_at_five(service):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: service.negotiate("A", f"安排{n}"), range(8)))
    final = service.get_session("A")
    assert final.round_count == 5 and final.status == "completed"
    assert len(final.history) == 15 and len(final.confirmed_terms) == 5
    assert all(result.round_count <= 5 for result in results)


def test_duplicate_requests_commit_once_and_keys_are_session_local(service):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: service.negotiate("A", "安排", request_id="same"), range(4),
        ))
    assert all(result == results[0] for result in results)
    assert service.get_session("A").round_count == 1
    assert service.negotiate("B", "B安排", request_id="same").round_count == 1
    with pytest.raises(ValueError, match="different input"):
        service.negotiate("A", "换一个输入", request_id="same")
    service.negotiate("A", "第二轮", request_id="second")
    assert service.negotiate("A", "安排", request_id="same").round_count == 1
    assert service.get_session("A").round_count == 2


def test_returned_snapshots_and_cached_responses_cannot_modify_sessions(service):
    result = service.negotiate("A", "安排", request_id="first")
    result.confirmed_terms["round_1"]["arrangement"].append("污染")
    result.history[0].content = "污染"
    snapshot = service.get_session("A")
    snapshot.confirmed_terms.clear()
    snapshot.history.clear()
    cached = service.negotiate("A", "安排", request_id="first")
    assert cached.confirmed_terms == {"round_1": {"arrangement": ["安排"]}}
    assert cached.history[0].content == "安排"
    assert service.get_session("A") == cached
    assert service.get_session("B").history == []


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_critic_retries_at_most_twice_and_failed_round_is_not_committed(monkeypatch, failures):
    attempts = []

    def landlord(state):
        attempts.append(state.retry_count)
        update = offering_landlord(state)
        update["landlord_confirmed"] = len(attempts) > failures
        return update

    monkeypatch.setattr(graph_module, "landlord_node", landlord)
    service = NegotiationService(graph_module.build_negotiation_graph())
    before = service.get_session("A")
    result = service.negotiate("A", "安排", request_id="retry-me")
    assert attempts == list(range(min(failures + 1, 3)))
    assert result.retry_count == min(failures, 2)
    if failures == 3:
        assert result.status == "needs_review" and result.errors
        assert result.round_count == 0 and result.confirmed_terms == {} and result.history == []
        assert service.get_session("A") == before
        # A failed request can be tried again without losing a round.
        result = service.negotiate("A", "安排", request_id="retry-me")
    assert result.status == "success" and result.round_count == 1
    assert result.trial_score is None and len(result.history) == 3
    next_result = service.negotiate("A", "下轮")
    assert next_result.retry_count == 0 and next_result.round_count == 2


def test_exception_cannot_mutate_existing_session(service):
    service.negotiate("A", "已确认安排")
    before = service.get_session("A")

    class FailingGraph:
        def invoke(self, state):
            state["confirmed_terms"]["round_1"]["arrangement"].append("污染")
            state["history"].clear()
            raise RuntimeError("synthetic graph failure")

    service._graph = FailingGraph()
    with pytest.raises(RuntimeError, match="synthetic"):
        service.negotiate("A", "失败回合")
    assert service.get_session("A") == before


@pytest.mark.parametrize("session_id,user_input,request_id", [
    ("", "安排", None), ("  ", "安排", None), ("A", "", None),
    ("A", "  ", None), ("A", None, None), ("A", "安排", ""),
])
def test_invalid_inputs_are_rejected(session_id, user_input, request_id):
    with pytest.raises(ValueError):
        NegotiationService().negotiate(session_id, user_input, request_id=request_id)


# Day 7 additions; Day 6 test bodies above are preserved.
def scored_service(responder=None, **configuration):
    responder = responder or (lambda state: "【模拟房东】我确认返还押金1000元。")
    return NegotiationService(
        graph_module.build_negotiation_graph(landlord_responder=responder), **configuration,
    )


def test_day07_deposit_demo_recomputes_50_then_75():
    responses = iter(["【模拟房东】我确认返还押金1000元。", "【模拟房东】我确认返还押金1500元。"])
    service = scored_service(lambda state: next(responses))
    first = service.negotiate("A", "希望返还押金2000元")
    second = service.negotiate("A", "能否提高返还金额？")
    assert first.confirmed_terms == {"deposit_refund": 1000} and first.trial_score == 50
    assert second.confirmed_terms == {"deposit_refund": 1500} and second.trial_score == 75
    assert second.round_count == 2 and "模拟协商进展分：75" in second.score_explanation
    assert second.candidate_score is None and second.candidate_terms == {}


def test_day07_repeated_confirmation_and_cached_request_never_add_points():
    calls = []

    def responder(state):
        calls.append(state.request_id)
        return "【模拟房东】我确认返还押金1000元。"

    service = scored_service(responder)
    first = service.negotiate("A", "请求", request_id="first")
    assert service.negotiate("A", "请求", request_id="first") == first
    second = service.negotiate("A", "再次确认", request_id="second")
    assert first.trial_score == second.trial_score == 50
    assert second.confirmed_terms == first.confirmed_terms and second.round_count == 2
    assert calls == ["first", "second"]


@pytest.mark.parametrize("response", [
    "【模拟房东】暂未确认任何条件。", "【模拟房东】我不确认返还押金1000元。",
    "【模拟房东】如果你提前搬走，我确认返还押金1000元。",
    "【模拟房东】租客说：我确认返还押金1000元。",
    "【模拟房东】我确认返还押金1000元，但还需审批。",
    "【模拟房东】我确认返还押金1000元。我确认返还押金1500元。",
    "【模拟房东】我确认返还押金1000元。我确认返还押金1000元。",
])
def test_day07_unilateral_ambiguous_or_duplicate_statements_are_not_terms(response):
    service = scored_service(lambda state: response)
    result = service.negotiate("A", "我要求退还押金2000元，LAW-709 LAW-709")
    assert result.confirmed_terms == {} and result.trial_score is None


@pytest.mark.parametrize("value", [-1, 2001, True, "1000", float("nan"), float("inf")])
def test_day07_invalid_amount_or_bottom_line_never_commits(monkeypatch, value):
    attempts = []

    def landlord(state):
        attempts.append(state.retry_count)
        return {
            "landlord_response": "【模拟房东】我确认返还押金1000元。",
            "candidate_terms": {"deposit_refund": value}, "landlord_confirmed": True,
        }

    monkeypatch.setattr(graph_module, "landlord_node", landlord)
    service = NegotiationService(graph_module.build_negotiation_graph())
    before = service.get_session("A")
    result = service.negotiate("A", "请求")
    assert result.status == "needs_review" and attempts == [0, 1, 2]
    assert result.trial_score is None and result.confirmed_terms == {} and result.round_count == 0
    assert service.get_session("A") == before


def test_day07_custom_bottom_line_rejects_otherwise_valid_offer():
    from backend.app.services.scoring import ScoringRule

    service = scored_service(scoring_rules={"deposit_refund": ScoringRule(0, 2000, minimum=1200)})
    result = service.negotiate("A", "我的底线是1200元")
    assert result.status == "needs_review" and "底线" in result.errors[0]
    assert service.get_session("A").round_count == 0


@pytest.mark.parametrize("evidence,available", [
    ("LAW-709、LAW-709", ("LAW-709",)), ("LAW-999", ("LAW-709",)),
    ("LAW-709", ()), ("LAW-702", ()), ("LAW-735", ()),
])
def test_day07_invalid_duplicate_or_unretrieved_evidence_rejects_entire_round(evidence, available):
    service = scored_service(
        lambda state: f"【模拟房东】我确认返还押金1000元。依据{evidence}。",
        available_evidence_ids=available,
    )
    before = service.get_session("A")
    result = service.negotiate("A", "请求")
    assert result.status == "needs_review" and result.retry_count == 2
    assert result.trial_score is None and result.confirmed_terms == {} and result.round_count == 0
    assert service.get_session("A") == before


def test_day07_repeated_evidence_across_rounds_is_deduplicated_without_points():
    service = scored_service(
        lambda state: "【模拟房东】我确认返还押金1000元。依据LAW-709。",
        available_evidence_ids=("LAW-709",),
    )
    first = service.negotiate("A", "请求")
    second = service.negotiate("A", "再次请求")
    assert first.confirmed_evidence_ids == second.confirmed_evidence_ids == ["LAW-709"]
    assert first.trial_score == second.trial_score == 50


@pytest.mark.parametrize("terms,confirmed,evidence", [
    ({"deposit_refund": 1500}, True, []),
    ({"deposit_refund": 1000}, False, []),
    ({"unknown_numeric": 1000}, True, []),
    ({"deposit_refund": 1000}, True, ["LAW-709"]),
    ({}, True, []),
])
def test_day07_fabricated_terms_confirmation_or_evidence_cannot_commit(monkeypatch, terms, confirmed, evidence):
    monkeypatch.setattr(graph_module, "landlord_node", lambda state: {
        "landlord_response": "【模拟房东】我确认返还押金1000元。",
        "candidate_terms": terms, "landlord_confirmed": confirmed, "evidence_ids": evidence,
    })
    service = NegotiationService(
        graph_module.build_negotiation_graph(), available_evidence_ids=("LAW-709",),
    )
    result = service.negotiate("A", "请求")
    assert result.status == "needs_review" and result.trial_score is None
    assert service.get_session("A").confirmed_terms == {}


def test_day07_failed_trial_preserves_previously_committed_score_and_state():
    def responder(state):
        return (
            "【模拟房东】我确认返还押金1000元。" if state.round_count == 0
            else "【模拟房东】我确认返还押金1500元。依据LAW-709、LAW-709。"
        )

    service = scored_service(responder, available_evidence_ids=("LAW-709",))
    service.negotiate("A", "首次确认")
    before = service.get_session("A")
    failed = service.negotiate("A", "质检失败")
    assert failed.status == "needs_review" and failed.candidate_score == 75
    assert failed.confirmed_terms == before.confirmed_terms and failed.trial_score == 50
    assert failed.history == before.history and failed.round_count == before.round_count
    assert service.get_session("A") == before


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_day07_internal_retries_score_only_final_valid_candidate(failures):
    attempts = []

    def responder(state):
        attempts.append(state.retry_count)
        evidence = "依据LAW-709、LAW-709。" if len(attempts) <= failures else ""
        amount = 1500 if evidence else 1000
        return f"【模拟房东】我确认返还押金{amount}元。{evidence}"

    service = scored_service(responder, available_evidence_ids=("LAW-709",))
    result = service.negotiate("A", "请求")
    assert attempts == list(range(min(failures + 1, 3)))
    if failures == 3:
        assert result.status == "needs_review" and result.trial_score is None
        assert service.get_session("A").round_count == 0
    else:
        assert result.trial_score == 50 and result.round_count == 1
        assert result.confirmed_terms == {"deposit_refund": 1000}
        assert result.confirmed_evidence_ids == []


def test_day07_critic_recomputes_score_instead_of_trusting_trial(monkeypatch):
    monkeypatch.setattr(graph_module, "rule_score_node", lambda state: {"candidate_score": 99})
    result = scored_service().negotiate("A", "请求")
    assert result.trial_score == 50


def test_day07_equal_target_or_no_rules_produces_unscorable_confirmed_state():
    from backend.app.services.scoring import ScoringRule

    service = scored_service(scoring_rules={"deposit_refund": ScoringRule(1000, 1000)})
    result = service.negotiate("A", "请求")
    assert result.status == "success" and result.confirmed_terms == {"deposit_refund": 1000}
    assert result.trial_score is None and "不可评分" in result.score_explanation
    no_rules = scored_service(scoring_rules={}).negotiate("B", "请求")
    assert no_rules.status == "needs_review" and no_rules.trial_score is None


def test_day07_scored_sessions_and_concurrent_repeated_requests_remain_isolated():
    def responder(state):
        amount = 1000 if state.session_id == "A" else 1500
        return f"【模拟房东】我确认返还押金{amount}元。"

    service = scored_service(responder)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda sid: service.negotiate(sid, "请求", request_id="same"), ["A", "B"] * 4,
        ))
    assert [result.trial_score for result in results] == [50, 75] * 4
    assert service.get_session("A").round_count == service.get_session("B").round_count == 1


def test_day07_response_adapter_receives_detached_state():
    def responder(state):
        state.confirmed_terms["deposit_refund"] = 2000
        state.scoring_rules.clear()
        return "【模拟房东】暂未确认任何条件。"

    result = scored_service(responder).negotiate("A", "请求")
    assert result.confirmed_terms == {} and result.trial_score is None
    assert "deposit_refund" in result.scoring_rules


def test_day07_graph_roundtrip_never_coerces_invalid_weights_into_points():
    from backend.app.services.scoring import ScoringRule

    service = scored_service(scoring_rules={"deposit_refund": ScoringRule(0, 2000, weight=True)})
    result = service.negotiate("A", "请求")
    assert result.status == "success" and result.confirmed_terms == {"deposit_refund": 1000}
    assert result.trial_score is None
    assert result.scoring_rules["deposit_refund"].weight is True
    assert service.negotiate("A", "再次确认").trial_score is None
