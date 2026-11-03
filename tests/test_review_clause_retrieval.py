"""Clause-recall coverage, bounded batches and verified citation publication."""
import json
from types import SimpleNamespace

import pytest

from backend.app.core.config import get_settings
from backend.app.services.review import ContractReviewService
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws, review_queries


REPAIR = "房屋及附属设施发生任何损坏，维修责任和费用均由租客承担。"
CONTRACT = "房屋租赁合同。租期一年，租金按月支付。押金2000元。" + REPAIR


def test_clause_views_cover_tail_and_do_not_grow_with_every_sentence():
    text = "房屋租赁合同。" + "租金按月支付。" * 500 + REPAIR
    queries = review_queries(text)
    assert queries[0] == text
    assert 1 < len(queries) <= 9
    assert REPAIR in "\n".join(queries[1:])
    assert len(queries) == len(set(queries))
    assert review_queries("房屋租赁合同") == ["房屋租赁合同"]


def store_double():
    store = LawVectorStoreService.__new__(LawVectorStoreService)
    store.embedding_mode, store.embedding_dimension = "cloud", 2
    store._check_mode = lambda: None
    store._check_ids = lambda: None
    batches, searches = [], []

    def embed_documents(texts):
        batches.append(texts)
        return [[float(i + 1), 1.0] for i in range(len(texts))]

    def query(**kwargs):
        searches.append(kwargs)
        ids = []
        for i, text in enumerate(batches[-1]):
            choices = (["LAW-712", "LAW-713", "LAW-711", "LAW-712"]
                       if i and "维修" in text else ["LAW-721", "LAW-707", "LAW-730", "LAW-705"])
            ids.append(choices[:kwargs["n_results"]])
        return {"ids": ids, "distances": [[0.1 + i * 0.05 for i in range(len(row))] for row in ids]}

    store.embeddings = SimpleNamespace(embed_documents=embed_documents)
    store.collection = SimpleNamespace(count=lambda: 32, query=query)
    return store, batches, searches


def test_batch_recall_preserves_repair_laws_missing_from_whole_contract_top_four():
    store, batches, searches = store_double()
    result = store.search_review_evidence(CONTRACT)
    assert len(batches) == len(searches) == 1
    assert 1 < len(batches[0]) <= 9
    assert {item.evidence_id for item in result} == {
        "LAW-721", "LAW-707", "LAW-730", "LAW-705", "LAW-711", "LAW-712", "LAW-713",
    }
    assert len(result) == len({item.evidence_id for item in result})
    laws = {item.law_id: item for item in load_authoritative_laws()}
    assert all(item.content == laws[item.evidence_id].content for item in result)


def test_every_embedding_view_is_masked_before_external_call():
    store, batches, _ = store_double()
    store.search_review_evidence(CONTRACT + "联系电话13800000000，证件11010119900101000X。")
    assert len(batches) == 1
    assert all("13800000000" not in text and "11010119900101000X" not in text for text in batches[0])


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[float("nan"), 1]], [[True, 1]], [["1", 1]]])
def test_invalid_batch_vectors_do_not_reach_chroma(vectors):
    store, _, searches = store_double()
    store.embeddings.embed_documents = lambda texts: vectors * len(texts) if vectors else []
    with pytest.raises(ValueError):
        store.search_review_evidence(CONTRACT)
    assert not searches


def test_zero_batch_vectors_do_not_query_or_invent_evidence():
    store, _, searches = store_double()
    store.embeddings.embed_documents = lambda texts: [[0, 0] for _ in texts]
    assert store.search_review_evidence(CONTRACT) == []
    assert not searches


@pytest.mark.parametrize("query,top_k", [("", 4), ("x" * 5001, 4), (CONTRACT, True), (CONTRACT, 9)])
def test_batch_admission_is_bounded(query, top_k):
    store, batches, searches = store_double()
    with pytest.raises(ValueError):
        store.search_review_evidence(query, top_k)
    assert not batches and not searches


@pytest.mark.parametrize("bad", [{"ids": [], "distances": []},
                                  {"ids": [["LAW-712"]], "distances": [[float("nan")]]}])
def test_malformed_retrieval_does_not_publish_evidence(bad):
    store, _, _ = store_double()
    store.collection.query = lambda **kwargs: bad
    with pytest.raises(ValueError):
        store.search_review_evidence("租赁物维修")


@pytest.mark.parametrize("cited", [True, False])
def test_detailed_service_keeps_clause_union_and_only_publishes_model_citations(monkeypatch, cited):
    monkeypatch.setenv("CHAT_API_KEY", "sk-synthetic-clause-coverage")
    laws = load_authoritative_laws()[:12]
    evidence = [LawVectorStoreService._evidence(law, 0.8) for law in laws]
    calls, model_payloads = [], []

    def retrieve(text, top_k):
        calls.append((text, top_k))
        return evidence

    def invoke(messages):
        model_payloads.append(json.loads(messages[1].content))
        return SimpleNamespace(content=json.dumps([{
            "clause_id": "C-01", "original_clause": REPAIR, "risk_level": "MEDIUM",
            "explanation": "请结合第712条中的约定例外，核对维修责任与实际损坏原因。" if cited else "现有依据不能直接支持该项结论，需补充核对。",
            "evidence_ids": ["LAW-712", "LAW-713"] if cited else [],
            "negotiation_tip": "请明确维修责任、损坏原因及费用凭证。",
        }], ensure_ascii=False))

    store = SimpleNamespace(get_status=lambda: SimpleNamespace(is_ready=True), search_review_evidence=retrieve)
    service = ContractReviewService(vector_store=store, llm=SimpleNamespace(invoke=invoke), settings=get_settings())
    result = service.analyze_contract_detailed(CONTRACT, top_k=1)
    assert result.status == "success"
    assert calls == [(CONTRACT, 1)]
    assert len(model_payloads[0]["法律依据"]) == 12  # Not truncated back to the global top_k=1.
    assert set(result.evidence_by_id) == ({"LAW-712", "LAW-713"} if cited else set())
    assert result.results[0].evidence_ids == (["LAW-712", "LAW-713"] if cited else [])
    assert next(item for item in result.trace if item.node == "retrieval").evidence_ids == [item.evidence_id for item in evidence]
    if cited:
        canonical = {law.law_id: law.content for law in laws}
        assert result.evidence_by_id["LAW-712"].content == canonical["LAW-712"]
