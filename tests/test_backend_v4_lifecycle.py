"""Fault injection for publication, single-flight and bounded cloud work."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace
import json
import httpx
from langchain_core.messages import SystemMessage, HumanMessage

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api import negotiation as api
from backend.app.main import app
from backend.app.schemas.proposal import ProposalResponse
from backend.app.services.negotiation_graph import build_negotiation_graph, scenario_landlord_responder
from backend.app.services.negotiation_service import (
    NegotiationService, NegotiationRoundConflict, NegotiationSessionInvalid, NegotiationCapacityExceeded,
)
from backend.app.services.model_gateway import CloudExecutor, CloudTransport, invoke_model
from backend.app.services.operation_store import OperationStore, OperationBusy, OperationExpired
from backend.app.services.review_context import ReviewContextStore, ReviewContextMissing
from test_proposal import setup, GOOD, material, TEXT


def practice(**kwargs):
    return NegotiationService(build_negotiation_graph(landlord_responder=scenario_landlord_responder), public_api=True, **kwargs)


def test_unknown_session_reads_are_not_allocations_and_bad_baseline_never_creates():
    service = practice()
    assert service.get_session("absent").history == []
    assert not service._sessions
    with pytest.raises(NegotiationRoundConflict):
        service.negotiate_with_effect("absent", "诉求", request_id="r", expected_round=2)
    assert not service._sessions


def test_response_validation_failure_precedes_state_and_receipt_publication(monkeypatch):
    service = practice()
    app.dependency_overrides[api.get_negotiation_service] = lambda: service
    original = api._response
    def broken(*args):
        raise ValueError("synthetic response construction failure")
    monkeypatch.setattr(api, "_response", broken)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            body = {"session_id": "atomic", "request_id": "r", "user_input": "核对条件。"}
            result = client.post("/api/negotiation/turn", json=body)
            assert result.status_code == 500
            state = service.get_session("atomic")
            assert state.round_count == 0 and state.confirmed_terms == {} and state.trial_score is None
            assert service._sessions["atomic"].requests == {}
            monkeypatch.setattr(api, "_response", original)
            first = client.post("/api/negotiation/turn", json=body).json()
            assert first["round_count"] == 1
            # Cached public response is authoritative, not reconstructed from current policy.
            monkeypatch.setattr(api, "_response", broken)
            replay = client.post("/api/negotiation/turn", json=body).json()
            assert replay == {**first, "replayed": True}
    finally:
        app.dependency_overrides.pop(api.get_negotiation_service, None)


@pytest.mark.parametrize("field", ["trial_score", "scoring_rules", "available_evidence_ids", "confirmed_terms"])
def test_untrusted_graph_cannot_cross_commit_barrier(field):
    good = build_negotiation_graph(landlord_responder=scenario_landlord_responder)
    class Poisoned:
        def invoke(self, state):
            result = good.invoke(state)
            result[field] = {"trial_score": 100, "scoring_rules": {}, "available_evidence_ids": ["LAW-703"], "confirmed_terms": {"deposit_refund": 2000}}[field]
            return result
    service = NegotiationService(Poisoned(), public_api=True)
    result = service.negotiate("blocked", "诉求", request_id="r")
    assert result.status == "needs_review"
    assert service.get_session("blocked").round_count == 0
    assert service.get_session("blocked").confirmed_terms == {}


def test_session_bounds_expired_id_never_revives_and_replays_do_not_spend_quota():
    now = [0.0]
    service = practice(capacity=1, identity_capacity=2, request_capacity=1, ttl_seconds=10, clock=lambda: now[0])
    first = service.negotiate_with_effect("A", "诉求", request_id="r")
    assert service.negotiate_with_effect("A", "诉求", request_id="r").state.replayed
    with pytest.raises(NegotiationCapacityExceeded):
        service.negotiate_with_effect("A", "新诉求", request_id="r2")
    with pytest.raises(NegotiationCapacityExceeded):
        service.negotiate_with_effect("B", "诉求", request_id="r")
    now[0] = 11
    with pytest.raises(NegotiationSessionInvalid):
        service.negotiate_with_effect("A", "诉求", request_id="r")
    service.negotiate_with_effect("B", "诉求", request_id="r")
    now[0] = 22
    with pytest.raises(NegotiationCapacityExceeded):
        service.negotiate_with_effect("C", "诉求", request_id="r")


def test_same_context_allows_other_operations_while_first_model_is_blocked():
    service, request, llm = setup()
    entered, release = Event(), Event()
    calls, guard = [0], Lock()
    def model(messages):
        with guard:
            calls[0] += 1
            index = calls[0]
        if index == 1:
            entered.set()
            assert release.wait(5)
        return SimpleNamespace(content=json.dumps(GOOD, ensure_ascii=False))
    llm.invoke = model
    with ThreadPoolExecutor(3) as pool:
        first = pool.submit(service.generate, request)
        try:
            assert entered.wait(2)
            context = service.context_store.get(request.review_context_id)
            assert context.lock.acquire(blocking=False)
            context.lock.release()
            other = pool.submit(service.generate, request.model_copy(update={"draft_request_id": "other"})).result(2)
            assert other.status == "success"
            duplicate = pool.submit(service.generate, request)
        finally:
            release.set()
        assert first.result(3).status == "success"
        assert duplicate.result(3).replayed
    assert calls == [2]


def test_receipt_recovers_after_context_expiry_but_new_operation_requires_context():
    now = [0.0]
    store = ReviewContextStore(ttl_seconds=10, clock=lambda: now[0])
    service, request, llm = setup(store=store)
    response = service.generate(request)
    now[0] = 11
    with pytest.raises(ReviewContextMissing):
        store.get(request.review_context_id)
    assert service.generate(request).model_dump() == {**response.model_dump(), "replayed": True}
    with pytest.raises(ReviewContextMissing):
        service.generate(request.model_copy(update={"draft_request_id": "new"}))
    assert len(llm.calls) == 1


def test_active_context_cannot_be_evicted_and_finishes_after_context_ttl():
    now = [0.0]
    store = ReviewContextStore(ttl_seconds=10, capacity=1, clock=lambda: now[0])
    service, request, llm = setup(store=store)
    entered, release = Event(), Event()
    def model(messages):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(content=json.dumps(GOOD))
    llm.invoke = model
    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(service.generate, request)
        try:
            assert entered.wait(2)
            now[0] = 11
            with pytest.raises(OperationBusy):
                store.create(TEXT, [material()[0]], material()[1])
        finally:
            release.set()
        assert result.result(3).status == "success"
    assert service.generate(request).replayed


def test_expired_operation_never_publishes_questions_or_reenters_model():
    now = [0.0]
    service, request, llm = setup()
    service.context_store.operations = OperationStore(deadline=1, recovery=10, clock=lambda: now[0])
    def model(messages):
        llm.calls.append(messages)
        now[0] = 2
        return SimpleNamespace(content=json.dumps(GOOD))
    llm.invoke = model
    with pytest.raises(OperationExpired):
        service.generate(request)
    context = service.context_store.get(request.review_context_id)
    assert context.questions == {} and context.requests == {}
    with pytest.raises(OperationExpired):
        service.generate(request)
    assert len(llm.calls) == 1


def test_public_question_arrays_cannot_drift():
    service, request, _ = setup()
    response = service.generate(request).model_dump()
    response["question_items"][0]["text"] = "另一问题"
    with pytest.raises(ValidationError):
        ProposalResponse.model_validate(response)


def test_http_cancellation_keeps_worker_capacity_until_real_completion():
    async def scenario():
        executor = CloudExecutor(workers=1, queue=0)
        entered, release, finished = Event(), Event(), Event()
        def work():
            entered.set()
            release.wait(5)
            finished.set()
        try:
            task = asyncio.create_task(executor.run(work))
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(OperationBusy):
                await executor.run(lambda: None)
            assert not finished.is_set()
            release.set()
            while not finished.is_set():
                await asyncio.sleep(0.001)
            assert await executor.run(lambda: "ready") == "ready"
        finally:
            release.set()
            executor.close()
    asyncio.run(scenario())


def test_server_deadline_ends_http_wait_without_freeing_running_worker():
    async def scenario():
        executor = CloudExecutor(workers=1, queue=0, deadline=0.03)
        release = Event()
        try:
            with pytest.raises(OperationExpired):
                await executor.run(lambda: release.wait(3))
            with pytest.raises(OperationBusy):
                await executor.run(lambda: None)
        finally:
            release.set()
            executor.close()
    asyncio.run(scenario())


def test_model_egress_checks_text_not_opaque_question_ids():
    calls = []
    model = SimpleNamespace(invoke=lambda messages: calls.append(messages) or "ok")
    def messages(payload):
        return [SystemMessage(content="fixed"), HumanMessage(content=json.dumps(payload))]
    assert invoke_model(model, messages({"answers": [{"question_id": "q_13800000000" + "a" * 21, "text": "金额2000元。"}]})) == "ok"
    with pytest.raises(ValueError):
        invoke_model(model, messages({"goal_text": "联系人13800000000"}))
    assert len(calls) == 1


def test_cloud_stream_budget_counts_actual_chunks_and_closes_transport():
    closed = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"a" * 6
            yield b"b" * 6
        def close(self):
            closed.append(True)
    def handle(request):
        assert request.headers["accept-encoding"] == "identity"
        # Missing content length cannot bypass the actual-byte budget.
        return httpx.Response(200, stream=Stream())
    with httpx.Client(transport=CloudTransport(httpx.MockTransport(handle), max_bytes=10)) as client:
        with pytest.raises(ValueError, match="byte budget"):
            client.get("https://offline.invalid")
    assert closed == [True]


def test_compressed_cloud_response_is_rejected_before_decoding():
    with httpx.Client(transport=CloudTransport(httpx.MockTransport(lambda request:
        httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"not-decoded"))))) as client:
        with pytest.raises(ValueError, match="compressed"):
            client.get("https://offline.invalid")


def test_eight_same_and_different_baselines_execute_fixed_graph_once():
    for same in (True, False):
        count = [0]
        actual = build_negotiation_graph(landlord_responder=scenario_landlord_responder)
        class Counted:
            def invoke(self, state):
                count[0] += 1
                return actual.invoke(state)
        service = NegotiationService(Counted(), public_api=True)
        def run(index):
            try:
                return service.negotiate_with_effect("race", "核对条件", request_id="same" if same else f"r-{index}", expected_round=0)
            except NegotiationRoundConflict:
                return None
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(run, range(8)))
        assert count == [1] and service.get_session("race").round_count == 1
        assert sum(result is not None for result in results) == (8 if same else 1)


def test_fixed_plane_runs_when_chat_and_embedding_fail(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("fixed practice must not use a cloud dependency")
    monkeypatch.setattr("backend.app.services.proposal.ChatOpenAI", forbidden)
    monkeypatch.setattr("backend.app.services.review.ChatOpenAI", forbidden)
    monkeypatch.setattr("backend.app.services.embedding.post_embeddings", forbidden)
    service = practice()
    for scenario in ("deposit", "maintenance", "early_termination"):
        assert service.negotiate(scenario, "核对条件", scenario=scenario).round_count == 1


def test_expired_receipt_does_not_reexecute_if_context_lives_longer():
    now = [0.0]
    service, request, llm = setup()
    service.context_store.operations = OperationStore(deadline=1, recovery=2, clock=lambda: now[0])
    service.generate(request)
    now[0] = 3
    with pytest.raises(OperationExpired):
        service.generate(request)
    assert len(llm.calls) == 1
