"""Conservative deterministic text cleanup; never truncate contractual content."""

import re
import unicodedata
from backend.app.core.document_limits import DocumentError, MAX_TEXT

# Extraction artifacts only; ZWNJ/ZWJ and bidi controls can affect meaningful
# text/emoji rendering and must not be erased as a whole Unicode category.
EXTRACTION_ARTIFACTS = frozenset("\ufeff\u200b\u2060\u00ad")


def clean_text(text):
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(c for c in text if c not in EXTRACTION_ARTIFACTS and (c in "\n\t" or unicodedata.category(c) != "Cc"))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()


def table_text(rows):
    def cell(value):
        return clean_text(value or "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", " / ")
    return "\n".join("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)


def finish_text(text):
    text = clean_text(text)
    if len(text) > MAX_TEXT:
        raise DocumentError("TEXT_TOO_LONG")
    if not text.strip():
        raise DocumentError("NO_EXTRACTABLE_TEXT")
    bad = text.count("\ufffd") + sum(unicodedata.category(c) == "Co" for c in text) + sum(len(m.group()) for m in re.finditer(r"\(cid:\d+\)", text))
    if bad > max(2, len(text) * .02):
        raise DocumentError("UNREADABLE_TEXT")
    return text
