import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.core.config import get_settings, has_real_key
from backend.app.schemas.knowledge import EvidenceItem, KBSearchRequest, chinese_article_no
from backend.app.services.embedding import DeterministicHashEmbeddings, SiliconFlowEmbeddings, get_embeddings
from backend.app.services.vector_store import (
    LAW_FILE, LawVectorStoreService, load_authoritative_laws, mask_sensitive_text,
)


def test_authoritative_json_is_complete_and_consecutive():
    raw = json.loads(LAW_FILE.read_text(encoding="utf-8"))
    laws = load_authoritative_laws()
    assert len(raw) == len(laws) == 32
    assert [law.article_number for law in laws] == list(range(703, 735))
    assert len({law.law_id for law in laws}) == 32
    for law in laws:
        assert law.law_id == f"LAW-{law.article_number}"
        assert law.article_no == chinese_article_no(law.article_number)
        assert law.law_name == "中华人民共和国民法典"
        assert law.part_chapter == "第三编 合同 / 第十四章 租赁合同"
        assert str(law.source_url) == "https://www.court.gov.cn/zixun/xiangqing/233181.html"
        assert law.verified_date.isoformat() == "2026-10-05"
        assert law.content and "…" not in law.content and "..." not in law.content
        assert law.topic_tags
    by_id = {law.law_id: law for law in laws}
    assert "因承租人的过错" in by_id["LAW-713"].content
    assert "（三）租赁物具有违反法律" in by_id["LAW-724"].content
    assert "优先承租的权利" in by_id["LAW-734"].content


def test_loader_does_not_scan_scenarios(tmp_path, monkeypatch):
    scenarios = tmp_path / "backend" / "data" / "scenarios"
    scenarios.mkdir(parents=True)
    (scenarios / "fake_law.json").write_text('{"law_id":"SCENARIO-01"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert {law.law_id for law in load_authoritative_laws()} == {
        f"LAW-{number}" for number in range(703, 735)
    }


def test_embedding_is_stable_and_has_topic_signal(monkeypatch):
    embedder = DeterministicHashEmbeddings()
    first = embedder.embed_query("房东不维修漏水房屋")
    assert len(first) == 1024
    assert first == embedder.embed_query("房东不维修漏水房屋")
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert first != embedder.embed_query("未经同意擅自转租")
    monkeypatch.setenv("EMBEDDING_API_KEY", "your_embedding_api_key_here")
    assert isinstance(get_embeddings("auto"), DeterministicHashEmbeddings)
    with pytest.raises(ValueError, match="configured API key"):
        get_embeddings("cloud")


def test_cloud_embedding_response_and_secret_safe_error(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [
                {"index": 1, "embedding": [0, 1.0]},
                {"index": 0, "embedding": [1.0, 0]},
            ]}

    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("backend.app.services.embedding.httpx.post", fake_post)
    secret = "sk-private-test-secret"
    embedder = SiliconFlowEmbeddings(
        base_url="https://example.invalid/v1/", model="BAAI/bge-m3",
        api_key=secret, expected_dimension=2,
    )
    assert embedder.embed_documents(["维修", "转租"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert calls[0][0] == "https://example.invalid/v1/embeddings"
    assert calls[0][1]["timeout"] == 20.0
    assert secret not in repr(embedder)

    def failing_post(url, **kwargs):
        raise ValueError(secret)

    monkeypatch.setattr("backend.app.services.embedding.httpx.post", failing_post)
    with pytest.raises(RuntimeError) as error:
        embedder.embed_documents(["维修"])
    assert secret not in str(error.value)


def test_ingest_is_idempotent_and_retrievable(tmp_path):
    service = LawVectorStoreService(tmp_path / "chroma", embeddings=DeterministicHashEmbeddings())
    first = service.ingest_laws()
    second = service.ingest_laws()
    assert (first.before_count, first.inserted_count, first.updated_count, first.total_count) == (0, 32, 0, 32)
    assert (second.before_count, second.inserted_count, second.updated_count, second.total_count) == (32, 0, 32, 32)
    assert service.collection.count() == 32
    assert set(service.collection.get(include=[])["ids"]) == {f"LAW-{i}" for i in range(703, 735)}
    found = service.get_laws_by_ids(["LAW-712", "LAW-999", "SCENARIO-01", "LAW-712", "LAW-731"])
    assert [item.evidence_id for item in found] == ["LAW-712", "LAW-731"]
    assert all(isinstance(item, EvidenceItem) for item in found)
    assert service.get_laws_by_ids(["LAW-999", "SCENARIO-01"]) == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("房东扣留押金，退租后如何返还押金？", None),
        ("房屋漏水需要维修，房东不修谁承担维修费用？", {"LAW-712", "LAW-713"}),
        ("承租人未经同意擅自转租，出租人可以解约吗？", {"LAW-716"}),
        ("不定期租赁解除合同，需要提前多久通知对方？", {"LAW-730"}),
        ("房屋危及安全或者甲醛超标影响健康，承租人能否解除合同？", {"LAW-731"}),
    ],
)
def test_five_queries_recall_authoritative_evidence(tmp_path, query, expected):
    service = LawVectorStoreService(tmp_path / "chroma", embeddings=DeterministicHashEmbeddings())
    service.ingest_laws()
    evidence = service.search_evidence(query, top_k=3)
    assert len(evidence) == 3
    assert all(isinstance(item, EvidenceItem) and item.evidence_id.startswith("LAW-") for item in evidence)
    assert all(str(item.source_url) == "https://www.court.gov.cn/zixun/xiangqing/233181.html" for item in evidence)
    if expected:
        assert {item.evidence_id for item in evidence} & expected


def test_query_boundaries_and_collection_separation(tmp_path):
    path = tmp_path / "chroma"
    service = LawVectorStoreService(path, embeddings=DeterministicHashEmbeddings())
    with pytest.raises(ValueError, match="empty"):
        service.search_evidence("  ")
    with pytest.raises(ValueError, match="top_k"):
        service.search_evidence("维修", top_k=0)
    with pytest.raises(ValueError):
        KBSearchRequest(query="  ")
    service.collection.upsert(ids=["SCENARIO-01"], documents=["演练话术"], embeddings=[service.embeddings.embed_query("演练话术")])
    with pytest.raises(ValueError, match="non-authoritative"):
        service.ingest_laws()
    with pytest.raises(ValueError, match="non-authoritative"):
        service.search_evidence("维修")


def test_mode_guard_and_authoritative_evidence_reconstruction(tmp_path):
    path = tmp_path / "chroma"
    service = LawVectorStoreService(path, embeddings=DeterministicHashEmbeddings())
    service.ingest_laws()
    original = next(item for item in load_authoritative_laws() if item.law_id == "LAW-712")
    service.collection.update(
        ids=["LAW-712"], documents=["伪造正文"],
        metadatas=[{"source_url": "https://example.invalid/fake"}],
        embeddings=[service.embeddings.embed_query("伪造正文")],
    )
    evidence = service.get_laws_by_ids(["LAW-712"])[0]
    assert evidence.content == original.content
    assert str(evidence.source_url) == str(original.source_url)

    class OtherMode(DeterministicHashEmbeddings):
        mode = "cloud"

    with pytest.raises(ValueError, match="embedding mode differs"):
        LawVectorStoreService(path, embeddings=OtherMode())

    class OtherModel(DeterministicHashEmbeddings):
        model = "other-model"

    with pytest.raises(ValueError, match="embedding model differs"):
        LawVectorStoreService(path, embeddings=OtherModel())


def test_cloud_query_masks_phone_and_id_before_embedding(tmp_path):
    class SpyEmbeddings(DeterministicHashEmbeddings):
        mode = "cloud"

        def embed_query(self, text):
            self.last_query = text
            return super().embed_query(text)

    embeddings = SpyEmbeddings()
    service = LawVectorStoreService(tmp_path / "chroma", embeddings=embeddings)
    service.ingest_laws()
    service.search_evidence("维修请联系13800138000，身份证110101199001011234")
    assert "13800138000" not in embeddings.last_query
    assert "110101199001011234" not in embeddings.last_query
    assert "[手机号]" in embeddings.last_query
    assert "[身份证号]" in embeddings.last_query


def test_cli_mock_mode_is_idempotent(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "init_kb.py"
    env = os.environ.copy()
    env["EMBEDDING_API_KEY"] = ""
    command = [sys.executable, str(script), "--mode", "mock", "--persist-dir", str(tmp_path / "cli_chroma"), "--verify-queries"]
    first = subprocess.run(command, cwd=script.parents[1], env=env, capture_output=True, text=True, check=True)
    second = subprocess.run(command, cwd=script.parents[1], env=env, capture_output=True, text=True, check=True)
    first_lines = [json.loads(line) for line in first.stdout.splitlines()]
    second_lines = [json.loads(line) for line in second.stdout.splitlines()]
    assert (first_lines[0]["inserted_count"], first_lines[0]["updated_count"], first_lines[0]["total_count"]) == (32, 0, 32)
    assert (second_lines[0]["inserted_count"], second_lines[0]["updated_count"], second_lines[0]["total_count"]) == (0, 32, 32)
    assert len(first_lines) == len(second_lines) == 6
    assert all(len(line["evidence"]) == 3 for line in first_lines[1:])
    assert "直接依据不足" in first_lines[1]["note"] or "没有直接规定" in first_lines[1]["note"]


@pytest.mark.parametrize(
    "invalid_value", [True, False, "0.1", None, float("nan"), float("inf"), -float("inf")],
    ids=["true", "false", "numeric-string", "null", "nan", "infinity", "negative-infinity"],
)
def test_cloud_rejects_invalid_vector_elements(monkeypatch, invalid_value):
    secret = "sk-synthetic-element-test"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, invalid_value]}]}

    monkeypatch.setattr("backend.app.services.embedding.httpx.post", lambda *args, **kwargs: FakeResponse())
    embeddings = SiliconFlowEmbeddings(
        base_url="https://example.invalid/v1", model="test-model",
        api_key=secret, expected_dimension=2,
    )
    with pytest.raises(ValueError, match="element 1.*finite int or float") as error:
        embeddings.embed_query("维修")
    assert secret not in str(error.value)


@pytest.mark.parametrize("query", ["！！！", "😀🏠", "\u200b\u200c\u200d"])
def test_zero_vector_query_does_not_call_chroma(tmp_path, monkeypatch, query):
    with LawVectorStoreService(tmp_path / "chroma", embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()

        def unexpected_query(*args, **kwargs):
            pytest.fail("zero vectors must not reach Chroma query")

        monkeypatch.setattr(type(service.collection), "query", unexpected_query)
        assert service.search_evidence(query) == []


@pytest.mark.parametrize("distance", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_distance_is_rejected(tmp_path, monkeypatch, distance):
    with LawVectorStoreService(tmp_path / "chroma", embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
        monkeypatch.setattr(
            type(service.collection), "query",
            lambda *args, **kwargs: {"ids": [["LAW-712"]], "distances": [[distance]]},
        )
        with pytest.raises(ValueError, match="distance must be finite"):
            service.search_evidence("维修")


def test_zero_scores_are_removed_and_small_positive_scores_are_kept(tmp_path, monkeypatch):
    with LawVectorStoreService(tmp_path / "chroma", embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
        monkeypatch.setattr(
            type(service.collection), "query",
            lambda *args, **kwargs: {
                "ids": [["LAW-703", "LAW-704", "LAW-705", "LAW-706"]],
                "distances": [[1.0, 1.2, 0.99, 0.4]],
            },
        )
        evidence = service.search_evidence("修")
        assert [item.evidence_id for item in evidence] == ["LAW-705", "LAW-706"]
        assert [item.score for item in evidence] == pytest.approx([0.01, 0.6])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("+8613800138000", "[手机号]"),
        ("8613800138000", "[手机号]"),
        ("+86 13800138000", "[手机号]"),
        ("138-0013-8000", "[手机号]"),
        ("138 0013 8000", "[手机号]"),
        ("+86-138-0013-8000", "[手机号]"),
        ("110101900101123", "[身份证号]"),
        ("110101199001011234", "[身份证号]"),
        ("11010119900101123X", "[身份证号]"),
        ("11010119900101123x", "[身份证号]"),
    ],
)
def test_sensitive_number_formats_are_masked(text, expected):
    assert mask_sensitive_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "银行卡6222021234567890",
        "银行卡622202123456789012",
        "订单6222021234567890123",
        "金额138001380000元",
        "订单1101011990010112349",
        "日期2026-10-07和20261007",
        "民法典第712条、LAW-712、第七百一十二条",
    ],
)
def test_unrelated_numbers_and_long_digit_boundaries_are_preserved(text):
    assert mask_sensitive_text(text) == text


@pytest.mark.parametrize(
    ("key", "configured"),
    [
        ("", False), (" YOUR_embedding_api_key_here ", False),
        ("placeholder", False), ("replace_me", False),
        ("请填入密钥", False), ("示例密钥", False),
        ("sk-synthetic-configured", True),
    ],
)
def test_key_configuration_and_embedding_mode_agree(monkeypatch, key, configured):
    for name, value in {
        "CHAT_BASE_URL": "https://example.invalid/v1",
        "CHAT_MODEL": "test-chat", "CHAT_API_KEY": key,
        "EMBEDDING_BASE_URL": "https://example.invalid/v1",
        "EMBEDDING_MODEL": "test-embedding", "EMBEDDING_API_KEY": key,
        "CHROMA_PATH": ".runtime/not-opened",
    }.items():
        monkeypatch.setenv(name, value)
    assert has_real_key(key) is configured
    assert get_settings().env_configured is configured
    assert get_embeddings("auto").mode == ("cloud" if configured else "mock")
