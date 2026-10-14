"""Conservative browser-aligned masking, including malformed synthetic IDs."""

import re

_ID = re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{15})(?![\dXx])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[ \t-]*)?1\d{2}[ \t-]?\d{4}[ \t-]?\d{4}(?!\d)")


def redact_pii(text: str) -> str:
    return _PHONE.sub("***", _ID.sub("***", text))
