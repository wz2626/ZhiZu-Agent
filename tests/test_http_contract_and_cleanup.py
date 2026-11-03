"""HTTP-only term restrictions and resource ownership at successful submit."""

import asyncio
from copy import deepcopy
from threading import Event, current_thread
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api import negotiation as negotiation_api, review as review_api
from backend.app.main import app
from backend.app.schemas.negotiation import NegotiationResponse
from backend.app.services import negotiation_graph as graph_module, model_gateway
from backend.app.services.negotiation_service import NegotiationService
from backend.app.services.model_gateway import CloudExecutor
from backend.app.services.operation_store import OperationBusy


@pytest.fixture
def arrangement_service(monkeypatch):
    def landlord(state):
        return {"landlord_response": "【模拟房东】确认本轮安排：周五核对交接记录",
                "candidate_terms": {f"round_{state.round_count + 1}": {"arrangement": ["周五核对交接记录"]}},
                "landlord_confirmed": True}
    monkeypatch.setattr(graph_module, "landlord_node", landlord)
    service = NegotiationService(graph_module.build_negotiation_graph(), public_api=True)
    key = negotiation_api.get_negotiation_service
    previous = app.dependency_overrides.get(key)
    app.dependency_overrides[key] = lambda: service
    try:
        yield service
    finally:
        if previous is None:
            app.dependency_overrides.pop(key, None)
        else:
            app.dependency_overrides[key] = previous


def submit(client, service, session_id, request_id="turn"):
    return client.post("/api/negotiation/turn", json={
        "session_id": session_id, "request_id": request_id, "user_input": "请核对交接安排。",
    }, headers={"X-Interaction-Version": "4", "X-Practice-Epoch": service.practice_epoch, "X-Expected-Round": "0"})


def test_http_rejects_arrangement_before_commit_while_python_remains_compatible(arrangement_service):
    service = arrangement_service
    before = service.get_session("web")
    with TestClient(app) as client:
        rejected = submit(client, service, "web")
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "UNSUPPORTED_HTTP_TERMS"
    assert service.get_session("web") == before
    assert service._sessions["web"].requests == {}
    # Same public_api=True service, same identifier: HTTP did not consume it.
    accepted = service.negotiate("web", "请核对交接安排。", request_id="turn")
    assert accepted.status == "success" and accepted.round_count == 1
    assert accepted.confirmed_terms == {"round_1": {"arrangement": ["周五核对交接记录"]}}


def test_http_replay_cannot_expose_cached_python_public_arrangements(arrangement_service):
    service = arrangement_service
    def python_public_response(result):
        # Another Python consumer can legitimately cache the wider DTO.
        fields = set(NegotiationResponse.model_fields) & set(type(result.state).model_fields)
        return NegotiationResponse(**result.state.model_dump(include=fields),
                                   unresolved_requests=[], missing_facts=[], turn_effect=result.turn_effect)
    service.negotiate_with_effect("python-cached", "请核对交接安排。", request_id="turn",
                                  response_validator=python_public_response)
    before = service.get_session("python-cached")
    cached = deepcopy(service._sessions["python-cached"].requests)
    with TestClient(app) as client:
        rejected = submit(client, service, "python-cached")
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "UNSUPPORTED_HTTP_TERMS"
    assert service.get_session("python-cached") == before
    assert service._sessions["python-cached"].requests == cached


class ReviewProbe:
    def __init__(self, gate=None):
        self.gate, self.entered, self.closed_event = gate, Event(), Event()
        self.calls, self.closes, self.close_threads = 0, 0, []

    def analyze_contract_detailed(self, text, top_k):
        self.calls += 1
        assert self.closes == 0
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5), "test must release accepted work"
        assert self.closes == 0, "HTTP completion must not close running work"
        return "reviewed"

    def close(self):
        self.closes += 1
        self.close_threads.append(current_thread().name)
        self.closed_event.set()


async def until(predicate):
    for _ in range(2000):
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("worker did not reach expected ownership boundary")


async def review(service):
    return await review_api._review_job(service, SimpleNamespace(contract_text="租赁合同测试", top_k=4), detailed=True)


def test_slot_rejection_closes_unsubmitted_service_once(monkeypatch):
    async def scenario():
        executor = CloudExecutor(workers=1, queue=0)
        monkeypatch.setattr(review_api, "cloud_executor", executor)
        gate, entered = Event(), Event()
        def blocker():
            entered.set()
            assert gate.wait(5)
        pending = asyncio.create_task(executor.run(blocker))
        try:
            await until(entered.is_set)
            probe = ReviewProbe()
            with pytest.raises(HTTPException) as error:
                await review(probe)
            assert error.value.status_code == 503
            assert probe.calls == 0 and probe.closes == 1
            assert probe.close_threads == [current_thread().name]
        finally:
            gate.set()
            await asyncio.gather(pending, return_exceptions=True)
            executor.close()
    asyncio.run(scenario())


def test_submit_failure_closes_once_and_returns_capacity(monkeypatch):
    async def scenario():
        executor, probe = CloudExecutor(workers=1, queue=0), ReviewProbe()
        original = executor._pool.submit
        def broken(*args):
            raise RuntimeError("synthetic submit failure")
        monkeypatch.setattr(executor._pool, "submit", broken)
        try:
            with pytest.raises(RuntimeError, match="submit failure"):
                await executor.run(lambda: None, cleanup=probe.close)
            assert probe.closes == 1 and probe.calls == 0
            monkeypatch.setattr(executor._pool, "submit", original)
            assert await executor.run(lambda: "capacity returned") == "capacity returned"
            assert probe.closes == 1
        finally:
            executor.close()
    asyncio.run(scenario())


def test_queue_expiry_closes_submitted_service_once_without_executing(monkeypatch):
    async def scenario():
        now, submitted = [0.0], []
        monkeypatch.setattr(model_gateway, "monotonic", lambda: now[0])
        executor = CloudExecutor(workers=1, queue=1, queue_timeout=1)
        monkeypatch.setattr(review_api, "cloud_executor", executor)
        original = executor._pool.submit
        def track(*args):
            future = original(*args)
            submitted.append(future)
            return future
        monkeypatch.setattr(executor._pool, "submit", track)
        gate, entered = Event(), Event()
        def blocker():
            entered.set()
            assert gate.wait(5)
        pending = asyncio.create_task(executor.run(blocker))
        queued = None
        try:
            await until(entered.is_set)
            probe = ReviewProbe()
            queued = asyncio.create_task(review(probe))
            await until(lambda: len(submitted) == 2)
            assert not submitted[1].running() and probe.closes == 0
            now[0] = 2
            gate.set()
            with pytest.raises(HTTPException) as error:
                await queued
            assert error.value.status_code == 503 and error.value.detail["code"] == "SERVICE_BUSY"
            assert probe.calls == 0 and probe.closes == 1
            assert probe.close_threads[0].startswith("zhizu-cloud")
        finally:
            gate.set()
            await asyncio.gather(*[task for task in (pending, queued) if task is not None], return_exceptions=True)
            executor.close()
    asyncio.run(scenario())


def test_http_timeout_does_not_close_running_service(monkeypatch):
    async def scenario():
        executor = CloudExecutor(workers=1, queue=0, deadline=0.1)
        monkeypatch.setattr(review_api, "cloud_executor", executor)
        gate, probe = Event(), None
        try:
            probe = ReviewProbe(gate)
            pending = asyncio.create_task(review(probe))
            await until(probe.entered.is_set)
            with pytest.raises(HTTPException) as error:
                await pending
            assert error.value.status_code == 503 and error.value.detail["code"] == "OPERATION_EXPIRED"
            assert probe.calls == 1 and probe.closes == 0
            with pytest.raises(OperationBusy):
                await executor.run(lambda: None)
            gate.set()
            await until(probe.closed_event.is_set)
            assert probe.closes == 1 and probe.close_threads[0].startswith("zhizu-cloud")
        finally:
            gate.set()
            executor.close()
    asyncio.run(scenario())


def test_http_timeout_while_queued_does_not_reclaim_task_ownership(monkeypatch):
    async def scenario():
        now = [0.0]
        monkeypatch.setattr(model_gateway, "monotonic", lambda: now[0])
        executor = CloudExecutor(workers=1, queue=1, deadline=0.1)
        monkeypatch.setattr(review_api, "cloud_executor", executor)
        gate, entered = Event(), Event()
        def blocker():
            entered.set()
            assert gate.wait(5)
        pending = asyncio.create_task(executor.run(blocker))
        try:
            await until(entered.is_set)
            probe = ReviewProbe()
            with pytest.raises(HTTPException) as error:
                await review(probe)
            assert error.value.status_code == 503
            assert probe.calls == 0 and probe.closes == 0
            # It was submitted but never started: only completion of the queued
            # task may close it, even after the HTTP timeout has returned.
            # Advance the operation clock explicitly: an asyncio timeout on
            # Windows need not fire at/after a monotonic deadline exactly.
            now[0] = 1.0
            gate.set()
            await until(probe.closed_event.is_set)
            assert probe.calls == 0 and probe.closes == 1
            assert probe.close_threads[0].startswith("zhizu-cloud")
        finally:
            gate.set()
            await asyncio.gather(pending, return_exceptions=True)
            executor.close()
    asyncio.run(scenario())


def test_cleanup_error_preserves_result_and_capacity_without_logging_raw_text(caplog):
    async def scenario():
        executor = CloudExecutor(workers=1, queue=0)
        def broken_close():
            raise RuntimeError("private-cleanup-payload")
        try:
            assert await executor.run(lambda: "done", cleanup=broken_close) == "done"
            assert await executor.run(lambda: "ready") == "ready"
        finally:
            executor.close()
    asyncio.run(scenario())
    assert "private-cleanup-payload" not in caplog.text
