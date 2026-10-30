"""Authoritative response enrichment without changing model/legacy contracts."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.schemas.review import ReviewClauseResult, ReviewDetailedResponse
from backend.app.services.review import ContractReviewService
from backend.app.services.review_context import ReviewContextStore
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws

TEXT = "租客未经房东同意擅自转租房屋。房东可以依法要求核对转租授权。"
CLAUSE = "租客未经房东同意擅自转租房屋。"


def settings(key="sk-offline-evidence"):
    return Settings("https://chat.invalid/v1", "offline", key,
                    "https://embedding.invalid/v1", "offline", "", "missing")


def finding(**updates):
    value = dict(clause_id="C-01", original_clause=CLAUSE, risk_level="HIGH",
                 explanation="请核对是否取得授权。", evidence_ids=["LAW-716"],
                 negotiation_tip="请明确转租授权。")
    value.update(updates)
    return value


class LLM:
    def __init__(self, value):
        self.value = value

    def invoke(self, _messages):
        return SimpleNamespace(content=json.dumps(self.value, ensure_ascii=False))


class Store:
    def __init__(self):
        self.laws = {law.law_id: law for law in load_authoritative_laws()}

    def get_status(self):
        return SimpleNamespace(is_ready=True)

    def search_evidence(self, _query, top_k=4):
        # Source metadata is deliberately untrusted; the response must take
        # canonical metadata rather than passing it through from retrieval.
        return [LawVectorStoreService._evidence(self.laws[key], 0.8).model_copy(update={
            "source_url": "https://untrusted.invalid/", "article_no": "错误条号",
        }) for key in ["LAW-716", "LAW-721"]]


def service(results=None):
    return ContractReviewService(vector_store=Store(), llm=LLM(results or [finding()]),
                                 settings=settings(), context_store=ReviewContextStore())


def test_detailed_evidence_only_contains_cited_retrieved_canonical_articles():
    review = service()
    result = review.analyze_contract_detailed(TEXT)
    law = review.vector_store.laws["LAW-716"]
    assert result.status == "success"
    assert set(result.evidence_by_id) == {"LAW-716"}
    evidence = result.evidence_by_id["LAW-716"]
    assert evidence.content == law.content and evidence.article_no == law.article_no
    assert evidence.source_url == law.source_url and evidence.verified_date == law.verified_date
    context = review.context_store.get(result.review_context_id)
    assert context.clauses["C-01"].original_clause == CLAUSE
    assert context.evidence_by_id == result.evidence_by_id


def test_shared_evidence_is_not_duplicated_and_model_fields_stay_six():
    result = service([finding(), finding(clause_id="C-02")]).analyze_contract_detailed(TEXT)
    assert len(result.results) == 2 and len(result.evidence_by_id) == 1
    assert set(ReviewClauseResult.model_fields) == {
        "clause_id", "original_clause", "risk_level", "explanation", "evidence_ids", "negotiation_tip",
    }


def test_no_citation_success_still_gets_context_without_fake_evidence():
    result = service([finding(risk_level="NONE", evidence_ids=[])]).analyze_contract_detailed(TEXT)
    assert result.status == "success" and result.evidence_by_id == {}
    assert result.review_context_id


def test_failure_has_no_context_or_evidence():
    review = ContractReviewService(settings=settings(""), context_store=ReviewContextStore())
    result = review.analyze_contract_detailed(TEXT)
    assert result.status == "needs_review"
    assert result.evidence_by_id == {} and result.review_context_id is None


def test_legacy_response_stays_unenriched():
    result = service().analyze_contract(TEXT).model_dump()
    assert set(result) == {"status", "results", "total_risks"}
    assert set(result["results"][0]) == set(ReviewClauseResult.model_fields)


def test_context_is_detached_and_rechecks_sensitive_numbers():
    store = ReviewContextStore()
    clause = ReviewClauseResult.model_validate(finding(explanation="联系13800000000核对。"))
    context_id = store.create(TEXT + "13800000000", [clause], {})
    clause.explanation = "被外部修改"
    context = store.get(context_id)
    assert "13800000000" not in context.contract_text
    assert context.clauses["C-01"].explanation == "联系***核对。"


def test_detailed_schema_rejects_evidence_for_uncited_law_and_failed_context():
    raw = service().analyze_contract_detailed(TEXT).model_dump(mode="json")
    raw["evidence_by_id"]["LAW-721"] = raw["evidence_by_id"]["LAW-716"]
    with pytest.raises(ValidationError):
        ReviewDetailedResponse.model_validate(raw)
    failed = ContractReviewService(settings=settings("")).analyze_contract_detailed(TEXT).model_dump()
    failed["review_context_id"] = "a" * 32
    with pytest.raises(ValidationError):
        ReviewDetailedResponse.model_validate(failed)
