"""Review API, evidence grounding, privacy and bounded fallback behavior."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.main import app
from backend.app.schemas.review import ReviewResponse
from backend.app.services.embedding import DeterministicHashEmbeddings
from backend.app.services.graph import review_graph
from backend.app.services.review import ContractReviewService
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws, mask_sensitive_text

CONTRACT = "租客每月按约支付租金。租客未经房东同意擅自转租房屋。"
RISK_CLAUSE = "租客未经房东同意擅自转租房屋。"


@pytest.fixture(autouse=True)
def isolated_review_environment(monkeypatch, tmp_path):
    for key, value in {
        "CHAT_API_KEY": "", "CHAT_BASE_URL": "https://chat.example.invalid/v1",
        "CHAT_MODEL": "test-review-model", "EMBEDDING_API_KEY": "",
        "CHROMA_PATH": str(tmp_path / "missing_chroma"),
    }.items():
        monkeypatch.setenv(key, value)

    def unexpected_cloud_call(*args, **kwargs):
        pytest.fail("review unit tests must not call cloud APIs")

    monkeypatch.setattr("backend.app.services.review.ChatOpenAI.invoke", unexpected_cloud_call)
    monkeypatch.setattr("backend.app.services.embedding.httpx.post", unexpected_cloud_call)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def finding(risk_level="HIGH", **overrides):
    result = {
        "clause_id": "C-01", "original_clause": RISK_CLAUSE,
        "risk_level": risk_level,
        "explanation": "未经出租人同意转租，出租人可以解除合同。",
        "evidence_ids": ["LAW-716"],
        "negotiation_tip": "协商取得出租人的书面转租同意。",
    }
    result.update(overrides)
    return result


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response)


class FakeStore:
    def __init__(self, evidence=None, ready=True, error=None):
        laws = {law.law_id: law for law in load_authoritative_laws()}
        self.evidence = evidence if evidence is not None else [
            LawVectorStoreService._evidence(laws["LAW-716"], 0.6),
        ]
        self.ready = ready
        self.error = error
        self.calls = []

    def get_status(self):
        return SimpleNamespace(is_ready=self.ready)

    def search_evidence(self, query, top_k=4):
        self.calls.append((query, top_k))
        if self.error:
            raise self.error
        return self.evidence


def real_mode_service(monkeypatch, llm, store=None):
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-review-test")
    return ContractReviewService(vector_store=store if store is not None else FakeStore(), llm=llm)


def assert_mock(response, text):
    assert response.status == "mock"
    assert response.total_risks == 1
    assert [item.risk_level.value for item in response.results] == ["HIGH", "NONE"]
    for item in response.results:
        assert item.original_clause.strip() and item.original_clause in mask_sensitive_text(text)
        assert "Mock" in item.explanation
        assert all(re.fullmatch(r"LAW-(70[3-9]|71\d|72\d|73[0-4])", law_id) for law_id in item.evidence_ids)


def test_mock_api_returns_valid_json_without_storage_or_cloud(client, monkeypatch):
    def unexpected_dependency(*args, **kwargs):
        pytest.fail("missing chat key must skip storage and chat initialization")

    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-synthetic-embedding-configured")
    monkeypatch.setattr("backend.app.services.review.LawVectorStoreService", unexpected_dependency)
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", unexpected_dependency)
    response = client.post("/api/review/analyze", json={"contract_text": CONTRACT})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) == {"status", "results", "total_risks"}
    assert_mock(ReviewResponse.model_validate(response.json()), CONTRACT)
    assert not Path(get_settings().chroma_path).exists()


@pytest.mark.parametrize("text", ["", "短合同", "文" * 9, "文" * 5001, " " * 10, None, 123])
def test_invalid_contract_returns_422(client, text):
    assert client.post("/api/review/analyze", json={"contract_text": text}).status_code == 422


def test_missing_contract_returns_422(client):
    assert client.post("/api/review/analyze", json={}).status_code == 422


@pytest.mark.parametrize("text", ["文" * 10, "文" * 5000])
def test_contract_length_boundaries_are_accepted(client, text):
    response = client.post("/api/review/analyze", json={"contract_text": text})
    assert response.status_code == 200
    assert_mock(ReviewResponse.model_validate(response.json()), text)


@pytest.mark.parametrize("top_k", [0, -1, 9, True, "4", 1.5, None])
def test_invalid_top_k_returns_422(client, top_k):
    assert client.post("/api/review/analyze", json={"contract_text": CONTRACT, "top_k": top_k}).status_code == 422


@pytest.mark.parametrize("key", ["", " ", "YOUR_CHAT_API_KEY", "placeholder", "replace_me", "请填入密钥", "示例密钥"])
def test_missing_and_placeholder_chat_keys_use_mock(monkeypatch, key):
    monkeypatch.setenv("CHAT_API_KEY", key)
    llm, store = FakeLLM(), FakeStore()
    assert_mock(ContractReviewService(vector_store=store, llm=llm).analyze_contract(CONTRACT), CONTRACT)
    assert llm.calls == store.calls == []


@pytest.mark.parametrize("text", [CONTRACT, "双方约定每月五日支付当月租金", "         甲", "13800138000"])
def test_mock_clauses_always_locate_in_masked_input(text):
    assert_mock(ContractReviewService().analyze_contract(text), text)


@pytest.mark.parametrize("top_k", [1, 4, 8])
def test_success_uses_retrieved_law_text_ids_and_requested_top_k(monkeypatch, top_k):
    llm, store = FakeLLM(json.dumps([finding()], ensure_ascii=False)), FakeStore()
    service = real_mode_service(monkeypatch, llm, store)
    response = service.analyze_contract(CONTRACT, top_k=top_k)
    assert response.status == "success" and response.total_risks == 1
    assert response.results[0].original_clause in CONTRACT
    assert response.results[0].evidence_ids == ["LAW-716"]
    assert store.calls == [(CONTRACT, top_k)]
    system, human = llm.calls[0]
    assert "不得输出 Markdown" in system.content
    assert "JSON 数组" in system.content and "没有直接规定押金返还" in system.content
    payload = json.loads(human.content)
    assert payload["合同文本"] == CONTRACT
    assert payload["法律依据"] == [{"law_id": "LAW-716", "正文": store.evidence[0].content}]


def test_risk_count_is_computed_for_all_risk_levels(monkeypatch):
    clauses = ["甲方负责按约维修房屋。", "乙方应当按时支付租金。", "双方共同核对设施状况。", "期满办理房屋返还手续。"]
    results = [finding(level, clause_id=f"C-{index:02d}", original_clause=clause)
               for index, (level, clause) in enumerate(zip(["HIGH", "MEDIUM", "LOW", "NONE"], clauses), 1)]
    response = real_mode_service(monkeypatch, FakeLLM(json.dumps(results))).analyze_contract("".join(clauses))
    assert response.status == "success" and response.total_risks == 3


def test_no_risk_review_can_have_empty_details(monkeypatch):
    llm = FakeLLM(json.dumps([finding("NONE", explanation="", negotiation_tip="", evidence_ids=[])]))
    response = real_mode_service(monkeypatch, llm).analyze_contract(CONTRACT)
    assert response.status == "success" and response.total_risks == 0


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf"), 0, -0.1, 1.1, True, "0.6", None])
def test_anomalous_scores_are_filtered_before_prompt(monkeypatch, score):
    store = FakeStore()
    bad = store.evidence[0].model_copy(update={"score": score, "evidence_id": "LAW-712"})
    store.evidence = [bad, store.evidence[0]]
    llm = FakeLLM(json.dumps([finding()]))
    response = real_mode_service(monkeypatch, llm, store).analyze_contract(CONTRACT)
    assert response.status == "success"
    assert [law["law_id"] for law in json.loads(llm.calls[0][1].content)["法律依据"]] == ["LAW-716"]


def test_small_positive_score_is_not_arbitrarily_dropped(monkeypatch):
    store = FakeStore()
    store.evidence = [store.evidence[0].model_copy(update={"score": 0.01})]
    response = real_mode_service(monkeypatch, FakeLLM(json.dumps([finding()])), store).analyze_contract(CONTRACT)
    assert response.status == "success"


def test_untrusted_law_content_ids_and_duplicates_do_not_enter_prompt(monkeypatch):
    store = FakeStore()
    valid = store.evidence[0]
    store.evidence = [valid.model_copy(update={"content": "伪造正文"}),
                      valid.model_copy(update={"evidence_id": "SCENARIO-REVIEW-01"}), valid, valid]
    llm = FakeLLM(json.dumps([finding()]))
    assert real_mode_service(monkeypatch, llm, store).analyze_contract(CONTRACT).status == "success"
    assert len(json.loads(llm.calls[0][1].content)["法律依据"]) == 1


@pytest.mark.parametrize("bad_output", [
    "not JSON", "```json\n[]\n```", "[]", "{}", "null", ["content block"],
    json.dumps([finding(original_clause="凭空生成的原文")]),
    json.dumps([finding(evidence_ids="LAW-716")]),
    json.dumps([finding(evidence_ids=[None])]),
    json.dumps([finding(evidence_ids=[{"law_id": "LAW-716"}])]),
    json.dumps([finding(risk_level="CRITICAL")]),
    json.dumps([finding(explanation="", negotiation_tip="")]),
    json.dumps([finding(), finding()]),
    json.dumps([finding(extra_field="not allowed")]),
    json.dumps([finding(explanation="联系13800138000确认")]),
])
def test_invalid_generation_retries_once_then_accepts_valid_json(monkeypatch, bad_output):
    llm = FakeLLM(bad_output, json.dumps([finding()]))
    response = real_mode_service(monkeypatch, llm).analyze_contract(CONTRACT)
    assert response.status == "success" and len(llm.calls) == 2
    assert "重新生成完整 JSON 数组" in llm.calls[1][-1].content


def test_validation_failure_stops_after_three_generations(monkeypatch):
    llm = FakeLLM("broken", "broken", "broken")
    assert_mock(real_mode_service(monkeypatch, llm).analyze_contract(CONTRACT), CONTRACT)
    assert len(llm.calls) == 3


def test_second_rewrite_can_succeed(monkeypatch):
    llm = FakeLLM("broken", "broken", json.dumps([finding()]))
    assert real_mode_service(monkeypatch, llm).analyze_contract(CONTRACT).status == "success"
    assert len(llm.calls) == 3


def test_chat_failure_degrades_without_exposing_secrets(monkeypatch, caplog):
    secret = "sk-synthetic-sensitive-error"
    llm = FakeLLM(RuntimeError(secret))
    response = real_mode_service(monkeypatch, llm).analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert len(llm.calls) == 1
    assert secret not in response.model_dump_json() + caplog.text


@pytest.mark.parametrize("store", [FakeStore(evidence=[]), FakeStore(ready=False), FakeStore(error=RuntimeError("synthetic-failure"))])
def test_unavailable_or_empty_evidence_degrades_without_chat(monkeypatch, store):
    llm = FakeLLM()
    assert_mock(real_mode_service(monkeypatch, llm, store).analyze_contract(CONTRACT), CONTRACT)
    assert llm.calls == []


def test_redaction_precedes_retrieval_and_chat(monkeypatch, client):
    text = "租客联系13800138000，身份证110101199001011234。" + CONTRACT
    safe_text = mask_sensitive_text(text)
    llm, store = FakeLLM(json.dumps([finding()])), FakeStore()
    service = real_mode_service(monkeypatch, llm, store)
    result = service.analyze_contract(text)
    assert result.status == "success"
    assert store.calls == [(safe_text, 4)]
    assert json.loads(llm.calls[0][1].content)["合同文本"] == safe_text
    response = client.post("/api/review/analyze", json={"contract_text": text})
    assert response.status_code == 200  # Missing KB in real mode also has a safe fallback.
    for value in (response.text, result.model_dump_json(), llm.calls[0][1].content):
        assert "13800138000" not in value and "110101199001011234" not in value
    assert_mock(ReviewResponse.model_validate(response.json()), text)


def test_chat_initialization_failure_is_mock_200(client, monkeypatch, caplog):
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-review-configured")

    def failed_client(**kwargs):
        raise ValueError("sk-synthetic-init-error")

    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", failed_client)
    response = client.post("/api/review/analyze", json={"contract_text": CONTRACT})
    assert response.status_code == 200
    assert_mock(ReviewResponse.model_validate(response.json()), CONTRACT)
    assert "sk-synthetic-init-error" not in response.text + caplog.text


def test_chat_client_uses_config_and_disables_hidden_retries(monkeypatch):
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-config-test")
    calls, closed = [], []

    def fake_client(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(root_client=SimpleNamespace(close=lambda: closed.append(True)))

    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", fake_client)
    service = ContractReviewService()
    assert calls == [{
        "base_url": "https://chat.example.invalid/v1", "model": "test-review-model",
        "api_key": "sk-synthetic-config-test", "temperature": 0.1,
        "timeout": 20.0, "max_retries": 0, "use_responses_api": False,
    }]
    service.close()
    service.close()
    assert closed == [True]


def test_cleanup_failure_preserves_mock_200_and_hides_error(client, monkeypatch, caplog):
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-cleanup-test")

    def failed_close():
        raise RuntimeError("sk-synthetic-cleanup-error")

    llm = FakeLLM()
    llm.root_client = SimpleNamespace(close=failed_close)
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", lambda **kwargs: llm)
    response = client.post("/api/review/analyze", json={"contract_text": CONTRACT})
    assert response.status_code == 200
    assert_mock(ReviewResponse.model_validate(response.json()), CONTRACT)
    assert not Path(get_settings().chroma_path).exists()
    assert "sk-synthetic-cleanup-error" not in response.text + caplog.text


def test_api_runs_local_rag_with_fake_chat_and_closes_owned_store(client, monkeypatch, tmp_path):
    directory = tmp_path / "review_chroma"
    monkeypatch.setenv("CHROMA_PATH", str(directory))
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-rag-test")
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as store:
        store.ingest_laws()
    llm, closed = FakeLLM(json.dumps([finding()])), []
    llm.root_client = SimpleNamespace(close=lambda: closed.append("chat"))
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", lambda **kwargs: llm)
    original_close = LawVectorStoreService.close

    def tracked_close(store):
        closed.append("store")
        original_close(store)

    monkeypatch.setattr(LawVectorStoreService, "close", tracked_close)
    response = client.post("/api/review/analyze", json={"contract_text": CONTRACT, "top_k": 8})
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert response.json()["results"][0]["evidence_ids"] == ["LAW-716"]
    assert closed == ["store", "chat"]


def test_sample_scenarios_remain_reference_data(client):
    scenarios = json.loads((PROJECT_ROOT / "backend/data/scenarios/sample_contracts.json").read_text(encoding="utf-8"))
    assert len(scenarios) == 2
    assert len({item["scenario_id"] for item in scenarios}) == 2
    assert any("押金不退" in item["contract_text"] and "擅自转租" in item["contract_text"] for item in scenarios)
    for item in scenarios:
        assert "不作为法律依据" in item["usage"]
        assert mask_sensitive_text(item["contract_text"]) == item["contract_text"]
        response = client.post("/api/review/analyze", json={"contract_text": item["contract_text"]})
        assert response.status_code == 200
        assert_mock(ReviewResponse.model_validate(response.json()), item["contract_text"])
    assert len(load_authoritative_laws()) == 32


@pytest.fixture
def configured_chat_service(monkeypatch):
    """Build the actual SDK client; every invocation remains intercepted."""
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-real-client-test")
    service = ContractReviewService(vector_store=FakeStore())
    assert isinstance(service.llm, ChatOpenAI)
    assert not service.mock_mode
    try:
        yield service
    finally:
        service.close()


def test_chatopenai_invoke_parses_success_and_uses_masked_prompt(configured_chat_service):
    text = "租客联系13800138000，身份证110101199001011234。" + CONTRACT
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(
        content=json.dumps([finding()], ensure_ascii=False),
    )) as invoke:
        response = configured_chat_service.analyze_contract(text, top_k=8)
    invoke.assert_called_once()
    assert response.status == "success" and response.total_risks == 1
    assert response.results[0].original_clause in mask_sensitive_text(text)
    assert response.results[0].evidence_ids == ["LAW-716"]
    assert configured_chat_service.llm.temperature == 0.1
    assert configured_chat_service.llm.max_retries == 0
    system, human = invoke.call_args.args[0]
    assert "严苛的中国合同法务专家" in system.content
    assert "不得输出 Markdown" in system.content
    assert "没有直接规定押金返还" in system.content
    payload = json.loads(human.content)
    assert payload["合同文本"] == mask_sensitive_text(text)
    assert payload["法律依据"] == [{
        "law_id": "LAW-716", "正文": configured_chat_service.vector_store.evidence[0].content,
    }]
    assert configured_chat_service.vector_store.calls == [(mask_sensitive_text(text), 8)]


@pytest.mark.parametrize("wrapper", [" \n%s\t ", "```json\n%s\n```", " \n```\n%s\n```\t "])
def test_chatopenai_complete_fences_are_cleaned_without_retry(configured_chat_service, wrapper):
    clause = "双方记录备注为 json 与 ``` 字符，不改变原条款。"
    content = json.dumps([finding(original_clause=clause)], ensure_ascii=False)
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(content=wrapper % content)) as invoke:
        response = configured_chat_service.analyze_contract(clause)
    assert response.status == "success"
    assert response.results[0].original_clause == clause  # Preserve data inside the array.
    invoke.assert_called_once()


def test_chatopenai_three_json_decode_failures_trip_mock_fallback(configured_chat_service):
    with patch("langchain_openai.ChatOpenAI.invoke", side_effect=[
        AIMessage(content="第一轮乱码"), AIMessage(content="第二轮乱码"), AIMessage(content="第三轮乱码"),
    ]) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert invoke.call_count == 3
    # The last request contains the two bounded rewrite instructions.
    assert len(invoke.call_args.args[0]) == 4
    assert len(configured_chat_service.vector_store.calls) == 1


@pytest.mark.parametrize("invalid_attempts", [1, 3])
def test_chatopenai_tampered_clause_retries_and_has_finite_exit(configured_chat_service, invalid_attempts):
    responses = [AIMessage(content=json.dumps([finding(original_clause="模型改写的原句")]))] * invalid_attempts
    if invalid_attempts < 3:
        responses.append(AIMessage(content=json.dumps([finding()])))
    with patch("langchain_openai.ChatOpenAI.invoke", side_effect=responses) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert invoke.call_count == min(invalid_attempts + 1, 3)
    if invalid_attempts == 3:
        assert_mock(response, CONTRACT)
    else:
        assert response.status == "success"
        assert response.results[0].original_clause == RISK_CLAUSE


@pytest.mark.parametrize("citations", [
    ["LAW-716", "LAW-999"], ["LAW-712", "LAW-716", "LAW-716"], ["SCENARIO-01", "LAW-716"],
])
def test_chatopenai_filters_invented_and_unretrieved_ids(configured_chat_service, citations):
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(
        content=json.dumps([finding(evidence_ids=citations)]),
    )) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert response.status == "success" and response.total_risks == 1
    assert response.results[0].evidence_ids == ["LAW-716"]
    assert response.results[0].risk_level.value == "HIGH"
    invoke.assert_called_once()


@pytest.mark.parametrize("citations", [[], ["LAW-999"], ["LAW-712"], ["SCENARIO-01"]])
def test_chatopenai_high_without_retrieved_evidence_retries_then_is_mock(configured_chat_service, citations):
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(
        content=json.dumps([finding(evidence_ids=citations)]),
    )) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert all(item.evidence_ids == [] for item in response.results)
    assert invoke.call_count == 3


@pytest.mark.parametrize("level", ["MEDIUM", "LOW", "NONE"])
def test_chatopenai_lower_levels_never_keep_unretrieved_citations(configured_chat_service, level):
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(content=json.dumps([
        finding(level, evidence_ids=["LAW-712", "LAW-999"], explanation="直接依据不足，需要补充材料。"),
    ]))) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert response.status == "success"
    assert response.results[0].evidence_ids == []
    assert response.total_risks == (0 if level == "NONE" else 1)
    invoke.assert_called_once()


@pytest.mark.parametrize("wrapper", [
    "n%ss", "```json\n%s", "```python\n%s\n```", "审查结果：%s", "%s审查结束",
    "%s[]", "`%s`",
])
def test_chatopenai_cleanup_does_not_accept_damaged_or_extra_text(configured_chat_service, wrapper):
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(
        content=wrapper % json.dumps([finding()]),
    )) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert invoke.call_count == 3


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_chatopenai_rejects_nonstandard_json_constants(configured_chat_service, constant):
    content = json.dumps([finding()]).replace('"HIGH"', constant)
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(content=content)) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert invoke.call_count == 3


def test_chatopenai_rejects_duplicate_json_keys(configured_chat_service):
    content = json.dumps([finding()]).replace('"risk_level": "HIGH"', '"risk_level": "NONE", "risk_level": "HIGH"')
    with patch("langchain_openai.ChatOpenAI.invoke", return_value=AIMessage(content=content)) as invoke:
        response = configured_chat_service.analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert invoke.call_count == 3


def graph_input(text=CONTRACT):
    return {
        "contract_text": mask_sensitive_text(text), "evidence_list": FakeStore().evidence,
        "current_draft": None, "errors": [], "retry_count": 0,
        "final_results": [], "status": "drafting", "messages": [],
        "retry_pending": False,
    }


def test_service_invokes_compiled_graph_with_masked_text_and_filtered_evidence(monkeypatch):
    text = "联系电话13800138000。" + CONTRACT
    store = FakeStore()
    store.evidence.insert(0, store.evidence[0].model_copy(update={"content": "伪造法条"}))
    llm = FakeLLM(json.dumps([finding()]))
    service = real_mode_service(monkeypatch, llm, store)
    with patch("backend.app.services.review.review_graph.invoke", wraps=review_graph.invoke) as invoke:
        response = service.analyze_contract(text)
    invoke.assert_called_once()
    initial = invoke.call_args.args[0]
    assert initial["contract_text"] == mask_sensitive_text(text)
    assert len(initial["evidence_list"]) == 1
    assert initial["retry_count"] == 0 and initial["errors"] == []
    assert invoke.call_args.kwargs["context"] == {"llm": llm}
    assert set(response.model_dump()) == {"status", "results", "total_risks"}
    assert response.status == "success"


@pytest.mark.parametrize("invalid_attempts", [0, 1, 2])
def test_graph_runs_actual_nodes_and_only_commits_valid_findings(invalid_attempts):
    llm = FakeLLM(*([json.dumps([finding(original_clause="模型改写的原句")])] * invalid_attempts),
                  json.dumps([finding()]))
    events = list(review_graph.stream(graph_input(), context={"llm": llm}, stream_mode="updates"))
    assert [next(iter(event)) for event in events] == ["drafting", "critic"] * (invalid_attempts + 1)
    reviews = [event["critic"] for event in events if "critic" in event]
    for index, review in enumerate(reviews[:-1], 1):
        assert review["status"] == "needs_review" and review["retry_count"] == index
        assert review["final_results"] == []
        assert "original clause" in review["errors"][0]
        assert review["errors"][0] in llm.calls[index][-1].content
    assert reviews[-1]["status"] == "success" and reviews[-1]["errors"] == []
    assert reviews[-1]["final_results"][0].original_clause == RISK_CLAUSE


def test_graph_exhaustion_keeps_needs_review_reason_and_discards_invalid_draft():
    llm = FakeLLM("broken", "broken", "broken")
    state = review_graph.invoke(graph_input(), context={"llm": llm})
    assert len(llm.calls) == 3
    assert state["retry_count"] == 2 and state["status"] == "needs_review"
    assert state["errors"] and "JSON" in state["errors"][0]
    assert state["final_results"] == [] and state["current_draft"] is None
    assert not state["retry_pending"]


def test_graph_failure_runs_mock_node_without_additional_chat_calls():
    llm = FakeLLM(RuntimeError("sk-synthetic-private-error"))
    events = list(review_graph.stream(graph_input(), context={"llm": llm}, stream_mode="updates"))
    assert [next(iter(event)) for event in events] == ["drafting", "mock"]
    assert events[-1]["mock"]["status"] == "needs_review"
    assert len(llm.calls) == 1
    assert "sk-synthetic-private-error" not in str(events)


@pytest.mark.parametrize("invalid_field", ["original_clause", "explanation", "extra_field"])
def test_critic_feedback_does_not_echo_untrusted_output(invalid_field):
    private = "sk-synthetic-private-model-output 13800138000"
    bad = finding(**{invalid_field: {"untrusted": private} if invalid_field == "explanation" else private})
    llm = FakeLLM(json.dumps([bad]), json.dumps([finding()]))
    state = review_graph.invoke(graph_input(), context={"llm": llm})
    assert state["status"] == "success" and len(llm.calls) == 2
    assert private not in " ".join(message.content for message in llm.calls[1])
    assert private not in str(state["errors"]) + str(state["final_results"])


def test_critic_ungrounded_high_can_succeed_only_after_citation_is_fixed():
    llm = FakeLLM(json.dumps([finding(evidence_ids=["LAW-999"])]), json.dumps([finding()]))
    state = review_graph.invoke(graph_input(), context={"llm": llm})
    assert state["status"] == "success" and state["retry_count"] == 1
    assert len(llm.calls) == 2
    assert "HIGH finding has no retrieved evidence" in llm.calls[1][-1].content
    assert state["final_results"][0].evidence_ids == ["LAW-716"]


def test_reused_graph_does_not_share_errors_messages_or_retries_between_requests():
    failed = review_graph.invoke(graph_input(), context={"llm": FakeLLM("bad", "bad", "bad")})
    llm = FakeLLM(json.dumps([finding()]))
    succeeded = review_graph.invoke(graph_input(), context={"llm": llm})
    assert failed["status"] == "needs_review" and failed["retry_count"] == 2
    assert succeeded["status"] == "success" and succeeded["retry_count"] == 0
    assert succeeded["errors"] == [] and len(llm.calls[0]) == 2


@pytest.mark.parametrize("failure", ["needs_review", "exception"])
def test_service_graph_failure_preserves_mock_api_and_hides_internal_reason(monkeypatch, caplog, failure):
    private = "sk-synthetic-graph-error"
    service = real_mode_service(monkeypatch, FakeLLM())
    outcome = ({"return_value": {"status": "needs_review", "errors": [private], "final_results": []}}
               if failure == "needs_review" else {"side_effect": RuntimeError(private)})
    with patch("backend.app.services.review.review_graph.invoke", **outcome):
        response = service.analyze_contract(CONTRACT)
    assert_mock(response, CONTRACT)
    assert set(response.model_dump()) == {"status", "results", "total_risks"}
    assert private not in response.model_dump_json() + caplog.text
