"""Build a Windows delivery ZIP from project sources and a fresh cloud law index."""

import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb
from dotenv import dotenv_values

from backend.app.core.config import get_settings, has_real_key
from backend.app.services.embedding import get_embeddings
from backend.app.services.vector_store import LawVectorStoreService, load_authoritative_laws

KB = ".runtime/chroma_cloud"
MARKER = ".runtime/zhizu-bundled-kb.json"
# Files needed before the first V6 commit. All other source entries must be tracked.
V6_FILES = {
    ".gitattributes", "启动智租博弈.bat", "配置模型服务.bat", "首次使用说明.md",
    "scripts/bootstrap.cmd", "scripts/configure_models.py", "scripts/launcher.py",
    "scripts/launcher_files.py", "scripts/package_release.py", "tests/test_startup.py",
}


def verify_index(path):
    laws = {law.law_id: law for law in load_authoritative_laws()}
    with LawVectorStoreService(path, embeddings=get_embeddings("cloud"), create_if_missing=False) as store:
        if not store.get_status().is_ready or len(store.client.list_collections()) != 1:
            raise ValueError("unexpected index identity, IDs or collections")
        rows = store.collection.get(include=["documents", "metadatas", "embeddings"])
        for law_id, doc, meta, vector in zip(rows["ids"], rows["documents"], rows["metadatas"],
                                             rows["embeddings"], strict=True):
            law = laws[law_id]
            if doc != law.content or meta != store._metadata(law):
                raise ValueError(f"source mismatch: {law_id}")
            if len(vector) != 1024 or not 0 < math.hypot(*vector) < math.inf:
                raise ValueError(f"invalid vector: {law_id}")


def build():
    settings = get_settings()
    if (not settings.embedding_configured or settings.embedding_model != "BAAI/bge-m3"
            or settings.embedding_base_url.rstrip("/") != "https://api.siliconflow.cn/v1"
            or chromadb.__version__ != "1.5.9" or sys.version_info[:2] != (3, 12)):
        raise ValueError("check release Python, Chroma, embedding configuration and model")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="kb-release-", dir=runtime))
    index = stage / "index"
    subprocess.run([sys.executable, "-X", "utf8", "scripts/init_kb.py", "--mode", "cloud",
                    "--persist-dir", str(index)], cwd=ROOT, check=True)
    verify_index(index)
    marker = dict(path=KB, identity="cloud:BAAI/bge-m3", dimension=1024, count=32,
                  python=platform.python_version(), chromadb=chromadb.__version__)
    tracked = subprocess.check_output(["git", "--no-optional-locks", "ls-files", "-z"], cwd=ROOT)
    names = set(tracked.decode("utf-8").split("\0")[:-1]) | V6_FILES
    files = {}
    for name in names:
        path = ROOT / name
        if (set(path.relative_to(ROOT).parts) & {".runtime", ".venv", ".env", ".git", "__pycache__",
                                                ".pytest_cache", "chroma_db", "instance.json"}
                or path.suffix.lower() in {".log", ".sqlite3", ".zip"} or path.is_symlink()):
            raise ValueError(f"unexpected source entry: {name}")
        files[name] = path
    for path in index.rglob("*"):
        if path.is_dir():
            continue
        name = path.relative_to(index).as_posix()
        if name != "chroma.sqlite3" and not re.fullmatch(
            r"[0-9a-f-]{36}/(data_level0|header|length|link_lists)\.bin", name
        ):
            raise ValueError(f"unexpected index entry: {name}")
        files[f"{KB}/{name}"] = path
    marker_file = stage / "marker.json"
    marker_file.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    files[MARKER] = marker_file
    secrets = {settings.chat_api_key, settings.embedding_api_key}
    local = dotenv_values(ROOT / ".env")
    secrets.update(local.get(key) or "" for key in ("CHAT_API_KEY", "EMBEDDING_API_KEY"))
    keys = [key.encode() for key in secrets if has_real_key(key)]
    dest = stage / "智租博弈-V6-Windows.zip"
    with zipfile.ZipFile(dest.with_suffix(".partial"), "x", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            data = path.read_bytes()
            if any(key in data for key in keys):
                raise ValueError(f"credential in {name}")
            if path.suffix.lower() in {".bat", ".cmd"} and b"\n" in data.replace(b"\r\n", b""):
                raise ValueError(f"batch file requires CRLF: {name}")
            archive.writestr(name, data)
    with zipfile.ZipFile(dest.with_suffix(".partial")) as archive:
        if set(archive.namelist()) != set(files):
            raise ValueError("archive manifest mismatch")
        for item in archive.infolist():
            if not item.filename.isascii() and not item.flag_bits & 0x800:
                raise ValueError("missing UTF-8 filename flag")
            if archive.read(item) != files[item.filename].read_bytes():
                raise ValueError(f"archive mismatch: {item.filename}")
    dest.with_suffix(".partial").rename(dest)
    print(dest, hashlib.sha256(dest.read_bytes()).hexdigest())


if __name__ == "__main__":
    build()
