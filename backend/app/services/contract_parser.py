"""Offline-only parse facade; deliberately independent of review/model services."""

import json
import os
import subprocess
import sys
from time import monotonic
from pathlib import Path, PurePath
import unicodedata
from pdfminer.pdfdocument import PDFPasswordIncorrect

from backend.app.core.document_limits import Budget, DocumentError, extractor_info
from backend.app.services.contract_text import finish_text
from backend.app.services.docx_parser import parse_docx
from backend.app.services.pdf_parser import parse_pdf


def parse_isolated(stream, format_name, size_bytes, request_id, budget):
    # The parent owns the spool and lease until run() has killed/reaped the child.
    from backend.app.core.document_limits import FILE_BYTES
    payload = stream.read(FILE_BYTES + 1)
    if len(payload) != size_bytes or len(payload) > FILE_BYTES:
        raise DocumentError("INVALID_UPLOAD", status=400)
    environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP")
                   if key in os.environ}
    budget.check()
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).with_name("parse_worker.py")),
             format_name, request_id], input=payload, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=environment, check=True,
            timeout=max(0.001, budget.deadline - monotonic()),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        result = json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        raise DocumentError("PARSE_TIMEOUT", status=504) from None
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise DocumentError("PARSE_FAILED", status=500) from None
    budget.check()
    if "error" in result:
        raise DocumentError(result["error"], status=result["status"], pages=result["pages"])
    return result


def document_format(filename):
    suffix = PurePath(filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise DocumentError("UNSUPPORTED_FILE_TYPE", status=415)
    return suffix[1:]


def parse_contract(stream, format_name, size_bytes, request_id, budget=None):
    info = extractor_info(format_name)
    budget = budget or Budget()
    try:
        budget.check()
        header = stream.read(8)
        stream.seek(0)
        if not header:
            raise DocumentError("EMPTY_FILE")
        if header.startswith(b"\xd0\xcf\x11\xe0"):
            # Encrypted OOXML uses an OLE container; do not claim corrupt ZIP.
            raise DocumentError("ENCRYPTED_DOCUMENT")
        if (format_name == "pdf" and not header.startswith(b"%PDF-")) or (format_name == "docx" and not header.startswith(b"PK\x03\x04")):
            raise DocumentError("FILE_TYPE_MISMATCH", status=415)
        text, pages, tables, warnings = (parse_pdf if format_name == "pdf" else parse_docx)(stream, budget)
        text = finish_text(text)
        budget.check()
        if "\ufffd" in text or any(unicodedata.category(c) == "Co" for c in text):
            warnings.append({"code": "TEXT_REVIEW_RECOMMENDED", "message": "少量字符无法可靠识别，请对照原文件核对文字与金额。", "pages": []})
        if tables:
            warnings.append({"code": "TABLE_REVIEW_RECOMMENDED", "message": "已提取表格文字，请核对金额、日期及对应关系。", "pages": []})
        return {"status": "success", "text": text, "char_count": len(text),
                "document": {"format": format_name, "size_bytes": size_bytes, "page_count": pages, "table_count": tables},
                "warnings": warnings, "request_id": request_id, "extractor": info}
    except DocumentError:
        raise
    except MemoryError:
        raise DocumentError("DOCUMENT_LIMIT_EXCEEDED") from None
    except PDFPasswordIncorrect:
        raise DocumentError("ENCRYPTED_DOCUMENT") from None
    except Exception:
        raise DocumentError("CORRUPTED_DOCUMENT") from None
