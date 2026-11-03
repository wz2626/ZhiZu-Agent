"""Admission and strict protocol regressions (no external services)."""

import json

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.app.core.http_limits import ApiBoundary

from backend.app.main import app


def test_strict_endpoint_matrix(monkeypatch):
    monkeypatch.delenv("V4_ALLOW_LEGACY_HEADERS", raising=False)
    monkeypatch.setenv("CHAT_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    with TestClient(app) as client:
        meta = client.get("/api/negotiation/meta")
        assert meta.status_code == 200
        assert meta.headers["cache-control"] == "no-store"
        assert client.post("/api/review/analyze-detailed", json={"contract_text": "租客每月支付租金并由房东负责维修。"}).status_code == 409
        result = client.post("/api/review/analyze-detailed", json={"contract_text": "租客每月支付租金并由房东负责维修。"}, headers={"X-Interaction-Version": "4"})
        assert result.status_code == 200  # No practice headers on review.
        result = client.post("/api/review/proposal", json={"review_context_id": "a" * 32, "clause_id": "C-01", "goal_text": "请核对费用。", "draft_request_id": "d"}, headers={"X-Interaction-Version": "4"})
        assert result.status_code == 410  # Ownership, not missing practice heads.
        assert client.post("/api/negotiation/turn", json={"session_id": "strict", "request_id": "r", "user_input": "请核对费用。"}).status_code == 409


@pytest.mark.parametrize("content,status", [
    (b" " * (256 * 1024 + 1), 413),
    (b'[' * 40 + b'0' + b']' * 40, 413),
    (b'{"contract_text":"secret","contract_text":"other"}', 422),
    (b'{"top_k":NaN}', 422),
], ids=["bytes", "depth", "duplicate", "nonfinite"])
def test_json_limits_are_safe(content, status):
    with TestClient(app) as client:
        result = client.post("/api/review/analyze-detailed", content=content, headers={"Content-Type": "application/json"})
        assert result.status_code == status
        assert "secret" not in result.text
        assert result.headers["cache-control"] == "no-store"


def test_streamed_body_limit_without_content_length():
    with TestClient(app) as client:
        result = client.post("/api/review/analyze", content=iter([b"x" * 180000, b"x" * 180000]), headers={"Content-Type": "application/json"})
        assert result.status_code == 413


def test_multiworker_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="one process"):
        with TestClient(app):
            pass


def test_extra_field_name_is_not_reflected_in_safe_422():
    with TestClient(app) as client:
        result = client.post("/api/review/analyze", json={"contract_text": "房东应当按约负责维修并交付房屋。", "13800000000": "private"})
        assert result.status_code == 422
        assert "13800000000" not in result.text and "private" not in result.text


def test_duplicate_keys_without_content_type_are_rejected():
    with TestClient(app) as client:
        result = client.post("/api/review/analyze", content=b'{"contract_text":"private","contract_text":"other"}')
        assert result.status_code == 422 and "private" not in result.text


def test_unhandled_exception_cannot_bubble_private_text_to_server_logger(caplog):
    isolated = FastAPI()
    isolated.add_middleware(ApiBoundary)
    @isolated.get("/api/fault")
    def fault():
        raise ValueError("private-contract-13800000000")
    # Default raise_server_exceptions=True proves the exception is contained,
    # rather than merely hidden in an error response and re-raised by Starlette.
    with TestClient(isolated) as client:
        result = client.get("/api/fault")
    assert result.status_code == 500 and result.json()["detail"]["code"] == "INTERNAL_ERROR"
    assert "private-contract" not in result.text + caplog.text
    assert "13800000000" not in result.text + caplog.text
