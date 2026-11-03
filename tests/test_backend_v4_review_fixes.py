"""Review findings: independent commit evidence, busy semantics and quota."""

from copy import deepcopy
import json
from types import SimpleNamespace
from pathlib import Path
import subprocess
import re

import pytest
from fastapi.testclient import TestClient

from backend.app.api.review import get_review_service
from backend.app.main import app
from backend.app.services import negotiation_graph as graph_module
from backend.app.services.negotiation_service import NegotiationService
from backend.app.services.operation_store import OperationStore, OperationExpired
from backend.app.services.review_context import ReviewContextStore
from test_proposal import setup, GOOD, material, TEXT, settings
from test_review_detailed import FakeStore, FakeLLM, finding, CONTRACT
from backend.app.services.review import ContractReviewService


@pytest.mark.parametrize("mutation", ["arbitrary", "extra", "missing", "wrong_round", "history"])
def test_arrangement_rebuilt_from_trusted_round_rejects_rogue_keys_without_caching(monkeypatch, mutation):
    def landlord(state):
        return {"landlord_response": "【模拟房东】确认本轮安排：周五\t核对记录",
                "candidate_terms": {f"round_{state.round_count + 1}": {"arrangement": ["周五\t核对记录"]}},
                "landlord_confirmed": True}
    monkeypatch.setattr(graph_module, "landlord_node", landlord)
    good = graph_module.build_negotiation_graph()
    service = NegotiationService(good, public_api=True)
    service.negotiate_with_effect("arrange", "首轮", request_id="first")
    before = service.get_session("arrange")
    cached = deepcopy(service._sessions["arrange"].requests)
    class Poisoned:
        def invoke(self, state):
            result = good.invoke(state)
            terms = result["confirmed_terms"]
            if mutation == "arbitrary":
                terms["unexpected_key"] = terms.pop("round_2")
            elif mutation == "extra":
                terms["unexpected_key"] = deepcopy(terms["round_2"])
            elif mutation == "missing":
                terms.pop("round_2")
            elif mutation == "wrong_round":
                terms["round_3"] = terms.pop("round_2")
            else:
                terms["round_1"] = {"arrangement": ["篡改旧安排"]}
            return result
    service._graph = Poisoned()
    rejected = service.negotiate_with_effect("arrange", "第二轮", request_id="bad")
    assert rejected.state.status == "needs_review"
    assert rejected.turn_effect.kind == "not_committed"
    assert service.get_session("arrange") == before
    assert service._sessions["arrange"].requests == cached


def test_all_100_contexts_pinned_returns_http_busy_without_fake_graph_event():
    store = ReviewContextStore(capacity=100)
    pinned = [store.get(store.create(TEXT, [material()[0]], material()[1]), pin=True) for _ in range(100)]
    service = ContractReviewService(vector_store=FakeStore(), llm=FakeLLM(json.dumps([finding()])),
                                    settings=settings("sk-synthetic"), context_store=store)
    events = []
    original = store.create
    def inspect_create(*args, **kwargs):
        # This hook executes only after a genuinely successful graph.
        events.append(True)
        return original(*args, **kwargs)
    store.create = inspect_create
    original_failure = service._detailed_failure
    def no_fake_failure(code, trace, **kwargs):
        pytest.fail("capacity pressure must not become graph failure")
    service._detailed_failure = no_fake_failure
    previous = app.dependency_overrides.get(get_review_service)
    app.dependency_overrides[get_review_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post("/api/review/analyze-detailed", json={"contract_text": CONTRACT},
                                   headers={"X-Interaction-Version": "4"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "SERVICE_BUSY"
        assert response.headers["retry-after"] == "2"
        assert "trace" not in response.json()
        assert events == [True] and len(service.llm.calls) == 1
        assert len(store._contexts) == 100
    finally:
        for context in pinned:
            store.release(context)
        service._detailed_failure = original_failure
        if previous is None:
            app.dependency_overrides.pop(get_review_service, None)
        else:
            app.dependency_overrides[get_review_service] = previous


def test_64_aborted_drafts_release_active_quota_without_reexecuting_old_ids():
    service, request, llm = setup()
    now, count = [0.0], [0]
    service.context_store.operations = OperationStore(deadline=1, recovery=1000, clock=lambda: now[0])
    def model(messages):
        count[0] += 1
        if count[0] <= 64:
            now[0] += 2
        return SimpleNamespace(content=json.dumps(GOOD))
    llm.invoke = model
    for index in range(64):
        with pytest.raises(OperationExpired):
            service.generate(request.model_copy(update={"draft_request_id": f"abort-{index}"}))
    context = service.context_store.get(request.review_context_id)
    assert not context.inflight and not context.requests and len(context.retired) == 64
    with pytest.raises(OperationExpired):
        service.generate(request.model_copy(update={"draft_request_id": "abort-0"}))
    assert count == [64]
    result = service.generate(request.model_copy(update={"draft_request_id": "recovered"}))
    assert result.status == "success" and count == [65]
    assert not context.inflight and len(context.requests) == 1
    # Even beyond receipt TTL, retained capability IDs do not silently reenter.
    now[0] = 2000
    with pytest.raises(OperationExpired):
        service.generate(request.model_copy(update={"draft_request_id": "abort-0"}))
    assert count == [65]


def test_browser_consumes_upgraded_rule_data_without_a_pinned_version(monkeypatch):
    from backend.app.core import privacy
    monkeypatch.setattr(privacy, "PRIVACY_POLICY_VERSION", "compatible-rule-upgrade-test")
    monkeypatch.setattr(privacy, "IGNORED_POINTS", [*privacy.IGNORED_POINTS, 0x2063])
    monkeypatch.setattr(privacy, "SPACE_POINTS", [*privacy.SPACE_POINTS, 0x205F])
    monkeypatch.setattr(privacy, "_CHAR_MAP", {**privacy._CHAR_MAP, 0x205F: " ", ord("@"): "1"})
    old_separator = privacy.SEPARATOR_PATTERN
    new_separator = old_separator.replace("-", "[.-]")
    monkeypatch.setattr(privacy, "SEPARATOR_PATTERN", new_separator)
    for field in ("_ID", "_PHONE", "_LEFT_DIGIT", "_RIGHT_DIGIT"):
        monkeypatch.setattr(privacy, field, re.compile(getattr(privacy, field).pattern.replace(old_separator, new_separator), re.ASCII))
    cases = ["🙂@38\u20630000\u205f0000", "138.0000.0000", "000000.00000000.000X", "金额2000元，日期2026-11-05"]
    script = r"""
const fs=require('fs'),input=JSON.parse(fs.readFileSync(0,'utf8')),html=fs.readFileSync('frontend-web/index.html','utf8');
const start=html.indexOf('function compilePrivacyPolicy(policy)'),end=html.indexOf('function maskedOffset',start);
const redact=new Function('policy',html.slice(start,end)+';const privacyRules=compilePrivacyPolicy(policy);return redact;')(input.policy);
process.stdout.write(JSON.stringify(input.cases.map(text=>{const r=redact(text);return {safe_text:r.text,counts:r.counts,spans:r.spans};})));
"""
    result = subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
                            input=json.dumps({"policy": privacy.privacy_policy(), "cases": cases}),
                            text=True, encoding="utf-8", capture_output=True, check=True, timeout=15)
    expected = [privacy.redact_report(text) for text in cases]
    assert all("***" in item["safe_text"] for item in expected[:3])
    assert expected[-1]["safe_text"] == cases[-1]
    assert json.loads(result.stdout) == expected
