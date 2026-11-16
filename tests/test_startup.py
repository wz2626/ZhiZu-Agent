"""V6 runtime identity, local configuration and cloud-index admission."""

import sqlite3
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from backend.app.core.config import PROJECT_ROOT, kb_path
from backend.app.main import app
from backend.app.services.embedding import DeterministicHashEmbeddings
from backend.app.services.vector_store import LawVectorStoreService


def test_status_keeps_legacy_health_and_separates_keys(monkeypatch):
    monkeypatch.setenv("ZHIZU_INSTANCE_ID", "fixture-instance")
    monkeypatch.setenv("CHAT_API_KEY", "fixture-chat")
    monkeypatch.setenv("EMBEDDING_API_KEY", "your_test_key")
    with TestClient(app) as client:
        status = client.get("/api/startup/status")
        assert status.json() == {"instance_id": "fixture-instance", "chat_configured": True,
                                 "embedding_configured": False}
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/api/startup/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert set(schema["components"]["schemas"][ref.split("/")[-1]]["required"]) == set(status.json())
        assert status.headers["cache-control"] == "no-store"
        assert set(client.get("/api/health").json()) == {"project", "version", "status", "env_configured"}


def test_paths_are_anchored_outside_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert kb_path("./backend/chroma_db") == PROJECT_ROOT / "backend" / "chroma_db"
    assert kb_path(tmp_path) == tmp_path
    with pytest.raises(ValueError):
        kb_path(" ")


def test_packaged_default_is_independent_of_index_presence(tmp_path, monkeypatch):
    from backend.app.core import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CHROMA_PATH", raising=False)
    (tmp_path / ".runtime/chroma_cloud").mkdir(parents=True)
    (tmp_path / "backend/chroma_db").mkdir(parents=True)
    assert config.get_settings().chroma_path == "./backend/chroma_db"
    (tmp_path / ".runtime/zhizu-bundled-kb.json").write_text("{}")
    assert config.get_settings().chroma_path == "./.runtime/chroma_cloud"
    (tmp_path / ".runtime/chroma_cloud").rmdir()
    assert config.get_settings().chroma_path == "./.runtime/chroma_cloud"
    monkeypatch.setenv("CHROMA_PATH", "./backend/chroma_db")
    assert config.get_settings().chroma_path == "./backend/chroma_db"


def test_existing_unknown_directory_and_unrelated_sqlite_protected(tmp_path):
    embeddings = DeterministicHashEmbeddings()
    inspect = lambda: LawVectorStoreService.inspect_status(tmp_path, embeddings=embeddings)
    assert inspect().state == "missing"
    (tmp_path / "sentinel").touch()
    assert inspect().state == "unreadable"
    db = tmp_path / "chroma.sqlite3"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE unrelated(id INTEGER)")
    before = db.read_bytes()
    assert inspect().state == "unreadable"
    assert db.read_bytes() == before


def test_cloud_config_refuses_existing_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "fixture-vector")
    with LawVectorStoreService(tmp_path, embeddings=DeterministicHashEmbeddings()) as kb:
        kb.ingest_laws()
    status = LawVectorStoreService.inspect_status(tmp_path)
    assert (status.indexed_count, status.embedding_mode, status.state) == (32, "mock", "incompatible")


def test_key_change_preserves_other_fields_and_comments(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))
    from configure_models import save_key

    path = tmp_path / ".env"
    path.write_bytes("# 模板\r\nCHAT_API_KEY=old  # 用于回复\r\nCHAT_MODEL=custom\r\n".encode())
    key = "new'key#1"
    save_key(path, "CHAT_API_KEY", key)
    assert dotenv_values(path)["CHAT_API_KEY"] == key
    assert b"  # " in path.read_bytes()
    assert path.read_bytes().endswith(b"CHAT_MODEL=custom\r\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_key(path, "CHAT_API_KEY", "invalid\nline")
    assert path.read_bytes() == before
    save_key(path, "EMBEDDING_API_KEY", "sample-vector")
    assert path.read_bytes().startswith(before)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher lock")
def test_lock_survives_stale_file_and_releases_on_exception(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))
    from launcher_files import file_lock, InUse

    lock = tmp_path / "start.lock"
    lock.touch()
    with pytest.raises(RuntimeError):
        with file_lock(lock):
            with pytest.raises(InUse):
                with file_lock(lock):
                    pytest.fail("second owner")
            raise RuntimeError()
    with file_lock(lock):
        assert lock.is_file()



def test_managed_cli_requires_launcher_id(monkeypatch):
    import os
    import subprocess

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("ZHIZU_INSTANCE_ID", None)
    result = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/start.py"), "--managed"],
                            capture_output=True, env=env)
    assert result.returncode == 2
    assert "省略 --managed" in result.stderr.decode("utf-8")


def test_requirement_probe_ignores_comments_but_checks_versions(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))
    from launcher import REQUIREMENT_CHECK

    for requirement, should_pass in [("pip>=1", True), ("pip<1", False), ("zhizu-missing-example", False)]:
        (tmp_path / "requirements.txt").write_text("  # 说明\n\n" + requirement, encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", "-c", REQUIREMENT_CHECK], cwd=tmp_path, capture_output=True)
        assert (result.returncode == 0) == should_pass


def test_bootstrap_candidates_check_version_and_pointer_width():
    import re
    from types import SimpleNamespace

    script = (PROJECT_ROOT / "scripts/bootstrap.cmd").read_text(encoding="utf-8")
    probes = re.findall(r'sys.exit\((.*?)\)"', script)
    assert len(probes) == 3
    for version, bits, rejected in [((3, 12), 63, False), ((3, 12), 31, True), ((3, 11), 63, True)]:
        candidate = SimpleNamespace(version_info=version, maxsize=(1 << bits) - 1)
        assert all(eval(probe, {"sys": candidate, "__builtins__": {}}) == rejected for probe in probes)
