"""One document per process. Apply the memory limit before loading parser libraries."""
import ctypes
import io
import json
import os
from pathlib import Path
import sys

MEMORY_BYTES = 512 * 1024 * 1024


def limit_memory():
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        return

    from ctypes import wintypes as w
    size = ctypes.c_size_t

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", w.DWORD), ("minimum", size), ("maximum", size),
                    ("processes", w.DWORD), ("affinity", size), ("priority", w.DWORD),
                    ("scheduling", w.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
                    ("process_memory", size), ("job_memory", size),
                    ("peak_process", size), ("peak_job", size)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.process_memory = MEMORY_BYTES
    if not (job and kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            and kernel.AssignProcessToJobObject(job, w.HANDLE(-1))):
        raise OSError("document worker memory limit unavailable")
    # Keep the job handle for this disposable process's entire lifetime.


def main():
    limit_memory()
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from backend.app.core.document_limits import DocumentError, FILE_BYTES
    from backend.app.services.contract_parser import parse_contract

    data = sys.stdin.buffer.read(FILE_BYTES + 1)
    try:
        if len(data) > FILE_BYTES:
            raise DocumentError("FILE_TOO_LARGE", status=413)
        result = parse_contract(io.BytesIO(data), sys.argv[1], len(data), sys.argv[2])
    except DocumentError as error:
        result = {"error": error.code, "status": error.status, "pages": error.pages}
    except MemoryError:
        result = {"error": "DOCUMENT_LIMIT_EXCEEDED", "status": 422, "pages": []}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
