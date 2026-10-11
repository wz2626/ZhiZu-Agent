"""Offline fault injection for detailed review, measured trace and isolation."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError
from pydantic import ValidationError

from backend.app.api.review import get_review_service
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.schemas.review import ReviewDetailedResponse, ReviewTraceEvent
from backend.app.services import graph as graph_module
from backend.app.services.embedding import get_embeddings
from backend.app.services.graph import review_graph
from backend.app.services.review import ContractReviewService
from backend.app.services.review_trace import public_feedback
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws, mask_sensitive_text

CONTRACT = "租客按时支付租金。租客未经房东同意擅自转租房屋。"
CLAUSE = "租客未经房东同意擅自转租房屋。"


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch, tmp_path):
    for name, value in {
        "CHAT_API_KEY": "sk-synthetic-detailed", "CHAT_MODEL": "offline-chat",
        "CHAT_BASE_URL": "https://chat.example.invalid/v1", "CHAT_TIMEOUT_SECONDS": "20",
        "EMBEDDING_API_KEY": "", "EMBEDDING_MODEL": "offline-embedding",
        "EMBEDDING_BASE_URL": "https://embedding.example.invalid/v1",
        "CHROMA_PATH": str(tmp_path / "missing"),
    }.items():
        monkeypatch.setenv(name, value)

    def forbidden(*args, **kwargs):
        pytest.fail("detailed unit tests must never call cloud services")

    # Keep the legacy test module's fixtures untouched; also block SDK bypasses.
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI.invoke", forbidden)
    monkeypatch.setattr("backend.app.services.embedding.httpx.post", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def finding(**overrides):
    item = {
        "clause_id": "C-01", "original_clause": CLAUSE, "risk_level": "HIGH",
        "explanation": "未经同意转租存在解除风险。", "evidence_ids": ["LAW-716"],
        "negotiation_tip": "请取得明确的转租授权。",
    }
    item.update(overrides)
    return item


class FakeLLM:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def invoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response)


class FakeStore:
    def __init__(self, *, ready=True, empty=False, error=None):
        law = next(law for law in load_authoritative_laws() if law.law_id == "LAW-716")
        self.evidence = [] if empty else [LawVectorStoreService._evidence(law, 0.6)]
        self.ready, self.error, self.calls = ready, error, []

    def get_status(self):
        return SimpleNamespace(is_ready=self.ready)

    def search_evidence(self, query, top_k=4):
        self.calls.append((query, top_k))
        if self.error:
            raise self.error
        return self.evidence


def service_for(*responses, store=None):
    return ContractReviewService(llm=FakeLLM(*responses), vector_store=store or FakeStore())


@pytest.fixture
def client():
    previous = app.dependency_overrides.get(get_review_service)
    with TestClient(app) as client:
        yield client
    if previous is None:
        app.dependency_overrides.pop(get_review_service, None)
    else:
        app.dependency_overrides[get_review_service] = previous


def use_service(service):
    def dependency():
        try:
            yield service
        finally:
            service.close()
    app.dependency_overrides[get_review_service] = dependency


def check_trace(response, nodes):
    assert [event.node for event in response.trace] == nodes
    assert [event.sequence for event in response.trace] == list(range(1, len(nodes) + 1))
    assert all(event.duration_ms >= 0 for event in response.trace)
    assert response.trace_label == "本次执行回放"


def test_detailed_api_success_and_openapi_contract(client):
    service = service_for(json.dumps([finding()]))
    use_service(service)
    result = client.post("/api/review/analyze-detailed", json={"contract_text": CONTRACT})
    assert result.status_code == 200
    response = ReviewDetailedResponse.model_validate(result.json())
    assert response.status == "success" and response.total_risks == 1
    assert response.reason is None and response.failure_code is None and response.errors == []
    check_trace(response, ["configuration", "retrieval", "drafting", "critic"])
    assert [event.attempt for event in response.trace] == [0, 0, 1, 1]
    assert response.trace[1].evidence_ids == ["LAW-716"]
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/review/analyze-detailed"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("ReviewDetailedResponse")
    assert set(schema["components"]["schemas"]["ReviewResponse"]["properties"]) == {"status", "results", "total_risks"}


@pytest.mark.parametrize("failures", [1, 2])
def test_rewrite_success_keeps_prior_feedback_only_in_trace(failures):
    service = service_for(*(["broken"] * failures), json.dumps([finding()]))
    response = service.analyze_contract_detailed(CONTRACT)
    assert response.status == "success" and response.retry_count == failures
    assert response.errors == [] and response.reason is None
    check_trace(response, ["configuration", "retrieval"] + ["drafting", "critic"] * (failures + 1))
    critics = [event for event in response.trace if event.node == "critic"]
    assert [event.attempt for event in critics] == list(range(1, failures + 2))
    assert all(event.status == "retry" and "JSON" in event.feedback[0] for event in critics[:-1])
    assert critics[-1].status == "completed" and critics[-1].feedback == []
    assert len(service.llm.calls) == failures + 1


@pytest.mark.parametrize("bad_output", ["broken", json.dumps([finding(evidence_ids=[])]),
                                        json.dumps([finding(original_clause="不在合同中的句子")])])
def test_three_failures_exit_without_mock_findings(client, bad_output):
    service = service_for(bad_output, bad_output, bad_output)
    use_service(service)
    result = client.post("/api/review/analyze-detailed", json={"contract_text": CONTRACT})
    assert result.status_code == 200
    response = ReviewDetailedResponse.model_validate(result.json())
    assert response.status == "needs_review" and response.failure_code == "VALIDATION_FAILED"
    assert response.results == [] and response.total_risks == 0 and response.retry_count == 2
    assert response.errors and response.reason
    check_trace(response, ["configuration", "retrieval"] + ["drafting", "critic"] * 3 + ["mock"])
    assert [event.attempt for event in response.trace[2:]] == [1, 1, 2, 2, 3, 3, 3]
    assert response.trace[-2].status == response.trace[-1].status == "needs_review"
    assert len(service.llm.calls) == 3


@pytest.mark.parametrize("key", ["", "your_deepseek_api_key_here", "placeholder"])
def test_missing_key_skips_storage_and_cloud(client, monkeypatch, key):
    monkeypatch.setenv("CHAT_API_KEY", key)
    def forbidden(*args, **kwargs):
        pytest.fail("missing key must skip both client and storage initialization")
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", forbidden)
    monkeypatch.setattr("backend.app.services.review.LawVectorStoreService", forbidden)
    result = client.post("/api/review/analyze-detailed", json={"contract_text": CONTRACT})
    response = ReviewDetailedResponse.model_validate(result.json())
    assert response.failure_code == "CHAT_NOT_CONFIGURED" and response.results == []
    check_trace(response, ["configuration"])
    assert response.trace[0].status == "failed"


def test_client_initialization_failure_is_explicit_and_safe(client, monkeypatch, caplog):
    private = "sk-synthetic-initialization-secret"
    def fail(**kwargs):
        raise RuntimeError(private)
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", fail)
    result = client.post("/api/review/analyze-detailed", json={"contract_text": CONTRACT})
    response = ReviewDetailedResponse.model_validate(result.json())
    assert response.failure_code == "CHAT_INIT_FAILED"
    assert private not in result.text + caplog.text
    check_trace(response, ["configuration"])


@pytest.mark.parametrize(("store_options", "code"), [
    ({"ready": False}, "KB_NOT_READY"), ({"empty": True}, "NO_EVIDENCE"),
    ({"error": RuntimeError("sk-synthetic-embedding-secret")}, "UPSTREAM_EMBEDDING_ERROR"),
    ({"error": ValueError("sk-synthetic-storage-secret")}, "KB_NOT_READY"),
    ({"error": TypeError("sk-synthetic-retrieval-secret")}, "RETRIEVAL_FAILED"),
])
def test_retrieval_failures_never_generate_or_invent_graph_nodes(store_options, code):
    service = service_for(store=FakeStore(**store_options))
    response = service.analyze_contract_detailed(CONTRACT)
    assert response.status == "needs_review" and response.failure_code == code
    assert response.results == [] and service.llm.calls == []
    check_trace(response, ["configuration", "retrieval"])
    assert response.trace[-1].status == "failed"
    assert "sk-synthetic-" not in response.model_dump_json()


def test_missing_real_store_is_read_only(client, monkeypatch):
    # Real adapter with absent SQLite path, simulated chat, no actual vectors.
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", lambda **kwargs: FakeLLM())
    response = ReviewDetailedResponse.model_validate(client.post(
        "/api/review/analyze-detailed", json={"contract_text": CONTRACT},
    ).json())
    assert response.failure_code == "KB_NOT_READY"
    from pathlib import Path
    assert not Path(get_settings().chroma_path).exists()


@pytest.mark.parametrize(("error", "code"), [
    (TimeoutError("sk-synthetic-timeout"), "CHAT_TIMEOUT"),
    (httpx.ReadTimeout("sk-synthetic-timeout"), "CHAT_TIMEOUT"),
    (APITimeoutError(request=httpx.Request("POST", "https://example.invalid")), "CHAT_TIMEOUT"),
    (RuntimeError("sk-synthetic-call-secret"), "CHAT_CALL_FAILED"),
])
def test_chat_failure_has_explicit_code_and_no_critic(error, code, caplog):
    service = service_for(error)
    response = service.analyze_contract_detailed(CONTRACT)
    assert response.failure_code == code and response.retry_count == 0
    assert response.results == [] and len(service.llm.calls) == 1
    check_trace(response, ["configuration", "retrieval", "drafting", "mock"])
    assert response.trace[2].status == "failed"
    assert "sk-synthetic-" not in response.model_dump_json() + caplog.text


@pytest.mark.parametrize("prior_failures", [0, 1])
def test_unexpected_graph_error_keeps_completed_trace(prior_failures, monkeypatch):
    original_validate = graph_module.validate_response
    def fail(content, *args):
        if content == "broken":
            return original_validate(content, *args)
        raise RuntimeError("sk-synthetic-graph-secret")
    monkeypatch.setattr(graph_module, "validate_response", fail)
    service = service_for(*(["broken"] * prior_failures), json.dumps([finding()]))
    response = service.analyze_contract_detailed(CONTRACT)
    assert response.failure_code == "GRAPH_EXECUTION_FAILED"
    assert response.retry_count == prior_failures and response.results == []
    check_trace(response, ["configuration", "retrieval"] + ["drafting", "critic"] * prior_failures + ["drafting", "graph"])
    assert response.trace[-1].attempt == 0 and response.trace[-1].status == "failed"
    assert "sk-synthetic-graph-secret" not in response.model_dump_json()


@pytest.mark.parametrize("field", ["original_clause", "explanation", "extra_field"])
def test_invalid_output_never_enters_errors_or_trace(field):
    private = "sk-synthetic-raw-draft 13800138000"
    value = {"raw": private} if field == "explanation" else private
    draft = json.dumps([finding(**{field: value})])
    service = service_for(draft, draft, draft)
    response = service.analyze_contract_detailed(CONTRACT)
    assert response.status == "needs_review"
    assert private not in response.model_dump_json()
    assert "13800138000" not in response.model_dump_json()
    for event in response.trace:
        assert set(event.model_dump()) == {"sequence", "node", "attempt", "status", "duration_ms", "evidence_ids", "feedback"}


def test_safe_feedback_allowlist_does_not_echo_unknown_strings():
    assert public_feedback(["HIGH finding has no retrieved evidence"]) == ["HIGH finding has no retrieved evidence"]
    assert public_feedback(["JSON 字段结构校验失败：explanation, risk_level"]) == ["JSON 字段结构校验失败：explanation, risk_level"]
    assert "sk-synthetic" not in str(public_feedback([
        "sk-synthetic", "JSON 字段结构校验失败：sk-synthetic",
    ]))


def test_masking_before_retrieval_and_trace_contains_no_contract():
    text = "联系13800138000，身份证110101199001011234。" + CONTRACT
    service = service_for(json.dumps([finding()]))
    response = service.analyze_contract_detailed(text)
    assert service.vector_store.calls == [(mask_sensitive_text(text), 4)]
    assert "13800138000" not in service.llm.calls[0][1].content
    trace = json.dumps([event.model_dump() for event in response.trace], ensure_ascii=False)
    assert CONTRACT not in trace and "13800138000" not in trace and "110101199001011234" not in trace
    assert "messages" not in trace and "current_draft" not in trace


def test_trace_duration_comes_from_actual_node_clocks(monkeypatch):
    monkeypatch.setattr(graph_module, "perf_counter", iter([10.0, 20.0]).__next__)
    monkeypatch.setattr("backend.app.services.review_trace.perf_counter", iter([10.125, 20.250]).__next__)
    sink = []
    state = review_graph.invoke({
        "contract_text": CONTRACT, "evidence_list": FakeStore().evidence,
        "current_draft": None, "errors": [], "retry_count": 0,
        "final_results": [], "status": "drafting", "messages": [], "retry_pending": False,
    }, context={"llm": FakeLLM(json.dumps([finding()])), "trace": sink})
    assert state["trace"] == sink
    assert [event.duration_ms for event in sink] == [125.0, 250.0]


def test_concurrent_requests_share_graph_without_sharing_trace():
    failed = service_for("broken", "broken", "broken")
    successful = service_for(json.dumps([finding()]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(failed.analyze_contract_detailed, CONTRACT)
        second = pool.submit(successful.analyze_contract_detailed, CONTRACT)
        failed_response, successful_response = first.result(), second.result()
    assert failed_response.retry_count == 2 and successful_response.retry_count == 0
    assert len(failed_response.trace) == 9 and len(successful_response.trace) == 4
    assert successful_response.errors == []
    assert all(event.feedback == [] for event in successful_response.trace)
    assert failed_response.trace is not successful_response.trace


def test_reused_service_resets_trace_and_errors_per_request():
    service = service_for("broken", "broken", "broken", json.dumps([finding()]))
    failed = service.analyze_contract_detailed(CONTRACT)
    succeeded = service.analyze_contract_detailed(CONTRACT)
    assert failed.retry_count == 2 and succeeded.retry_count == 0
    assert len(failed.trace) == 9 and len(succeeded.trace) == 4
    assert succeeded.trace[0].sequence == 1 and succeeded.errors == []


def test_legacy_api_has_identical_mock_shape_after_detailed_failure(client):
    service = service_for(*(["broken"] * 6))
    use_service(service)
    detailed = client.post("/api/review/analyze-detailed", json={"contract_text": CONTRACT}).json()
    legacy = client.post("/api/review/analyze", json={"contract_text": CONTRACT}).json()
    assert detailed["status"] == "needs_review" and detailed["results"] == []
    assert legacy["status"] == "mock" and legacy["total_risks"] == 1
    assert set(legacy) == {"status", "results", "total_risks"}
    assert [item["risk_level"] for item in legacy["results"]] == ["HIGH", "NONE"]


@pytest.mark.parametrize("payload", [{}, {"contract_text": "短"}, {"contract_text": " " * 10},
                                      {"contract_text": CONTRACT, "top_k": True},
                                      {"contract_text": CONTRACT, "top_k": 9}])
def test_detailed_invalid_request_never_runs_graph(client, payload):
    service = service_for()
    use_service(service)
    assert client.post("/api/review/analyze-detailed", json=payload).status_code == 422
    assert service.llm.calls == service.vector_store.calls == []


@pytest.mark.parametrize("duration", [-1.0, float("nan"), float("inf")])
def test_trace_schema_rejects_invalid_duration(duration):
    with pytest.raises(ValidationError):
        ReviewTraceEvent(sequence=1, node="drafting", attempt=1, status="completed", duration_ms=duration)


def test_detailed_schema_rejects_failed_findings_and_noncontinuous_trace():
    with pytest.raises(ValidationError):
        ReviewDetailedResponse(status="needs_review", results=[finding()], total_risks=1,
                               failure_code="VALIDATION_FAILED", reason="failed", errors=["failed"])
    with pytest.raises(ValidationError):
        ReviewDetailedResponse(status="success", results=[finding()], total_risks=1, trace=[
            ReviewTraceEvent(sequence=2, node="critic", attempt=1, status="completed", duration_ms=0),
        ])


def test_new_cloud_guards_are_active_without_sending_requests():
    with pytest.raises(pytest.fail.Exception, match="never call cloud"):
        get_embeddings("mock")  # Creation itself is offline.
        # Synthetic key, but the guard must fire even if cloud mode is forced.
        from backend.app.services.embedding import SiliconFlowEmbeddings
        SiliconFlowEmbeddings(base_url="https://example.invalid", model="offline", api_key="sk-synthetic").embed_query("维修")
