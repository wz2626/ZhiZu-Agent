"""Review API, evidence grounding, privacy and bounded fallback behavior."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.main import app
from backend.app.schemas.review import ReviewResponse
from backend.app.services.embedding import DeterministicHashEmbeddings
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
    assert payload["法律依据"] == [{"id": "LAW-716", "正文": store.evidence[0].content}]


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
    assert [law["id"] for law in json.loads(llm.calls[0][1].content)["法律依据"]] == ["LAW-716"]


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
    json.dumps([finding(evidence_ids=["LAW-712"])]),
    json.dumps([finding(evidence_ids=["LAW-999"])]),
    json.dumps([finding(evidence_ids=["SCENARIO-01"])]),
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
        "api_key": "sk-synthetic-config-test", "temperature": 0,
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
