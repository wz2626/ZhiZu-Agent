"""Day 10 offline HTTP, scene extraction, privacy, trace and transaction checks."""

from concurrent.futures import ThreadPoolExecutor
import json
import math
from time import sleep

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.negotiation import get_negotiation_service
from backend.app.main import app
from backend.app.schemas.negotiation import NegotiationState, NegotiationTraceEvent
from backend.app.services import negotiation_graph as graph_module
from backend.app.services.negotiation_service import NegotiationService
from backend.app.services.scoring import calculate_score, scenario_scoring_rules

SCENES = [
    ("deposit", "deposit_refund", [1000, 1500, 2000]),
    ("maintenance", "repair_cost_share", [50, 75, 100]),
    ("early_termination", "termination_fee", [1000, 500, 0]),
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Day 10 tests must not call cloud services")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI.invoke", forbidden)
    monkeypatch.setattr("backend.app.services.embedding.httpx.post", forbidden)


def practice_service(responder=graph_module.scenario_landlord_responder):
    return NegotiationService(graph_module.build_negotiation_graph(landlord_responder=responder), public_api=True)


@pytest.fixture
def client():
    service = practice_service()
    app.dependency_overrides[get_negotiation_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.pop(get_negotiation_service, None)


def submit(client, *, sid="session-A", rid="request-1", scenario="deposit", text="请核对凭证并明确协商条件。", **extra):
    return client.post("/api/negotiation/turn", json={
        "session_id": sid, "request_id": rid, "user_input": text, "scenario": scenario, **extra,
    })


def assert_trace(trace):
    assert [e["sequence"] for e in trace] == list(range(1, len(trace) + 1))
    for event in trace:
        assert 0 <= event["attempt"] <= 3
        assert event["status"] in {"completed", "failed", "retry", "needs_review"}
        assert math.isfinite(event["duration_ms"]) and event["duration_ms"] >= 0
        assert isinstance(event["feedback"], list)


@pytest.mark.parametrize("scenario,key,values", SCENES)
def test_three_scene_http_commit_score_trace_and_five_round_limit(client, scenario, key, values):
    http, service = client
    for n in range(1, 6):
        result = submit(http, rid=f"r{n}", scenario=scenario).json()
        assert result["scenario"] == scenario and result["round_count"] == n
        assert result["confirmed_terms"] == {key: values[min(n - 1, 2)]}
        assert result["trial_score"] == [50, 75, 100][min(n - 1, 2)]
        assert result["status"] == ("completed" if n == 5 else "success")
        assert result["replayed"] is False and result["confirmed_evidence_ids"] == []
        assert [e["node"] for e in result["trace"]] == ["tenant_coach", "landlord", "rule_score", "critic"]
        assert result["trace"][-1]["feedback"]
        assert_trace(result["trace"])
        assert "candidate_terms" not in result and "history" not in result
    before = service.get_session("session-A")
    sixth = submit(http, rid="r6", scenario=scenario).json()
    assert sixth["request_id"] == "r6" and sixth["trace"] == [] and sixth["round_count"] == 5
    assert sixth["confirmed_terms"] == result["confirmed_terms"]
    assert service.get_session("session-A") == before


@pytest.mark.parametrize("alias,canonical", [("repair", "maintenance"), ("termination", "early_termination")])
def test_scenario_aliases(client, alias, canonical):
    result = submit(client[0], scenario=alias).json()
    assert result["scenario"] == canonical and result["trial_score"] == 50


def test_openapi_has_exactly_one_discoverable_submit_endpoint(client):
    schema = client[0].get("/openapi.json").json()
    matches = []
    for path, methods in schema["paths"].items():
        body = methods.get("post", {}).get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if "$ref" in body:
            body = schema["components"]["schemas"][body["$ref"].split("/")[-1]]
        if {"session_id", "user_input", "request_id"} <= body.get("properties", {}).keys():
            matches.append(path)
            assert set(body["required"]) == {"session_id", "user_input", "request_id"}
            assert body["additionalProperties"] is False
            assert all(body["properties"][key]["type"] == "string" for key in body["required"])
    assert matches == ["/api/negotiation/turn"]


@pytest.mark.parametrize("field,value", [
    ("session_id", ""), ("session_id", " "), ("session_id", "x" * 65), ("session_id", 1),
    ("session_id", "13800000000"), ("request_id", "110101199001010000"),
    ("request_id", None), ("request_id", "bad/id"), ("user_input", " "),
    ("user_input", 1000), ("user_input", "x" * 2001), ("scenario", "unknown"),
], ids=["empty_session", "blank_session", "long_session", "numeric_session", "phone_identifier", "id_identifier",
        "null_request", "invalid_identifier", "blank_message", "numeric_message", "long_message", "unknown_scene"])
def test_http_invalid_fields_never_echo_input_or_commit(client, field, value):
    response = submit(client[0], **{field: value}) if field not in {"session_id", "request_id", "user_input"} else client[0].post(
        "/api/negotiation/turn", json={"session_id": "session-A", "request_id": "r1", "user_input": "hello", field: value},
    )
    assert response.status_code == 422 and response.json() == {"detail": "谈判请求格式无效，请检查字段、长度与标识。"}
    assert client[1].get_session("session-A").round_count == 0


@pytest.mark.parametrize("field", ["session_id", "request_id", "user_input"])
def test_required_http_fields(client, field):
    data = {"session_id": "session-A", "request_id": "r1", "user_input": "hello"}
    data.pop(field)
    assert client[0].post("/api/negotiation/turn", json=data).status_code == 422


@pytest.mark.parametrize("field", ["trial_score", "scoring_rules", "confirmed_terms", "available_evidence_ids"])
def test_untrusted_http_state_cannot_be_injected(client, field):
    assert submit(client[0], **{field: 100}).status_code == 422
    assert client[1].get_session("session-A").round_count == 0


def test_bad_json_and_invalid_identifier_are_safe(client):
    response = client[0].post("/api/negotiation/turn", content='{ "user_input": "13800000000",', headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "13800000000" not in response.text


@pytest.mark.parametrize("token", ["13800000000", "+86 138-0000-0000", "110101199001010000", "11010119900101000X", "110101900101000", "110101000000000000"],
                         ids=["phone", "international_phone", "id18", "id18_x", "id15", "malformed_id"])
def test_http_and_direct_service_mask_before_adapter_history_and_cache(client, token):
    calls = []
    def responder(state):
        calls.append(state.user_input)
        return "【模拟房东】暂未确认任何条件。"
    service = practice_service(responder)
    app.dependency_overrides[get_negotiation_service] = lambda: service
    response = submit(client[0], text="测试标识：" + token)
    assert response.status_code == 200 and calls == ["测试标识：***"]
    assert token not in response.text and token not in service.get_session("session-A").model_dump_json()
    cached = service._sessions["session-A"].requests["request-1"]
    assert token not in str(cached)
    service.negotiate("direct", "测试标识：" + token, request_id="direct")
    assert calls[-1] == "测试标识：***"


@pytest.mark.parametrize("scenario,key,values", SCENES)
@pytest.mark.parametrize("variant", ["conditional", "negated", "quoted", "duplicate", "wrong_scene"])
def test_scene_ambiguous_and_cross_scene_responses_never_confirm(scenario, key, values, variant):
    prefix = graph_module._TEMPLATES[scenario][1]
    base = graph_module.scenario_landlord_responder(NegotiationState(session_id="A", scenario=scenario))
    responses = {
        "conditional": base.replace("【模拟房东】", "【模拟房东】如果审批通过，"),
        "negated": base.replace(prefix, prefix.replace("我确认", "我不确认")),
        "quoted": base.replace("【模拟房东】", "【模拟房东】租客说："),
        "duplicate": base + base,
        "wrong_scene": "【模拟房东】我确认承担维修费用50%。" if scenario != "maintenance" else "【模拟房东】我确认返还押金1000元。",
    }
    result = practice_service(lambda state: responses[variant]).negotiate("A", "我要求2000元", scenario=scenario)
    assert result.confirmed_terms == {} and result.trial_score is None


@pytest.mark.parametrize("scenario,key,values", SCENES)
@pytest.mark.parametrize("amount", [-1, 3000])
def test_scene_bottom_line_rejections_never_commit(scenario, key, values, amount):
    _, prefix, unit = graph_module._TEMPLATES[scenario]
    service = practice_service(lambda state: f"【模拟房东】{prefix}{amount}{unit}。")
    result = service.negotiate("A", "请求", scenario=scenario)
    assert result.status == "needs_review" and result.retry_count == 2
    assert result.confirmed_terms == {} and service.get_session("A").round_count == 0


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_real_retry_trace_and_failure_cache(failures):
    calls = []
    def responder(state):
        calls.append(state.retry_count)
        return "【模拟房东】我确认返还押金3000元。" if len(calls) <= failures else "【模拟房东】我确认返还押金1000元。"
    service = practice_service(responder)
    result = service.negotiate("A", "请求", request_id="r1")
    assert calls == list(range(min(failures + 1, 3)))
    assert_trace([e.model_dump() for e in result.trace])
    assert len([e for e in result.trace if e.node == "critic"]) == len(calls)
    assert len([e for e in result.trace if e.node == "retry"]) == min(failures, 2)
    replay = service.negotiate("A", "请求", request_id="r1")
    assert replay.replayed and replay.trace == result.trace and len(calls) == min(failures + 1, 3)
    if failures == 3:
        assert result.round_count == 0 and service.get_session("A").confirmed_terms == {}
        assert service.negotiate("A", "请求", request_id="r2").round_count == 1


def test_node_trace_measures_execution_and_exception_preserves_prior_events(monkeypatch):
    def coach(state):
        sleep(0.015)
        return {"coach_advice": "模拟辅导"}
    monkeypatch.setattr(graph_module, "tenant_coach_node", coach)
    def fail(state):
        raise RuntimeError("private-data-13800000000")
    service = practice_service(fail)
    before = service.get_session("A")
    result = service.negotiate("A", "请求", request_id="r1")
    assert result.status == "needs_review" and service.get_session("A") == before
    assert [e.node for e in result.trace] == ["tenant_coach", "landlord"]
    assert result.trace[0].duration_ms >= 10 and result.trace[1].status == "failed"
    assert "private-data" not in result.model_dump_json() and "13800000000" not in result.model_dump_json()


def test_http_failure_hides_rejected_draft_and_preserves_official_state(client):
    def responder(state):
        return "【模拟房东】我确认返还押金1000元。" if state.round_count == 0 else "【模拟房东】13800000000"
    service = practice_service(responder)
    app.dependency_overrides[get_negotiation_service] = lambda: service
    first = submit(client[0]).json()
    failed = submit(client[0], rid="r2").json()
    assert failed["status"] == "needs_review" and failed["round_count"] == 1
    assert failed["confirmed_terms"] == first["confirmed_terms"] and failed["trial_score"] == 50
    assert failed["landlord_response"] == "" and "13800000000" not in json.dumps(failed)
    assert service.get_session("session-A").request_id == "request-1"
    assert "13800000000" not in str(service._sessions["session-A"].requests["r2"])


def test_request_conflicts_and_cached_retry_after_later_round(client):
    first = submit(client[0]).json()
    assert submit(client[0], text="不同输入").status_code == 409
    assert submit(client[0], scenario="maintenance", rid="r2").status_code == 409
    assert submit(client[0], rid="r2").json()["round_count"] == 2
    replay = submit(client[0]).json()
    assert replay["replayed"] and replay["trace"] == first["trace"] and replay["round_count"] == 1
    assert client[1].get_session("session-A").round_count == 2


def test_parallel_sessions_and_duplicate_requests_keep_trace_and_commits_isolated():
    service = practice_service()
    def run(scene):
        return service.negotiate(scene, "请求", request_id="same", scenario=scene)
    with ThreadPoolExecutor(max_workers=9) as pool:
        results = list(pool.map(run, [scene[0] for scene in SCENES] * 3))
    for scene, key, _ in SCENES:
        subset = [r for r in results if r.scenario == scene]
        assert sum(not r.replayed for r in subset) == 1
        assert all(r.round_count == 1 and r.trial_score == 50 and key in r.confirmed_terms for r in subset)
        assert all(r.trace == subset[0].trace for r in subset)
        assert service.get_session(scene).round_count == 1


@pytest.mark.parametrize("field,value", [("attempt", 4), ("status", "invented"), ("duration_ms", float("nan")), ("duration_ms", -1)])
def test_trace_schema_rejects_invalid_public_events(field, value):
    data = dict(sequence=1, node="critic", attempt=1, status="completed", duration_ms=1, feedback=[])
    data[field] = value
    with pytest.raises(ValidationError):
        NegotiationTraceEvent(**data)


@pytest.mark.parametrize("scenario,key,values", SCENES)
def test_scene_scoring_is_deterministic_and_does_not_count_user_requests(scenario, key, values):
    terms = {key: values[0]}
    rules = scenario_scoring_rules(scenario)
    assert [calculate_score(terms, rules) for _ in range(5)] == [50] * 5


@pytest.mark.parametrize("scenario,key,values", SCENES)
@pytest.mark.parametrize("evidence,available,valid", [
    ("LAW-712", ("LAW-712",), True), ("LAW-712", (), False),
    ("LAW-712、LAW-712", ("LAW-712",), False), ("LAW-999", (), False),
])
def test_all_scene_reference_identity_is_checked_and_does_not_score(scenario, key, values, evidence, available, valid):
    _, prefix, unit = graph_module._TEMPLATES[scenario]
    graph = graph_module.build_negotiation_graph(landlord_responder=lambda state: f"【模拟房东】{prefix}{values[0]}{unit}。依据{evidence}。")
    service = NegotiationService(graph, public_api=True, available_evidence_ids=available)
    result = service.negotiate("A", "LAW-712 LAW-712 我单方要求满分", scenario=scenario)
    assert result.status == ("success" if valid else "needs_review")
    assert result.trial_score == (50 if valid else None)
    assert result.confirmed_evidence_ids == (["LAW-712"] if valid else [])


@pytest.mark.parametrize("scenario,key,values", SCENES)
def test_repeated_same_scene_confirmation_recomputes_same_score(scenario, key, values):
    _, prefix, unit = graph_module._TEMPLATES[scenario]
    service = practice_service(lambda state: f"【模拟房东】{prefix}{values[0]}{unit}。")
    first = service.negotiate("A", "单方要求满分", request_id="r1", scenario=scenario)
    second = service.negotiate("A", "重复要求满分", request_id="r2", scenario=scenario)
    assert first.confirmed_terms == second.confirmed_terms == {key: values[0]}
    assert first.trial_score == second.trial_score == 50 and second.round_count == 2


def test_orchestration_exception_returns_only_actual_failure_event(client):
    class FailingGraph:
        def invoke(self, state):
            raise RuntimeError("synthetic-secret-do-not-expose")
    service = NegotiationService(FailingGraph(), public_api=True)
    app.dependency_overrides[get_negotiation_service] = lambda: service
    response = submit(client[0])
    assert response.status_code == 200 and response.json()["status"] == "needs_review"
    assert [event["node"] for event in response.json()["trace"]] == ["graph"]
    assert "synthetic-secret" not in response.text and service.get_session("session-A").round_count == 0


def test_network_guard_blocks_external_dns_and_socket_without_calling_cloud():
    import socket
    with pytest.raises(pytest.fail.Exception, match="external DNS"):
        socket.getaddrinfo("cloud.example.invalid", 443)
    with socket.socket() as sock:
        with pytest.raises(pytest.fail.Exception, match="external network"):
            sock.connect(("192.0.2.1", 443))
