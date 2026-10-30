"""Regression checks for backend review/embedding audit boundaries."""

import json
from types import SimpleNamespace

import pytest

from backend.app.core.config import Settings
from backend.app.services.embedding import SiliconFlowEmbeddings
from backend.app.services.graph import ReviewValidationError, validate_response
from backend.app.services.review import ContractReviewService
from backend.app.services.review_context import ReviewContextStore
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws


CONTRACT = "租客未经房东同意擅自转租房屋。"


def finding(**updates):
    value = {
        "clause_id": "C-01", "original_clause": CONTRACT, "risk_level": "HIGH",
        "explanation": "请核对转租是否已取得授权。", "evidence_ids": ["LAW-716"],
        "negotiation_tip": "请明确转租的书面同意条件。",
    }
    value.update(updates)
    return value


@pytest.mark.parametrize("clause_id", ["C-13800000000", "C-110105194912310022"])
def test_review_identifier_cannot_publish_sensitive_numbers(clause_id):
    with pytest.raises(ReviewValidationError, match="unmasked sensitive numbers"):
        validate_response(json.dumps([finding(clause_id=clause_id)]), CONTRACT, {"LAW-716"})


@pytest.mark.parametrize("field", ["explanation", "negotiation_tip"])
def test_review_checks_decoded_tab_separated_phone_fields(field):
    with pytest.raises(ReviewValidationError, match="unmasked sensitive numbers"):
        validate_response(json.dumps([finding(**{field: "联系138\t0000\t0000"})]),
                          CONTRACT, {"LAW-716"})


def test_sensitive_identifier_enters_bounded_rewrite_without_leaking_feedback():
    unsafe_id = "C-13800000000"
    drafts = iter([json.dumps([finding(clause_id=unsafe_id)]), json.dumps([finding()])])
    prompts = []

    def invoke(messages):
        prompts.append(messages)
        return SimpleNamespace(content=next(drafts))

    law = next(law for law in load_authoritative_laws() if law.law_id == "LAW-716")
    store = SimpleNamespace(
        get_status=lambda: SimpleNamespace(is_ready=True),
        search_evidence=lambda *args, **kwargs: [LawVectorStoreService._evidence(law, 0.8)],
    )
    settings = Settings("https://chat.invalid/v1", "offline", "sk-offline-audit",
                        "https://embedding.invalid/v1", "offline", "", "missing")
    review = ContractReviewService(vector_store=store, llm=SimpleNamespace(invoke=invoke),
                                   settings=settings, context_store=ReviewContextStore())
    result = review.analyze_contract_detailed(CONTRACT)
    assert result.status == "success" and result.retry_count == 1
    assert len(prompts) == 2
    assert unsafe_id not in result.model_dump_json()
    assert unsafe_id not in prompts[1][-1].content
    assert result.results[0].clause_id == "C-01"
    assert [event.status for event in result.trace if event.node == "critic"] == ["retry", "completed"]


def mock_embedding_response(monkeypatch, indices):
    payload = {"data": [{"index": value, "embedding": [float(position), 1.0]}
                        for position, value in enumerate(indices)]}
    monkeypatch.setattr("backend.app.services.embedding.httpx.post", lambda *args, **kwargs:
                        SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload))
    return SiliconFlowEmbeddings(base_url="https://embedding.invalid/v1", model="offline",
                                 api_key="sk-offline-audit", expected_dimension=2)


@pytest.mark.parametrize("indices", [[0, 0], [-1, 1], [1, 2], [True, 0], [0.0, 1], ["0", "1"]])
def test_embedding_response_requires_exact_integer_input_indices(monkeypatch, indices):
    embedding = mock_embedding_response(monkeypatch, indices)
    with pytest.raises((ValueError, RuntimeError)):
        embedding.embed_documents(["法条甲", "法条乙"])


def test_out_of_order_embeddings_are_restored_to_their_input_positions(monkeypatch):
    embedding = mock_embedding_response(monkeypatch, [2, 0, 1])
    assert embedding.embed_documents(["法条甲", "法条乙", "法条丙"]) == [
        [1.0, 1.0], [2.0, 1.0], [0.0, 1.0],
    ]
