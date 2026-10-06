"""KB API contracts and cloud vector guardrails, with isolated Chroma paths."""

import sqlite3

import chromadb
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.embedding import DeterministicHashEmbeddings, SiliconFlowEmbeddings
from backend.app.services.vector_store import LawVectorStoreService


@pytest.fixture
def kb_environment(monkeypatch, tmp_path):
    directory = tmp_path / "chroma"
    monkeypatch.setenv("CHROMA_PATH", str(directory))
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    with TestClient(app) as client:
        yield client, directory


@pytest.mark.parametrize("actual_dimension", [0, 512, 1536])
def test_cloud_dimension_mismatch_is_clear_and_secret_safe(monkeypatch, actual_dimension):
    secret = "sk-private-dimension-test"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1] * actual_dimension}]}

    monkeypatch.setattr("backend.app.services.embedding.httpx.post", lambda *args, **kwargs: FakeResponse())
    embeddings = SiliconFlowEmbeddings(
        base_url="https://example.invalid/v1", model="BAAI/bge-m3", api_key=secret,
    )
    with pytest.raises(ValueError, match=f"expected 1024, got {actual_dimension}") as error:
        embeddings.embed_query("房屋维修")
    assert secret not in str(error.value)


def test_uninitialized_status_is_read_only_and_search_returns_503(kb_environment, monkeypatch):
    client, directory = kb_environment

    def unexpected_client(*args, **kwargs):
        pytest.fail("missing SQLite files must not construct PersistentClient")

    monkeypatch.setattr(chromadb, "PersistentClient", unexpected_client)
    assert not directory.exists()
    status_response = client.get("/api/kb/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["collection_name"] == "civil_code_lease_laws"
    assert status["persist_directory"] == str(directory.resolve())
    assert status["authoritative_law_count"] == 32
    assert status["indexed_count"] == 0
    assert status["is_ready"] is False
    assert status["embedding_mode"] == "mock"
    assert status["source_url"] == "https://www.court.gov.cn/zixun/xiangqing/233181.html"
    assert status["verified_date"] == "2026-10-05"
    assert not directory.exists()

    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "KB_NOT_READY",
        "message": "知识库尚未就绪，请先运行 scripts/init_kb.py。",
        "indexed_count": 0,
    }
    assert not directory.exists()


def test_status_after_ingest_and_metadata_guard(kb_environment):
    client, directory = kb_environment
    service = LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings())
    assert service.ingest_laws().total_count == 32
    assert service.ingest_laws().total_count == 32
    assert service.collection.metadata["embedding_dimension"] == 1024
    status = client.get("/api/kb/status").json()
    assert status["indexed_count"] == 32
    assert status["is_ready"] is True
    assert status["embedding_mode"] == "mock"

    changed_metadata = dict(service.collection.metadata)
    changed_metadata.pop("hnsw:space", None)
    changed_metadata["embedding_dimension"] = 512
    service.collection.modify(metadata=changed_metadata)
    assert client.get("/api/kb/status").json()["is_ready"] is False
    assert client.post("/api/kb/search", json={"query": "维修"}).status_code == 503
    with pytest.raises(ValueError, match="expected 1024, got 512"):
        LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings())


def test_empty_or_contaminated_collection_is_not_ready(kb_environment):
    client, directory = kb_environment
    service = LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings())
    empty_status = client.get("/api/kb/status").json()
    assert empty_status["indexed_count"] == 0
    assert empty_status["is_ready"] is False
    assert client.post("/api/kb/search", json={"query": "维修"}).status_code == 503

    service.ingest_laws()
    service.collection.upsert(
        ids=["SCENARIO-01"], documents=["演练案例"],
        embeddings=[service.embeddings.embed_query("演练案例")],
    )
    contaminated_status = client.get("/api/kb/status").json()
    assert contaminated_status["indexed_count"] == 33
    assert contaminated_status["is_ready"] is False
    assert client.post("/api/kb/search", json={"query": "维修"}).status_code == 503


def test_legacy_collection_dimension_metadata_migrates_on_ingest(kb_environment):
    client, directory = kb_environment
    service = LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings())
    service.ingest_laws()
    old_metadata = dict(service.collection.metadata)
    old_metadata.pop("embedding_dimension")
    old_metadata.pop("hnsw:space", None)
    service.collection.modify(metadata=old_metadata)
    assert client.get("/api/kb/status").json()["is_ready"] is False
    assert service.ingest_laws().updated_count == 32
    assert service.collection.metadata["embedding_dimension"] == 1024
    assert client.get("/api/kb/status").json()["is_ready"] is True


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("房东扣留押金，退租后如何返还押金？", "LAW-733"),
        ("房屋漏水维修费用由谁承担？", "LAW-712"),
        ("承租人未经同意转租可以解约吗？", "LAW-716"),
        ("提前退租如何通知房东？", None),
    ],
)
def test_search_returns_authoritative_evidence(kb_environment, query, expected_id):
    client, directory = kb_environment
    LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()).ingest_laws()
    response = client.post("/api/kb/search", json={"query": query})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == query
    assert payload["top_k"] == 4
    assert len(payload["results"]) == 4
    ids = {item["evidence_id"] for item in payload["results"]}
    assert ids <= {f"LAW-{number}" for number in range(703, 735)}
    assert all(item["source_url"] == "https://www.court.gov.cn/zixun/xiangqing/233181.html" for item in payload["results"])
    if expected_id:
        assert expected_id in ids
    if "押金" in query:
        assert payload["direct_basis_sufficient"] is False
        assert "无直接规定押金" in payload["boundary_notice"]
        assert "合同约定" in payload["boundary_notice"]
    if "提前退租" in query:
        assert payload["direct_basis_sufficient"] is False
        assert "合同约定" in payload["boundary_notice"]


def test_search_masks_synthetic_personal_data(kb_environment):
    client, directory = kb_environment
    LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()).ingest_laws()
    response = client.post("/api/kb/search", json={
        "query": "维修请联系13800138000，身份证110101199001011234",
        "top_k": 2,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "维修请联系[手机号]，身份证[身份证号]"
    assert payload["top_k"] == 2
    assert len(payload["results"]) == 2
    assert "13800138000" not in response.text
    assert "110101199001011234" not in response.text


@pytest.mark.parametrize(
    "request_body",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "维" * 501},
        {"query": "维修", "top_k": 0},
        {"query": "维修", "top_k": 9},
    ],
)
def test_search_request_validation_returns_422(kb_environment, request_body):
    client, directory = kb_environment
    response = client.post("/api/kb/search", json=request_body)
    assert response.status_code == 422
    assert not directory.exists()


def test_empty_directory_is_not_initialized(kb_environment, monkeypatch):
    client, directory = kb_environment
    directory.mkdir()

    def unexpected_client(*args, **kwargs):
        pytest.fail("empty directories must not construct PersistentClient")

    monkeypatch.setattr(chromadb, "PersistentClient", unexpected_client)
    status = client.get("/api/kb/status")
    assert status.status_code == 200
    assert status.json()["is_ready"] is False
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KB_NOT_READY"
    assert list(directory.iterdir()) == []


def test_corrupted_sqlite_file_degrades_safely(kb_environment):
    """Fault injection: this file is deliberately not a SQLite database."""
    client, directory = kb_environment
    directory.mkdir()
    database = directory / "chroma.sqlite3"
    corrupt_bytes = b"synthetic broken sqlite database"
    database.write_bytes(corrupt_bytes)

    status = client.get("/api/kb/status")
    assert status.status_code == 200
    assert status.json()["is_ready"] is False
    assert status.json()["indexed_count"] == 0
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KB_NOT_READY"
    assert response.json()["detail"]["indexed_count"] == 0
    assert database.read_bytes() == corrupt_bytes


@pytest.mark.parametrize("stage", ["client", "collection", "ids"])
@pytest.mark.parametrize("error_type", [chromadb.errors.InternalError, sqlite3.DatabaseError, ValueError])
def test_storage_inspection_errors_are_not_ready(kb_environment, monkeypatch, stage, error_type):
    client, directory = kb_environment
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
        client_type = type(service.client)
        collection_type = type(service.collection)

    def fail_storage(*args, **kwargs):
        raise error_type("synthetic private database diagnostic")

    if stage == "client":
        monkeypatch.setattr(chromadb, "PersistentClient", fail_storage)
    elif stage == "collection":
        monkeypatch.setattr(client_type, "get_collection", fail_storage)
    else:
        monkeypatch.setattr(collection_type, "get", fail_storage)
    status = client.get("/api/kb/status")
    assert status.status_code == 200
    assert status.json()["is_ready"] is False
    assert status.json()["indexed_count"] == 0
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KB_NOT_READY"
    assert "private database diagnostic" not in status.text + response.text


@pytest.mark.parametrize("error_type", [ValueError, chromadb.errors.InternalError, sqlite3.DatabaseError])
def test_collection_error_during_search_returns_503(kb_environment, monkeypatch, error_type):
    client, directory = kb_environment
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()

    def fail_collection(self):
        raise error_type("synthetic collection failure after readiness check")

    monkeypatch.setattr(LawVectorStoreService, "_check_ids", fail_collection)
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KB_NOT_READY"
    assert response.json()["detail"]["indexed_count"] == 32


@pytest.mark.parametrize("failure", ["dimension", "distance"])
def test_query_vector_or_distance_error_returns_503(kb_environment, monkeypatch, failure):
    client, directory = kb_environment
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
        collection_type = type(service.collection)
    if failure == "dimension":
        monkeypatch.setattr(DeterministicHashEmbeddings, "embed_query", lambda *args: [0.1] * 512)
    else:
        monkeypatch.setattr(
            collection_type, "query",
            lambda *args, **kwargs: {"ids": [["LAW-712"]], "distances": [[float("nan")]]},
        )
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KB_NOT_READY"


def test_cloud_embedding_failure_has_distinct_error_code(kb_environment, monkeypatch):
    client, directory = kb_environment
    secret = "sk-synthetic-upstream-error"

    class FailingCloudEmbeddings(DeterministicHashEmbeddings):
        mode = "cloud"
        model = "test-cloud-model"

        def embed_query(self, text):
            raise RuntimeError(secret)

    monkeypatch.setattr("backend.app.services.vector_store.get_embeddings", FailingCloudEmbeddings)
    with LawVectorStoreService(directory) as service:
        service.ingest_laws()
    assert client.get("/api/kb/status").json()["is_ready"] is True
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "UPSTREAM_EMBEDDING_ERROR",
        "message": "云端向量服务异常，请稍后重试。",
    }
    assert secret not in response.text


def test_search_constructs_one_persistent_client(kb_environment, monkeypatch):
    client, directory = kb_environment
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
    original_client = chromadb.PersistentClient
    paths = []

    def counted_client(*args, **kwargs):
        paths.append(kwargs["path"])
        return original_client(*args, **kwargs)

    monkeypatch.setattr(chromadb, "PersistentClient", counted_client)
    response = client.post("/api/kb/search", json={"query": "维修"})
    assert response.status_code == 200
    assert response.json()["results"]
    assert paths == [str(directory.resolve())]


@pytest.mark.parametrize("query", ["！！！", "😀🏠", "\u200b\u200c\u200d"])
def test_meaningless_query_returns_empty_evidence(kb_environment, query):
    client, directory = kb_environment
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
    response = client.post("/api/kb/search", json={"query": query})
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_search_masks_extended_formats_and_preserves_dates(kb_environment):
    client, directory = kb_environment
    with LawVectorStoreService(directory, embeddings=DeterministicHashEmbeddings()) as service:
        service.ingest_laws()
    response = client.post("/api/kb/search", json={
        "query": "维修联系+8613800138000或138-0013-8000，旧身份证110101900101123，日期2026-10-07，第712条",
    })
    assert response.status_code == 200
    assert response.json()["query"] == "维修联系[手机号]或[手机号]，旧身份证[身份证号]，日期2026-10-07，第712条"
