"""V4 visible payload, answer ownership and restart-safe replay regressions."""

import json
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.negotiation import get_negotiation_service
from backend.app.api.review import get_proposal_service
from backend.app.core.privacy import redact_pii, redact_report
from backend.app.main import app
from backend.app.schemas.proposal import ProposalRequest
from backend.app.services.negotiation_graph import build_negotiation_graph, scenario_landlord_responder
from backend.app.services.negotiation_service import NegotiationService, NegotiationRoundConflict
from test_proposal import setup, GOOD


@pytest.fixture
def client():
    service = NegotiationService(build_negotiation_graph(landlord_responder=scenario_landlord_responder), public_api=True)
    app.dependency_overrides[get_negotiation_service] = lambda: service
    with TestClient(app) as value:
        yield value, service
    app.dependency_overrides.clear()


def body(request_id="turn-1"):
    return dict(session_id="v4-session", request_id=request_id, scenario="deposit", user_input="请核对押金返还安排。")


def headers(client, expected=0):
    meta = client.get("/api/negotiation/meta").json()
    return {"X-Interaction-Version": "4", "X-Practice-Epoch": meta["practice_epoch"], "X-Expected-Round": str(expected)}


def test_preview_does_not_consume_request_or_execute_graph(client):
    http, service = client
    request, control = body(), headers(http)
    request["user_input"] = "联系" + "1" + "0" * 10
    response = http.post("/api/negotiation/turn", json=request, headers=control)
    assert response.status_code == 428 and response.headers["cache-control"] == "no-store"
    detail = response.json()["detail"]
    assert detail["code"] == "PRIVACY_PREVIEW_REQUIRED"
    assert detail["fields"][0]["counts"]["phone"] == 1
    assert not service._sessions
    request["user_input"] = detail["fields"][0]["safe_text"]
    assert http.post("/api/negotiation/turn", json=request, headers=control).json()["round_count"] == 1


def test_replay_precedes_baseline_check_and_old_epoch_never_creates_session(client):
    http, service = client
    request, control = body(), headers(http)
    first = http.post("/api/negotiation/turn", json=request, headers=control).json()
    replay = http.post("/api/negotiation/turn", json=request, headers=control).json()
    assert replay["replayed"] and replay["turn_effect"] == first["turn_effect"]
    conflict = http.post("/api/negotiation/turn", json=body("turn-2"), headers=control)
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "ROUND_CONFLICT"
    control["X-Practice-Epoch"] = "old-instance"
    request["session_id"] = "must-not-create"
    stale = http.post("/api/negotiation/turn", json=request, headers=control)
    assert stale.json()["detail"]["code"] == "SESSION_INVALID"
    assert "must-not-create" not in service._sessions
    request["user_input"] = "1" + "0" * 10
    assert http.post("/api/negotiation/turn", json=request, headers=control).json()["detail"]["code"] == "SESSION_INVALID"


def test_concurrent_different_requests_cannot_consume_same_expected_round(client):
    _http, service = client
    def submit(index):
        try:
            return service.negotiate_with_effect("race", "核对条件", request_id=f"r-{index}",
                expected_round=0, practice_epoch=service.practice_epoch).state.round_count
        except NegotiationRoundConflict:
            return "conflict"
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(submit, range(2)))
    assert sorted(outcomes, key=str) == [1, "conflict"]
    assert service.get_session("race").round_count == 1


@pytest.mark.parametrize("digit", ["0", "０", "٠", "𝟘"])
def test_unicode_digit_shapes_mask_without_changing_business_values(digit):
    text = "合同" + digit * 18 + "，押金3500元，2026年11月5日，比例50%。"
    report = redact_report(text)
    assert report["safe_text"] == "合同***，押金3500元，2026年11月5日，比例50%。"
    assert report["spans"] == [{"start": 2, "end": 20, "kind": "id"}]


def test_answer_ids_survive_replay_and_answers_do_not_follow_new_question_order():
    initial = {**GOOD, "questions": ["何时交接？", "金额多少？", "有什么材料？"]}
    service, request, llm = setup(initial, {**GOOD, "questions": ["金额还有争议吗？", "何时交接？"]})
    first = service.generate(request)
    assert first.question_items == service.generate(request).question_items
    answers = [{"question_id": item.question_id, "text": "答" * 200} for item in first.question_items]
    next_request = ProposalRequest(**{**request.model_dump(), "draft_request_id": "draft-2",
                                     "goal_text": "目" * 900, "answers": answers})
    second = service.generate(next_request)
    assert second.status == "success" and len(llm.calls) == 2
    payload = json.loads(llm.calls[1][1].content)
    assert {item["question_id"] for item in payload["answers"]} == {item.question_id for item in first.question_items}
    assert not ({item.question_id for item in first.question_items} & {item.question_id for item in second.question_items})
    assert service.generate(next_request.model_copy(update={"answers": list(reversed(next_request.answers))})).replayed


def test_forged_answer_rejected_before_model_and_budget_is_checked(client):
    http, _service = client
    proposal, request, llm = setup()
    app.dependency_overrides[get_proposal_service] = lambda: proposal
    invalid = {**request.model_dump(), "answers": [{"question_id": "q_" + "0" * 32, "text": "回答"}]}
    assert http.post("/api/review/proposal", json=invalid).status_code == 422
    assert not llm.calls
    with pytest.raises(ValidationError):
        ProposalRequest(**{**invalid, "goal_text": "目" * 1999})


def test_answers_privacy_preview_is_before_generation(client):
    http, _service = client
    proposal, request, llm = setup()
    first = proposal.generate(request)
    app.dependency_overrides[get_proposal_service] = lambda: proposal
    data = {**request.model_dump(), "draft_request_id": "draft-2",
            "answers": [{"question_id": first.question_items[0].question_id, "text": "1" + "0" * 10}]}
    response = http.post("/api/review/proposal", json=data, headers={"X-Interaction-Version": "4"})
    assert response.status_code == 428 and len(llm.calls) == 1
    assert response.json()["detail"]["fields"][0]["field"] == "answers"


def test_browser_python_privacy_reports_are_equivalent():
    from backend.app.core.privacy import privacy_policy
    root = Path(__file__).resolve().parents[1]
    # Execute the actual browser function, not a second implementation in tests.
    script = r"""
const fs=require('fs'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const html=fs.readFileSync('frontend-web/index.html','utf8');
const start=html.indexOf('function compilePrivacyPolicy(policy)'),end=html.indexOf('function maskedOffset',start);
const redact=new Function('policy',html.slice(start,end)+';const privacyRules=compilePrivacyPolicy(policy);return redact;')(input.policy);
process.stdout.write(JSON.stringify(input.cases.map(text=>{const r=redact(text);return {safe_text:r.text,counts:r.counts,spans:r.spans};})));
"""
    cases = ["押金3500元，2026年11月5日，50%。", "🙂" + "０" * 18,
             "𝟘" * 18, "٠" * 15, "+86 138-0000-0000", "合同编号" + "2" * 18,
             "订单" + "2" * 19, "1" + "0" * 10, "证件" + "0" * 17 + "X",
             "🙂1\u200b38\u00a00000\u202f0000", "证件000000-00000000-000Ｘ", "1\u20600000000000",
             "１３８\r\n００００\r\n００００", "138 \n0000 0000", "证件110101\n19900101\n000X",
             "13800000000 0", "| 138 | 0000 | 0000 |", "138\n\n0000\n0000", "1 3 8 0 0 0 0 0 0 0 0", " " * 5000]
    result = subprocess.run(["node", "-e", script], cwd=root,
                            input=json.dumps({"policy": privacy_policy(), "cases": cases}),
                            text=True, encoding="utf-8", capture_output=True, check=True, timeout=15)
    assert json.loads(result.stdout) == [redact_report(text) for text in cases]


def test_changed_answer_conflicts_and_cross_clause_answer_is_not_trusted():
    from backend.app.services.proposal import ProposalConflict, ProposalAnswerInvalid
    service, request, _llm = setup()
    result = service.generate(request)
    answer = {"question_id": result.question_items[0].question_id, "text": "交接后处理。"}
    data = {**request.model_dump(), "draft_request_id": "answered", "answers": [answer]}
    service.generate(ProposalRequest(**data))
    with pytest.raises(ProposalConflict):
        service.generate(ProposalRequest(**{**data, "answers": [{**answer, "text": "修改后的回答"}]}))
    context = service.context_store.get(request.review_context_id)
    context.clauses["C-02"] = context.clauses["C-01"].model_copy(update={"clause_id": "C-02"})
    with pytest.raises(ProposalAnswerInvalid):
        service.generate(ProposalRequest(**{**data, "clause_id": "C-02", "draft_request_id": "other-clause"}))
