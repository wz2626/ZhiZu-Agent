"""Conservative browser-aligned masking, including malformed synthetic IDs."""

import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256

PRIVACY_POLICY_VERSION = "v4-grouped-lines-3"
# The browser consumes the same digit table and patterns through the read-only
# metadata endpoint. Each normalized code point keeps its original position.
DIGIT_ZEROS = [point for point in range(0x110000)
               if unicodedata.category(chr(point)) == "Nd" and unicodedata.decimal(chr(point)) == 0]

IGNORED_POINTS = [0xAD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF]
SPACE_POINTS = [0xA0, 0x202F, 0x3000]
_CHAR_MAP = {**{point: " " for point in SPACE_POINTS}, 0xFF38: "X", 0xFF58: "x"}
_H = r"[ \t\u00a0\u202f\u3000]"
SEPARATOR_PATTERN = rf"(?:{_H}{{1,4}}|{_H}{{0,4}}-{_H}{{0,4}}|{_H}{{0,4}}(?:\r\n|\r|\n){_H}{{0,4}})"
_ID = re.compile(rf"(?<!\d)(?:\d{{6}}(?:{SEPARATOR_PATTERN})?\d{{8}}(?:{SEPARATOR_PATTERN})?\d{{3}}[\dXx]|\d{{15}})(?![\dXx])", re.ASCII)
_PHONE = re.compile(rf"(?<!\d)(?:\+?86(?:{SEPARATOR_PATTERN})?)?1\d{{2}}(?:{SEPARATOR_PATTERN})?\d{{4}}(?:{SEPARATOR_PATTERN})?\d{{4}}(?!\d)", re.ASCII)
_LEFT_DIGIT = re.compile(rf"[0-9](?:{SEPARATOR_PATTERN})?$", re.ASCII)
_RIGHT_DIGIT = re.compile(rf"^(?:{SEPARATOR_PATTERN})?[0-9]", re.ASCII)


def _bounded_candidate(text, match):
    return not (_LEFT_DIGIT.search(text[max(0, match.start() - 12):match.start()]) or
                _RIGHT_DIGIT.search(text[match.end():match.end() + 12]))


def privacy_policy() -> dict:
    return {"version": PRIVACY_POLICY_VERSION, "digit_zeros": DIGIT_ZEROS,
            "id_pattern": _ID.pattern, "phone_pattern": _PHONE.pattern,
            "ignored_points": IGNORED_POINTS, "space_points": SPACE_POINTS,
            "engine": "fold-codepoint-v1", "replacement": "***",
            "char_map": {str(point): char for point, char in _CHAR_MAP.items()},
            "separator_pattern": SEPARATOR_PATTERN}


@dataclass(frozen=True)
class SafeText:
    text: str
    policy_version: str
    fingerprint: str


def safe_payload(text: str) -> SafeText:
    safe = redact_pii(text)
    return SafeText(safe, PRIVACY_POLICY_VERSION, sha256(safe.encode("utf-8")).hexdigest())


def redact_report(text: str) -> dict:
    view, index_map = [], []
    for index, char in enumerate(text):
        point = ord(char)
        if point in IGNORED_POINTS:
            continue
        view.append(str(unicodedata.decimal(char)) if char.isdecimal() else _CHAR_MAP.get(point, char))
        index_map.append(index)
    normalized = "".join(view)
    spans = [{"start": index_map[match.start()], "end": index_map[match.end() - 1] + 1, "kind": "id"}
             for match in _ID.finditer(normalized) if _bounded_candidate(normalized, match)]
    for match in _PHONE.finditer(normalized):
        if not _bounded_candidate(normalized, match):
            continue
        start, end = index_map[match.start()], index_map[match.end() - 1] + 1
        if not any(start < item["end"] and end > item["start"] for item in spans):
            spans.append({"start": start, "end": end, "kind": "phone"})
    spans.sort(key=lambda item: item["start"])
    pieces, offset = [], 0
    for item in spans:
        pieces.extend([text[offset:item["start"]], "***"])
        offset = item["end"]
    pieces.append(text[offset:])
    return {"safe_text": "".join(pieces), "spans": spans,
            "counts": {kind: sum(item["kind"] == kind for item in spans) for kind in ("phone", "id")}}


def redact_pii(text: str) -> str:
    return redact_report(text)["safe_text"]
