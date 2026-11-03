"""Offline-only parse facade; deliberately independent of review/model services."""

from pathlib import PurePath
import unicodedata
from pdfminer.pdfdocument import PDFPasswordIncorrect

from backend.app.core.document_limits import Budget, DocumentError, extractor_info
from backend.app.services.contract_text import finish_text
from backend.app.services.docx_parser import parse_docx
from backend.app.services.pdf_parser import parse_pdf


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
    except PDFPasswordIncorrect:
        raise DocumentError("ENCRYPTED_DOCUMENT") from None
    except Exception:
        raise DocumentError("CORRUPTED_DOCUMENT") from None
