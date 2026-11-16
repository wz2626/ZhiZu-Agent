"""Local files shared by the Windows launcher and configuration tool (stdlib only)."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "launcher"
RECORD = RUNTIME / "instance.json"


class InUse(Exception):
    pass


@contextmanager
def file_lock(path):
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise InUse(path.name) from error
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".env.tmp-" if path.name == ".env" else None)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_record():
    try:
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        if (isinstance(record, dict) and record.get("root") == str(ROOT)
                and type(record.get("port")) is int and 0 < record["port"] < 65536
                and isinstance(record.get("id"), str) and len(record["id"]) == 32):
            return record
    except (OSError, UnicodeError, ValueError):
        pass
    return None

