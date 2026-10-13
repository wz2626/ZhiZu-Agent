"""Offline frontend assets are served without exposing the repository."""

from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import PROJECT_ROOT
from backend.app.main import app


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.sources.extend(value for name, value in attrs if name == "src")


def test_home_uses_only_local_pinned_scripts():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    parser = ScriptSources()
    parser.feed(response.text)
    assert set(parser.sources) == {
        "./vendor/vue-3.5.13.global.prod.js",
        "./vendor/tailwindcss-browser-4.1.13.js",
    }
    assert len(parser.sources) == 2


@pytest.mark.parametrize(
    "filename", ["vue-3.5.13.global.prod.js", "tailwindcss-browser-4.1.13.js"]
)
def test_vendor_assets_load_from_another_working_directory(
    filename, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        response = client.get(f"/vendor/{filename}")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] in {
        "text/javascript",
        "application/javascript",
    }
    assert response.content == (
        PROJECT_ROOT / "frontend-web" / "vendor" / filename
    ).read_bytes()


@pytest.mark.parametrize(
    "url", ["/vendor/not-found.js", "/vendor/%2e%2e/%2e%2e/AGENTS.md"]
)
def test_vendor_rejects_missing_and_outside_files(url):
    with TestClient(app) as client:
        response = client.get(url)
    assert response.status_code == 404
    assert "ZhiZu-Agent 协作约定" not in response.text
