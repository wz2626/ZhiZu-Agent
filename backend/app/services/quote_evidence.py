"""Request-local sources and lexical retrieval. No vector store or network."""

import json
import re
import unicodedata
from fractions import Fraction

from backend.app.core.config import PROJECT_ROOT
from backend.app.schemas.knowledge import LawArticle
from backend.app.schemas.quote_analysis import QuoteSource

LAW_FILE = PROJECT_ROOT / "backend/data/laws/civil_code_lease_703_734.json"
LEXICON_FILE = PROJECT_ROOT / "backend/data/laws/quote_lexicon.json"


def fold(text):
    # Retrieval view only: never mutate the evidence or displayed input.
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isalnum())


def bigrams(value):
    return {value[i:i + 2] for i in range(len(value) - 1)}


def contract_sources(text):
    sources = []
    for paragraph, match in enumerate(re.finditer(r"[^\n]+", text), 1):
        original = match.group()
        if not original.strip():
            continue
        parts, offset = [], 0
        while offset < len(original):
            end = min(offset + 800, len(original))
            if end < len(original):
                boundaries = [m.end() for m in re.finditer(r"[。！？；]", original[offset:end])]
                if boundaries:
                    end = offset + boundaries[-1]
            parts.append(original[offset:end])
            offset = end
        for index, part in enumerate(parts, 1):
            source_id = f"C-{len(sources) + 1:03d}"
            sources.append(QuoteSource(source_id=source_id, kind="contract",
                title=f"合同第{paragraph}段" + (f" · 片段{index}" if len(parts) > 1 else ""),
                original_text=part, paragraph_index=paragraph, part_index=index))
    return sources


def retrieve_laws(query, limit=4):
    raw = json.loads(LAW_FILE.read_text(encoding="utf-8"))
    laws = [LawArticle.model_validate(item) for item in raw]
    expected = [f"LAW-{i}" for i in range(703, 735)]
    if [law.law_id for law in laws] != expected:
        raise ValueError("invalid law registry")
    lexicon = json.loads(LEXICON_FILE.read_text(encoding="utf-8"))
    if not isinstance(lexicon, dict) or any(not isinstance(k, str) or not k or not isinstance(v, list)
            or not v or any(i not in expected for i in v) for k, v in lexicon.items()):
        raise ValueError("invalid lexical registry")
    normalized = fold(query)
    pairs = bigrams(normalized)
    scored = []
    for law in laws:
        hits = sum(fold(key) in normalized for key, ids in lexicon.items() if law.law_id in ids)
        law_pairs = bigrams(fold(law.article_no + law.content))
        # Jaccard overlap in [0,1], so boilerplate bigrams cannot outweigh keywords.
        overlap = Fraction(len(pairs & law_pairs), len(pairs | law_pairs) or 1)
        score = 3 * hits + overlap
        # Bigram overlap ranks keyword-grounded candidates; it never fills an
        # empty slot with an unrelated article containing generic boilerplate.
        if hits > 0:
            scored.append((score, law))
    scored.sort(key=lambda item: (-item[0], item[1].law_id))
    return [QuoteSource(source_id=f"L-{index:03d}", kind="law",
        title=f"《民法典》{law.article_no}", original_text=law.content,
        source_url=str(law.source_url), law_id=law.law_id, verified_date=law.verified_date.isoformat())
        for index, (_, law) in enumerate(scored[:limit], 1)]


def evidence_pack(request):
    sources = contract_sources(request.contract_text)
    # Contract text intentionally excluded from the lexical query.
    sources += retrieve_laws("\n".join([request.landlord_quote, request.user_goal, request.context_note]))
    return {source.source_id: source for source in sources}
