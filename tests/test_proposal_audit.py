"""Additional offline regressions for the proposal privacy boundary."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from backend.app.core.privacy import redact_pii
from backend.app.schemas.proposal import ProposalRequest
from backend.app.schemas.review import ReviewClauseResult
from backend.app.services.proposal import ProposalService
from backend.app.services.review_context import ReviewContextMissing, ReviewContextStore


PHONE = "138\t0000\t0000"  # Synthetic number, using a supported phone separator.
TEXT = "租赁期间应协商明确房屋维修的责任和安排。"


class RecordingModel:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=json.dumps(self.output, ensure_ascii=False))


def clause(**changes):
    return ReviewClauseResult(
        **{
            "clause_id": "C-01", "original_clause": TEXT, "risk_level": "NONE",
            "explanation": "请补充维修安排。", "evidence_ids": [],
            "negotiation_tip": "请明确维修责任。", **changes,
        }
    )


def request(context_id):
    return ProposalRequest(review_context_id=context_id, clause_id="C-01",
                           goal_text="请明确维修安排。", draft_request_id="audit-draft")


@pytest.mark.parametrize("field", ["proposed_message", "questions"])
def test_tab_separated_phone_is_rejected_before_public_draft_or_cache(field):
    assert redact_pii(PHONE) == "***"
    output = {"proposed_message": "请明确维修责任。", "evidence_ids": [], "questions": []}
    output[field] = f"请联系{PHONE}。" if field == "proposed_message" else [f"联系方式为{PHONE}吗？"]
    model = RecordingModel(output)
    store = ReviewContextStore()
    context_id = store.create(TEXT, [clause()], {})
    service = ProposalService(context_store=store, llm=model)

    result = service.generate(request(context_id))
    assert result.status == "needs_review"
    assert result.failure_code == "VALIDATION_FAILED" and result.retry_count == 2
    assert result.proposed_message == "" and result.questions == []
    assert len(model.calls) == 3
    replay = service.generate(request(context_id))
    assert replay.replayed and replay.proposed_message == "" and replay.questions == []
    assert len(model.calls) == 3


def test_context_masks_raw_clause_fields_before_storage_and_cloud_prompt():
    source = clause(original_clause=f"合同联系电话{PHONE}。",
                    explanation=f"联系{PHONE}确认维修。", negotiation_tip=f"请回复{PHONE}。")
    store = ReviewContextStore()
    context_id = store.create(f"合同联系电话{PHONE}。", [source], {})
    stored = store.get(context_id)
    assert stored.contract_text == "合同联系电话***。"
    for field in ("original_clause", "explanation", "negotiation_tip"):
        assert PHONE not in getattr(stored.clauses["C-01"], field)
        assert "***" in getattr(stored.clauses["C-01"], field)
    assert PHONE in source.original_clause  # Do not mutate the caller's result.

    model = RecordingModel({"proposed_message": "请明确维修责任。", "evidence_ids": [], "questions": []})
    result = ProposalService(context_store=store, llm=model).generate(request(context_id))
    assert result.status == "success"
    payload = json.loads(model.calls[0][1].content)
    assert payload["contract_text"] == stored.contract_text
    assert payload["clause"]["original_clause"] == "合同联系电话***。"
    assert all(PHONE not in value for value in payload["clause"].values() if isinstance(value, str))


def test_returned_drafts_do_not_allow_mutating_the_cached_response():
    model = RecordingModel({"proposed_message": "请明确维修责任。", "evidence_ids": [],
                            "questions": ["何时安排维修？"]})
    store = ReviewContextStore()
    context_id = store.create(TEXT, [clause()], {})
    service = ProposalService(context_store=store, llm=model)
    first = service.generate(request(context_id))
    expected = first.model_dump(exclude={"replayed"})
    first.proposed_message = "调用方修改"
    first.questions.append("不应写回缓存")
    first.trace[0].feedback.append("不应写回记录")

    replay = service.generate(request(context_id))
    assert replay.replayed and replay.model_dump(exclude={"replayed"}) == expected
    replay.questions.clear()
    replay.trace.clear()
    assert service.generate(request(context_id)).model_dump(exclude={"replayed"}) == expected
    assert len(model.calls) == 1


def test_context_clause_snapshot_is_detached_from_the_original_review():
    original = clause()
    store = ReviewContextStore()
    context_id = store.create(TEXT, [original], {})
    original.negotiation_tip = "调用方替换建议"
    original.evidence_ids.append("LAW-716")
    stored = store.get(context_id).clauses["C-01"]
    assert stored.negotiation_tip == "请明确维修责任。"
    assert stored.evidence_ids == []


def test_acquired_context_finishes_after_expiry_but_cannot_start_another_request():
    now = [0.0]
    started, release = Event(), Event()

    class WaitingModel(RecordingModel):
        def invoke(self, messages):
            started.set()
            assert release.wait(timeout=5), "test must release the pending model"
            return super().invoke(messages)

    model = WaitingModel({"proposed_message": "请明确维修责任。", "evidence_ids": [], "questions": []})
    store = ReviewContextStore(ttl_seconds=10, clock=lambda: now[0])
    context_id = store.create(TEXT, [clause()], {})
    service = ProposalService(context_store=store, llm=model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.generate, request(context_id))
        try:
            assert started.wait(timeout=5), "generation must acquire the context first"
            now[0] = 10.0
            with pytest.raises(ReviewContextMissing):
                store.get(context_id)
        finally:
            release.set()
        assert pending.result(timeout=5).status == "success"
    with pytest.raises(ReviewContextMissing):
        service.generate(request(context_id))
    assert len(model.calls) == 1
