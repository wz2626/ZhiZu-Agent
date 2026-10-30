"""Offline proposal drafting, context ownership, bounded validation and retries."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.api.review import get_proposal_service, get_review_service
from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.schemas.proposal import ProposalRequest
from backend.app.schemas.review import ReviewClauseResult, ReviewEvidence, RiskLevel
from backend.app.services.proposal import (
    ProposalService, ProposalConflict, ProposalClauseMissing, ProposalCapacityExceeded,
)
from backend.app.services.review import ContractReviewService
from backend.app.services.review_context import ReviewContextStore, ReviewContextMissing
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws

TEXT = "租客未经房东同意擅自转租房屋。"
GOOD = dict(proposed_message="请核对转租授权，并明确可接受的协商安排。",
            evidence_ids=["LAW-716"], questions=["是否有书面授权？"])


def settings(key=""):
    return Settings("https://chat.invalid/v1", "offline", key,
                    "https://embedding.invalid/v1", "offline", "", "missing")


class LLM:
    def __init__(self, *values):
        self.values, self.calls = list(values), []

    def invoke(self, messages):
        self.calls.append(messages)
        value = self.values.pop(0) if self.values else GOOD
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))


def material():
    law = next(law for law in load_authoritative_laws() if law.law_id == "LAW-716")
    evidence = ReviewEvidence(article_no=law.article_no, law_name=law.law_name,
                              content=law.content, source_url=law.source_url, verified_date=law.verified_date)
    clause = ReviewClauseResult(clause_id="C-01", original_clause=TEXT, risk_level="HIGH",
                                explanation="请核对授权。", evidence_ids=["LAW-716"],
                                negotiation_tip="请明确转租授权。")
    return clause, {"LAW-716": evidence}


def setup(*outputs, store=None):
    store = store if store is not None else ReviewContextStore()
    clause, evidence = material()
    context_id = store.create(TEXT, [clause], evidence)
    llm = LLM(*outputs)
    service = ProposalService(context_store=store, llm=llm)
    request = ProposalRequest(review_context_id=context_id, clause_id="C-01",
                              goal_text="希望明确授权与通知安排。", draft_request_id="draft-1")
    return service, request, llm


@pytest.mark.parametrize("message", [
    "押金2000元，希望2026年11月5日前退还。",
    "希望2026-11-05退还1500元，交接后7个工作日结清。",
    "维修费1500元，我承担30%，房东承担70%。",
])
def test_business_amount_dates_and_percentages_are_not_private(message):
    from backend.app.core.privacy import redact_pii
    assert redact_pii(message) == message
    service, request, llm = setup({"proposed_message": message, "evidence_ids": [], "questions": []})
    response = service.generate(request.model_copy(update={"goal_text": message}))
    assert response.status == "success" and response.proposed_message == message
    assert message in llm.calls[0][1].content


@pytest.mark.parametrize("bad,expected", [
    ("not-json", "格式"),
    ({**GOOD, "proposed_message": "请联系13800000000。"}, "疑似个人号码"),
    ({**GOOD, "proposed_message": "依据第585条退还押金。"}, "法律依据"),
    ({**GOOD, "proposed_message": "长" * 2001}, "长度"),
])
def test_draft_failure_reports_safe_specific_output_reason(bad, expected):
    service, request, llm = setup(bad, bad, bad)
    response = service.generate(request)
    assert response.failure_code == "VALIDATION_FAILED"
    assert expected in response.reason
    assert expected in llm.calls[1][-1].content
    assert len(llm.calls) == 3 and response.retry_count == 2
    assert response.proposed_message == "" and response.questions == []
    assert "13800000000" not in response.model_dump_json()
    replay = service.generate(request)
    assert replay.replayed and replay.reason == response.reason and len(llm.calls) == 3


def test_success_contains_only_public_draft_and_actual_trace():
    service, request, llm = setup()
    response = service.generate(request)
    assert response.status == "success" and response.proposed_message == GOOD["proposed_message"]
    assert response.evidence_ids == ["LAW-716"] and response.retry_count == 0
    assert [event.node for event in response.trace] == ["context", "configuration", "drafting", "critic"]
    assert all(event.duration_ms >= 0 for event in response.trace)
    assert all("contract_text" not in event.model_dump() for event in response.trace)
    assert "candidate_terms" not in response.model_dump() and "trial_score" not in response.model_dump()
    assert len(llm.calls) == 1


@pytest.mark.parametrize("bad", [
    "broken", '{"proposed_message":"a","proposed_message":"b","evidence_ids":[],"questions":[]}',
    {**GOOD, "evidence_ids": ["LAW-721"]}, {**GOOD, "evidence_ids": ["LAW-999"]},
    {**GOOD, "evidence_ids": ["LAW-716", "LAW-716"]},
    {**GOOD, "proposed_message": "请联系13800000000。"},
    {**GOOD, "questions": ["身份证110101199001010011？"]},
    {**GOOD, "proposed_message": "依据第585条，请返还押金。"},
    {**GOOD, "proposed_message": "依据LAW-721，请返还押金。"},
    {**GOOD, "proposed_message": "依据第716条，请核对授权。", "evidence_ids": []},
    {**GOOD, "unexpected": "discard this candidate"},
    {**GOOD, "proposed_message": " "}, {**GOOD, "questions": [" "]},
    {**GOOD, "proposed_message": "长" * 2001},
    '[' * 1500 + '0' + ']' * 1500,
    'x' * 32001,
])
def test_invalid_drafts_are_bounded_and_never_exposed(bad):
    service, request, llm = setup(bad, bad, bad)
    response = service.generate(request)
    assert response.status == "needs_review" and response.failure_code == "VALIDATION_FAILED"
    assert response.proposed_message == "" and response.questions == [] and response.evidence_ids == []
    assert response.retry_count == 2 and len(llm.calls) == 3
    assert [event.attempt for event in response.trace if event.node == "drafting"] == [1, 2, 3]
    assert len([event for event in response.trace if event.node == "retry"]) == 2
    assert "13800000000" not in response.model_dump_json()
    assert "unexpected" not in response.model_dump_json()


@pytest.mark.parametrize("failures", [1, 2])
def test_rewrite_success_discards_rejected_candidate(failures):
    service, request, llm = setup(*(["bad"] * failures), GOOD)
    response = service.generate(request)
    assert response.status == "success" and response.retry_count == failures
    assert response.errors == [] and len(llm.calls) == failures + 1
    assert [event.status for event in response.trace if event.node == "critic"] == ["retry"] * failures + ["completed"]


@pytest.mark.parametrize("error,code", [(TimeoutError("private key 13800000000"), "CHAT_TIMEOUT"),
                                        (RuntimeError("private key 13800000000"), "CHAT_CALL_FAILED")])
def test_upstream_errors_are_safe_and_cached(error, code):
    service, request, llm = setup(error)
    response = service.generate(request)
    replay = service.generate(request)
    assert response.status == "needs_review" and response.failure_code == code
    assert replay.replayed and replay.trace == response.trace and len(llm.calls) == 1
    assert "private" not in replay.model_dump_json() and "13800000000" not in replay.model_dump_json()
    if code == "CHAT_TIMEOUT":
        assert "新的生成请求" in response.reason and "重试同一请求" not in response.reason


def test_replay_conflicts_and_concurrent_duplicates():
    service, request, llm = setup()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: service.generate(request), range(4)))
    assert len(llm.calls) == 1 and sum(not response.replayed for response in responses) == 1
    first = next(item for item in responses if not item.replayed)
    assert all(item.trace == first.trace for item in responses)
    with pytest.raises(ProposalConflict):
        service.generate(request.model_copy(update={"goal_text": "不同诉求"}))


def test_request_cache_is_context_scoped_and_old_request_is_stable():
    service, request, llm = setup()
    first = service.generate(request)
    service.generate(request.model_copy(update={"draft_request_id": "draft-2", "goal_text": "另一个目标"}))
    replay = service.generate(request)
    assert replay.model_dump(exclude={"replayed"}) == first.model_dump(exclude={"replayed"})
    other = service.context_store.create(TEXT, [material()[0]], material()[1])
    assert not service.generate(request.model_copy(update={"review_context_id": other})).replayed
    assert len(llm.calls) == 3


def test_goal_and_context_are_redacted_before_model_and_cache():
    service, request, llm = setup()
    service.generate(request.model_copy(update={"goal_text": "请联系13800000000，身份证110101199001010011。"}))
    prompt = "".join(message.content for message in llm.calls[0])
    assert "13800000000" not in prompt and "110101199001010011" not in prompt
    cached_goal = service.context_store.get(request.review_context_id).requests["draft-1"][1]
    assert cached_goal == "请联系***，身份证***。"


def test_missing_or_wrong_clause_is_rejected_before_model_configuration(monkeypatch):
    service, request, llm = setup()
    monkeypatch.setattr("backend.app.services.proposal.ChatOpenAI", lambda **_: pytest.fail("must not initialize"))
    service.llm = None
    with pytest.raises(ReviewContextMissing):
        service.generate(request.model_copy(update={"review_context_id": "a" * 32}))
    with pytest.raises(ProposalClauseMissing):
        service.generate(request.model_copy(update={"clause_id": "C-02"}))
    assert llm.calls == []


def test_context_expiry_capacity_and_detached_results():
    now = [0.0]
    store = ReviewContextStore(ttl_seconds=10, capacity=2, clock=lambda: now[0])
    first = store.create(TEXT, [material()[0]], material()[1])
    second = store.create(TEXT, [material()[0]], material()[1])
    store.get(first)
    third = store.create(TEXT, [material()[0]], material()[1])
    with pytest.raises(ReviewContextMissing):
        store.get(second)
    assert store.get(first) and store.get(third)
    now[0] = 10.0
    with pytest.raises(ReviewContextMissing):
        store.get(first)


def test_request_capacity_is_bounded(monkeypatch):
    monkeypatch.setattr("backend.app.services.proposal._REQUEST_LIMIT", 1)
    service, request, llm = setup()
    service.generate(request)
    assert service.generate(request).replayed
    with pytest.raises(ProposalCapacityExceeded):
        service.generate(request.model_copy(update={"draft_request_id": "draft-2"}))
    assert len(llm.calls) == 1


def test_absent_configuration_is_honest_failure_without_model_call():
    service, request, llm = setup()
    service.llm, service.settings = None, settings("")
    result = service.generate(request)
    assert result.failure_code == "CHAT_NOT_CONFIGURED"
    assert [event.node for event in result.trace] == ["context", "configuration"]
    assert llm.calls == []


def test_client_initialization_error_is_safe(monkeypatch):
    service, request, _ = setup()
    service.llm, service.settings = None, settings("sk-offline")
    def broken(**_kwargs):
        raise RuntimeError("do not expose 13800000000")
    monkeypatch.setattr("backend.app.services.proposal.ChatOpenAI", broken)
    result = service.generate(request)
    assert result.failure_code == "CHAT_INIT_FAILED" and "13800000000" not in result.model_dump_json()


def test_invalid_configuration_is_also_a_safe_cached_failure(monkeypatch):
    service, request, _ = setup()
    service.llm = None
    def invalid():
        raise ValueError("private configuration 13800000000")
    monkeypatch.setattr("backend.app.services.proposal.get_settings", invalid)
    result = service.generate(request)
    assert result.failure_code == "CHAT_INIT_FAILED" and "13800000000" not in result.model_dump_json()
    assert service.generate(request).replayed


def test_no_evidence_context_can_propose_clarifying_message():
    service, request, llm = setup({**GOOD, "evidence_ids": []})
    clause = material()[0].model_copy(update={"evidence_ids": [], "risk_level": RiskLevel.NONE})
    context_id = service.context_store.create(TEXT, [clause], {})
    response = service.generate(request.model_copy(update={"review_context_id": context_id}))
    assert response.status == "success" and response.evidence_ids == []
    payload = json.loads(llm.calls[0][1].content)
    assert payload["evidence_by_id"] == {}


@pytest.mark.parametrize("message", ["针对合同第二条，请进一步明确转租授权。", "请核对租约中的第十二条。"])
def test_contract_clause_numbers_are_not_mistaken_for_statutory_citations(message):
    service, request, _ = setup({**GOOD, "proposed_message": message})
    assert service.generate(request).status == "success"


@pytest.fixture
def http():
    service, request, llm = setup()
    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_proposal_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service, request, llm
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


def test_http_statuses_and_validation_do_not_echo_private_inputs(http):
    client, _service, request, _llm = http
    body = request.model_dump()
    assert client.post("/api/review/proposal", json=body).status_code == 200
    assert client.post("/api/review/proposal", json={**body, "goal_text": "另一个目标"}).status_code == 409
    assert client.post("/api/review/proposal", json={**body, "clause_id": "C-02"}).status_code == 409
    assert client.post("/api/review/proposal", json={**body, "clause_id": "C-02", "draft_request_id": "unknown-clause"}).status_code == 404
    assert client.post("/api/review/proposal", json={**body, "review_context_id": "a" * 32}).status_code == 410
    for change in [{"goal_text": " "}, {"goal_text": 123}, {"goal_text": "长" * 2001},
                   {"trusted_evidence_ids": ["LAW-716"]}, {"draft_request_id": "13800000000"}]:
        response = client.post("/api/review/proposal", json={**body, **change})
        assert response.status_code == 422 and "13800000000" not in response.text


def test_http_review_to_proposal_and_legacy_openapi_is_unambiguous(http):
    client, service, _request, llm = http
    law = next(law for law in load_authoritative_laws() if law.law_id == "LAW-716")
    store = SimpleNamespace(get_status=lambda: SimpleNamespace(is_ready=True),
                            search_evidence=lambda *_args, **_kwargs: [LawVectorStoreService._evidence(law, .8)])
    finding = material()[0].model_dump(mode="json")
    review = ContractReviewService(settings=settings("sk-offline"), vector_store=store,
                                    llm=LLM([finding]), context_store=service.context_store)
    app.dependency_overrides[get_review_service] = lambda: review
    response = client.post("/api/review/analyze-detailed", json={"contract_text": TEXT}).json()
    assert response["status"] == "success" and set(response["evidence_by_id"]) == {"LAW-716"}
    proposal = client.post("/api/review/proposal", json={
        "review_context_id": response["review_context_id"], "clause_id": "C-01",
        "goal_text": "请明确授权", "draft_request_id": "chain-1",
    })
    assert proposal.status_code == 200 and proposal.json()["status"] == "success"
    schema = client.get("/openapi.json").json()
    matches = []
    for path, methods in schema["paths"].items():
        body = methods.get("post", {}).get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if "$ref" in body:
            body = schema["components"]["schemas"][body["$ref"].split("/")[-1]]
        if {"session_id", "user_input", "request_id"} <= set(body.get("properties", {})):
            matches.append(path)
    assert matches == ["/api/negotiation/turn"]
    assert set(schema["components"]["schemas"]["ReviewClauseResult"]["properties"]) == set(ReviewClauseResult.model_fields)
    assert len(llm.calls) == 1
