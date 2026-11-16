"""Start the local server, even when invoked outside the repository directory."""

import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    import argparse
    from launcher_files import RUNTIME, InUse, file_lock

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--managed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.managed:
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)
        return
    if not os.environ.get("ZHIZU_INSTANCE_ID"):
        parser.error("请使用启动脚本；手动启动请省略 --managed。")
    try:
        with file_lock(RUNTIME / "service.lock"):
            serve_managed(args.port)
    except InUse:
        raise SystemExit("此目录的服务仍在运行，请查看原启动窗口。")


def serve_managed(preferred_port):
    import json
    import socket
    from launcher_files import RECORD, ROOT, atomic_write, read_record

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", preferred_port))
        except OSError as error:
            if error.winerror not in (10013, 10048):
                raise
            listener.bind(("127.0.0.1", 0))
        record = {"root": str(ROOT), "port": listener.getsockname()[1],
                  "id": os.environ["ZHIZU_INSTANCE_ID"]}
        atomic_write(RECORD, json.dumps(record).encode())
        try:
            uvicorn.Server(uvicorn.Config("backend.app.main:app")).run(sockets=[listener])
        finally:
            if read_record() == record:
                RECORD.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
