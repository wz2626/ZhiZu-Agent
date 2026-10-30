"""Invalid API requests must not echo unredacted payloads in diagnostics."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAT_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("CHAT_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "absent-kb"))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("endpoint,field,limit", [
    ("/api/review/analyze", "contract_text", 5000),
    ("/api/review/analyze-detailed", "contract_text", 5000),
    ("/api/kb/search", "query", 500),
])
def test_overlong_request_does_not_echo_private_text(client, endpoint, field, limit):
    private_text = "合成住址测试甲路1号 13800000147 99000020010101001X"
    response = client.post(endpoint, json={field: private_text + "租" * limit})
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["type"] == "string_too_long" and error["loc"] == ["body", field]
               for error in errors)
    assert all("input" not in error and "ctx" not in error for error in errors)
    for secret in ["13800000147", "99000020010101001X", "合成住址测试甲路1号"]:
        assert secret not in response.text


@pytest.mark.parametrize("endpoint", [
    "/api/review/analyze", "/api/review/analyze-detailed", "/api/kb/search",
    "/api/review/proposal", "/api/negotiation/turn",
])
def test_wrong_body_type_does_not_echo_entire_payload(client, endpoint):
    response = client.post(endpoint, json=["合成姓名及住址", "13800000147"])
    assert response.status_code == 422
    assert "13800000147" not in response.text
    assert "合成姓名及住址" not in response.text


@pytest.mark.parametrize("endpoint", ["/api/review/analyze", "/api/review/analyze-detailed", "/api/kb/search"])
def test_invalid_numeric_field_does_not_echo_private_input(client, endpoint):
    field = "query" if endpoint.endswith("search") else "contract_text"
    response = client.post(endpoint, json={field: "房东应承担房屋维修责任。", "top_k": "13800000147"})
    assert response.status_code == 422
    assert "13800000147" not in response.text
    assert any(error["loc"] == ["body", "top_k"] for error in response.json()["detail"])
