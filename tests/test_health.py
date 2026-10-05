import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app


@pytest.fixture
def client(monkeypatch):
    """Use synthetic configuration, independent of the developer's real .env."""
    values = {
        "CHAT_BASE_URL": "https://chat.example.invalid/v1",
        "CHAT_MODEL": "test-chat-model",
        "CHAT_API_KEY": "",
        "EMBEDDING_BASE_URL": "https://embedding.example.invalid/v1",
        "EMBEDDING_MODEL": "test-embedding-model",
        "EMBEDDING_API_KEY": "",
        "CHROMA_PATH": "./backend/chroma_db",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    with TestClient(app) as test_client:
        yield test_client


def test_health_without_api_keys(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "project": "ZhiZu-Agent",
        "version": "0.1.0",
        "env_configured": False,
    }


@pytest.mark.parametrize(
    ("chat_key", "embedding_key", "configured"),
    [
        ("your_chat_api_key_here", "your_embedding_api_key_here", False),
        ("test-chat-key-not-real", "", False),
        ("   ", "   ", False),
        ("test-chat-key-not-real", "test-embedding-key-not-real", True),
    ],
)
def test_health_configuration_and_secret_protection(
    client, monkeypatch, chat_key, embedding_key, configured
):
    monkeypatch.setenv("CHAT_API_KEY", chat_key)
    monkeypatch.setenv("EMBEDDING_API_KEY", embedding_key)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["env_configured"] is configured
    assert set(response.json()) == {"status", "project", "version", "env_configured"}
    assert "test-chat-key-not-real" not in response.text
    assert "test-embedding-key-not-real" not in response.text


def test_settings_read_configuration_without_exposing_keys(client, monkeypatch):
    monkeypatch.setenv("CHAT_API_KEY", "test-chat-key-not-real")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-embedding-key-not-real")
    settings = get_settings()
    assert settings.chat_base_url == "https://chat.example.invalid/v1"
    assert settings.chat_model == "test-chat-model"
    assert settings.embedding_base_url == "https://embedding.example.invalid/v1"
    assert settings.embedding_model == "test-embedding-model"
    assert settings.chroma_path == "./backend/chroma_db"
    assert settings.env_configured is True
    assert "test-chat-key-not-real" not in repr(settings)
    assert "test-embedding-key-not-real" not in repr(settings)


def test_root_serves_same_origin_page_from_another_directory(
    client, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "智租博弈" in response.text
    assert 'fetch("/api/health"' in response.text
    assert 'href="/docs"' in response.text


def test_api_documentation(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"] == {"title": "ZhiZu-Agent API", "version": "0.1.0"}
    assert "/api/health" in schema["paths"]


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:8000", "http://localhost:8000"]
)
def test_cors_allows_local_origins(client, origin):
    response = client.options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_rejects_unlisted_origin(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "https://unlisted.example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
