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
