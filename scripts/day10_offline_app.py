"""Browser-test-only local server: real routes/graphs, explicit review doubles.

Never imported by the production application. All external sockets and cloud
HTTP are blocked. No local .env credential is used by these dependencies.
"""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from time import sleep
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key, value in {
    "CHAT_API_KEY": "synthetic-offline-key", "CHAT_MODEL": "offline-review-double",
    "CHAT_BASE_URL": "https://offline.invalid", "EMBEDDING_API_KEY": "",
    "EMBEDDING_BASE_URL": "https://offline.invalid", "EMBEDDING_MODEL": "offline",
    "CHROMA_PATH": str(ROOT / ".runtime/day10-unused-store"), "ANONYMIZED_TELEMETRY": "False",
}.items():
    os.environ[key] = value

_connect = socket.socket.connect
_getaddrinfo = socket.getaddrinfo
blocked_external_calls = 0


def local_connect(sock, address):
    global blocked_external_calls
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
        blocked_external_calls += 1
        raise RuntimeError("external network blocked in browser test server")
    return _connect(sock, address)


def local_dns(host, *args, **kwargs):
    global blocked_external_calls
    if host not in {None, "127.0.0.1", "::1", "localhost", b"localhost"}:
        blocked_external_calls += 1
        raise RuntimeError("external DNS blocked in browser test server")
    return _getaddrinfo(host, *args, **kwargs)


socket.socket.connect = local_connect
socket.getaddrinfo = local_dns

import httpx
import uvicorn
from backend.app.api.review import get_review_service, get_proposal_service
from backend.app.api.negotiation import get_negotiation_service
from backend.app.core.config import get_settings
from backend.app.core.privacy import redact_pii
from backend.app.main import app
from backend.app.services.negotiation_graph import build_negotiation_graph, scenario_landlord_responder
from backend.app.services.negotiation_service import NegotiationService
from backend.app.services.review import ContractReviewService
from backend.app.services.proposal import ProposalService
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws


def forbidden_http(*args, **kwargs):
    global blocked_external_calls
    blocked_external_calls += 1
    raise RuntimeError("cloud HTTP forbidden in browser test server")


httpx.HTTPTransport.handle_request = forbidden_http


class ReviewStoreDouble:
    def get_status(self):
        return SimpleNamespace(is_ready=True)

    def search_evidence(self, query, top_k=4):
        assert redact_pii(query) == query
        return [LawVectorStoreService._evidence(law, 0.8) for law in load_authoritative_laws() if law.law_id == "LAW-712"]


class ReviewChatDouble:
    def invoke(self, messages):
        payload = json.loads(messages[1].content)
        text = payload["合同文本"]
        assert redact_pii(text) == text
        clauses = [
            "租赁结束后可不说明理由直接扣留全部押金。",
            "维修责任和费用均由租客承担。",
            "提前退租须支付固定违约金2000元。",
        ]
        results = [{
            "clause_id": f"C-{i:02d}", "original_clause": clause, "risk_level": "MEDIUM",
            "explanation": "离线浏览器测试样例：请结合合同事实核对，需补充具体依据。",
            "evidence_ids": ["LAW-712"] if i == 2 else [],
            "negotiation_tip": "测试样例建议：核对费用凭证，明确协商条件。",
        } for i, clause in enumerate(clauses, 1) if clause in text]
        sleep(0.05)
        return SimpleNamespace(content=json.dumps(results, ensure_ascii=False))


def review_dependency():
    service = ContractReviewService(vector_store=ReviewStoreDouble(), llm=ReviewChatDouble(), settings=get_settings())
    try:
        yield service
    finally:
        service.close()


mode = {"value": "normal"}
proposal_calls = 0


class ProposalChatDouble:
    """Explicit expression fixture; production proposal validation still runs."""

    def invoke(self, messages):
        global proposal_calls
        proposal_calls += 1
        payload = json.loads(messages[1].content)
        assert redact_pii(payload["goal_text"]) == payload["goal_text"]
        slow = mode["value"] == "proposal_slow"
        sleep(0.5 if slow else 0.08)
        if mode["value"] == "proposal_invalid":
            return SimpleNamespace(content='{"proposed_message":"13800000000","evidence_ids":[],"questions":[]}')
        if mode["value"] == "proposal_timeout":
            raise TimeoutError("synthetic private timeout")
        ids = list(payload["evidence_by_id"])
        prefix = "依据" + "、".join(ids) + "，" if ids else ""
        return SimpleNamespace(content=json.dumps({
            "proposed_message": ("合成慢请求结果：" if slow else "") + prefix + "合成反提案：请核对相关凭证，明确责任、具体金额和处理日期。",
            "evidence_ids": ids,
            "questions": (["请确认处理时间。", "还有哪些材料？", "费用是否仍有争议？"] if payload.get("answers") else
                          ["请补充费用凭证与交接记录。", "希望何时完成？", "费用是多少？"]),
        }, ensure_ascii=False))


def test_responder(state):
    if mode["value"] == "critic_failure":
        return "【模拟房东】我确认返还押金3000元。"
    if mode["value"] == "node_exception":
        raise RuntimeError("synthetic private exception")
    return scenario_landlord_responder(state)


app.dependency_overrides[get_review_service] = review_dependency
practice = NegotiationService(build_negotiation_graph(landlord_responder=test_responder), public_api=True)
app.dependency_overrides[get_negotiation_service] = lambda: practice
app.dependency_overrides[get_proposal_service] = lambda: ProposalService(llm=ProposalChatDouble())


@app.middleware("http")
async def test_wait(request, call_next):
    if request.method == "POST" and request.url.path in {"/api/negotiation/turn", "/api/review/analyze-detailed", "/api/review/proposal"}:
        await asyncio.sleep(1.25)  # Explicit latency injection to test waiting UI.
    return await call_next(request)


@app.post("/_test/mode", include_in_schema=False)
def set_mode(body: dict):
    assert body["value"] in {"normal", "critic_failure", "node_exception", "proposal_invalid", "proposal_timeout", "proposal_slow"}
    mode["value"] = body["value"]
    return {"ok": True}


@app.get("/_test/diagnostics", include_in_schema=False)
def diagnostics():
    return {"blocked_external_calls": blocked_external_calls, "real_cloud_calls": 0,
            "review": "explicit_chat_and_retrieval_doubles_with_real_graph",
            "negotiation": "real_graph_fixed_offline_policy",
            "proposal": "explicit_chat_double_with_real_service_validation_and_cache",
            "proposal_model_calls": proposal_calls}


@app.post("/_test/restart-practice", include_in_schema=False)
def restart_practice():
    # Explicit test-only instance replacement: real registry and epoch reset.
    global practice
    practice = NegotiationService(build_negotiation_graph(landlord_responder=test_responder), public_api=True)
    return {"practice_epoch": practice.practice_epoch}


if __name__ == "__main__":
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    print(f"READY {listener.getsockname()[1]}", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False)).run(sockets=[listener])
