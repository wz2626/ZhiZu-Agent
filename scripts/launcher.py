"""Prepare and start one local Windows workbench. Requires only the stdlib initially."""

import argparse
import hashlib
import http.client
import json
import os
import subprocess
import sys
import time
import uuid
import webbrowser

from launcher_files import ROOT, RUNTIME, InUse, atomic_write, file_lock, read_record

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
REQUIREMENTS = ROOT / "requirements.txt"


REQUIREMENT_CHECK = """from importlib.metadata import version
from pathlib import Path
from pip._vendor.packaging.requirements import Requirement
for line in Path('requirements.txt').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    req = Requirement(line)
    assert req.specifier.contains(version(req.name), prereleases=True)
"""


def run_python(*args):
    subprocess.run([str(PYTHON), "-X", "utf8", *args], cwd=ROOT, check=True)


def prepare_environment():
    if not PYTHON.is_file():
        print("正在创建 Python 3.12 项目环境…", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    fingerprint = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    marker = PYTHON.parents[1] / ".zhizu-requirements"
    previously_verified = marker.is_file() and marker.read_bytes() == fingerprint.encode()
    # Check package metadata even on repeat launches so interrupted upgrades can be repaired.
    check = REQUIREMENT_CHECK
    if not previously_verified:
        check += "import fastapi, uvicorn, chromadb, docx, pdfplumber, python_multipart, langgraph"
    probe = [str(PYTHON), "-I", "-c", check]
    if subprocess.run(probe, cwd=ROOT, stderr=subprocess.DEVNULL).returncode:
        print("首次安装或修复项目依赖，需要联网。以下为安装进度…", flush=True)
        if subprocess.run([str(PYTHON), "-m", "pip", "--version"], stdout=subprocess.DEVNULL).returncode:
            run_python("-m", "ensurepip", "--upgrade")
        run_python("-m", "pip", "install", "-r", str(REQUIREMENTS))
        subprocess.run(probe, cwd=ROOT, check=True)
    if not previously_verified:
        atomic_write(marker, fingerprint.encode())


def instance_online(record):
    if not record:
        return False
    connection = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=0.8)
    try:
        connection.request("GET", "/api/startup/status")
        response = connection.getresponse()
        if response.status != 200:
            return False
        data = json.loads(response.read(4096))
        return isinstance(data, dict) and data.get("instance_id") == record["id"]
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return False
    finally:
        connection.close()


def show_page(record, open_browser):
    url = f"http://127.0.0.1:{record['port']}/"
    print("工作台地址", url, flush=True)
    if open_browser:
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            print("请在浏览器中手动访问上方工作台地址。", flush=True)


def initialize_config():
    with file_lock(RUNTIME / "config.lock"):
        if not (ROOT / ".env").exists():
            atomic_write(ROOT / ".env", (ROOT / ".env.example").read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "configure"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    child = None
    try:
        with file_lock(RUNTIME / "startup.lock"):
            if args.action == "start":
                record = read_record()
                if instance_online(record):
                    print("此目录的工作台已运行。")
                    show_page(record, not args.no_browser)
                    return 0
            prepare_environment()
            initialize_config()
            if args.action == "configure":
                run_python("scripts/configure_models.py")
                return 0
            first = RUNTIME / "first-start"
            if not first.exists():
                run_python("scripts/configure_models.py", "--first-start")
                atomic_write(first, b"1")
            instance_id = uuid.uuid4().hex
            env = dict(os.environ, ZHIZU_INSTANCE_ID=instance_id,
                       WEB_CONCURRENCY="1", UVICORN_WORKERS="1")
            child = subprocess.Popen([str(PYTHON), "-X", "utf8", "scripts/start.py", "--managed"],
                                     cwd=ROOT, env=env)
            print("正在启动本地服务…", flush=True)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError("服务提前退出，请查看上方错误。")
                record = read_record()
                if record and record["id"] == instance_id and instance_online(record):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("等待本地服务超时，请检查上方日志。")
            print("在此窗口按 Ctrl+C 可停止工作台。", flush=True)
            show_page(record, not args.no_browser)
        return child.wait()
    except InUse:
        print("本目录正在准备环境、配置模型或启动，请等待当前窗口完成。")
        return 1
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print("启动未完成：", error, file=sys.stderr)
        return 1
    finally:
        if child and child.poll() is None:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())

