"""Fail closed on invalid sources/anchors and known unsafe outgoing content.

These checks establish structure and provenance, not legal correctness.
"""

import json
import re
import unicodedata
from decimal import Decimal

from backend.app.core.privacy import redact_pii
from backend.app.schemas.quote_analysis import QuoteDraft


class UnsafeReplyError(ValueError):
    """Controlled category, containing no upstream reply text."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("nonfinite JSON")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _fold(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value), flags=re.UNICODE)


_THREATS = ("曝光你的", "曝光你家", "搞臭", "让你付出代价", "后果自负", "弄死", "找人收拾", "一定能赢", "保证胜诉", "一定违法")
_UNSAFE_INTENT = re.compile(r"(?:我会|我将|我们会|我就|找人|否则|不然).{0,8}(?:堵门|骚扰|断水|断电|人肉|曝光)")
_FABRICATED = re.compile(r"(?:我|我们|本人)?(?:已经|已)(?:向.{0,12})?(?:立案|起诉|发出?律师函|报警|投诉|委托律师)")
_LEGAL_NUMBER = re.compile(r"第([零〇一二三四五六七八九十百千万\d]+)条")
_INTERNAL = re.compile(r"(?<![A-Za-z0-9])(?:[CL]-\d{3,4}|LAW-\d+)(?![A-Za-z0-9])")
_QUANTITIES = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(元|块|%|％|天|日内|小时|个月|月内|年)")
_TIME_EXPRESSION = re.compile(r"今天|明天|后天|这[一二两三四五六七八九十]+天|[一二两三四五六七八九十\d]+(?:个工作日|小时|天|日|个月)(?:内|前)|周[一二三四五六日天末](?:上午|下午|晚上|白天)?")
_REPORT_ACTOR = r"(?:您|你|房东|对方|他|她)"
_REPORT_TIME = r"(?:刚才|之前|先前|昨天|前天|刚刚|此前)?"


def _article_number(value):
    """Normalize written article identities, never create a new source authority."""
    value = unicodedata.normalize("NFKC", value)
    if value.isascii() and value.isdigit():
        return str(int(value))
    digits = dict(zip("零〇一二三四五六七八九", (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
    if all(char in digits for char in value):
        return str(int("".join(str(digits[char]) for char in value)))
    # Canonical Chinese article notation below 10000; malformed/unsupported
    # spellings stay distinct and therefore fail closed against the whitelist.
    number, pending, previous = 0, None, 10000
    for char in value:
        if char in digits:
            if pending not in (None, 0):
                return value
            pending = digits[char]
        elif char in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            if unit >= previous or pending == 0 or (pending is None and not (unit == 10 and number == 0)):
                return value
            number += (1 if pending is None else pending) * unit
            previous, pending = unit, None
        else:
            return value
    number += pending or 0
    rendered, zero = "", False
    rest = number
    for unit, label in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, rest = divmod(rest, unit)
        if digit:
            if zero:
                rendered += "零"
            rendered += ("" if digit == 1 and unit == 10 and not rendered else "零一二三四五六七八九"[digit]) + label
            zero = False
        elif rendered and rest:
            zero = True
    # Do not guess ambiguous colloquial notation such as 一百一 (101 or 110).
    normalized = value.replace("〇", "零")
    if normalized != rendered and not (rendered.startswith("十") and normalized == "一" + rendered):
        return value
    return str(number)


def _quantity_roles(text):
    """Compare only explicit roles; a deposit total is not a refund/deduction.

    Unlabelled multi-amount passages need semantic review, not set equality.
    """
    roles = {}
    normalized = unicodedata.normalize("NFKC", text)
    for match in _QUANTITIES.finditer(normalized):
        number, unit = match.groups()
        unit = {"块": "元", "日内": "天", "月内": "个月"}.get(unit, unit)
        before, after = normalized[max(0, match.start() - 14):match.start()], normalized[match.end():match.end() + 8]
        role = None
        if unit == '元':
            if re.search(r'押金(?:总额|金额)?(?:为|是|共|合计|有)?\s*$', before) or re.match(r'\s*(?:的)?押金', after):
                role = 'deposit_total'
            elif re.search(r'扣(?:除|款|减|留)?\s*$', before) or re.match(r'\s*(?:的)?扣(?:款|除|减)', after):
                role = 'deduction'
            elif re.search(r'(?:退(?:还|回)?|返还)(?:给|你|我|您)?\s*$', before):
                offered = re.search(r'(?:您|你|对方|房东).{0,8}(?:说|提|表示|愿意|承诺|只|仅)|只退|仅退', before)
                role = 'offered_refund' if offered else 'requested_refund'
        if role is None and unit != '元':
            role = unit
        if role:
            roles.setdefault(role, set()).add(Decimal(number))
    return roles


def _unsupported_action(text, landlord_quote):
    for match in _FABRICATED.finditer(text):
        prefix = text[max(0, match.start() - 10):match.start()]
        attributed = re.search(_REPORT_ACTOR + _REPORT_TIME + r"(?:说|称|提到|表示|声称)(?:自己)?$", prefix)
        own_claim = match.group().startswith(("我", "本人"))
        action = re.search(r"起诉|立案|报警|投诉|律师函|委托律师", match.group())
        # A grounded request to verify the landlord's claim is not a tenant's
        # invented action. No attribution may excuse a first-person assertion.
        if not (attributed and not own_claim and action and action.group() in landlord_quote):
            return True
    return False


def _outgoing_view(text, landlord_quote):
    # Mask proven reports, not the whole sentence: a tenant threat following a
    # legitimate report must still be scanned. Preserve positions between passes.
    attribution = _REPORT_ACTOR + _REPORT_TIME + r"(?:所说的|说过|说的|说|声称|表示|提到的|提到|提出的|提出|所谓的|所谓|以|用|拿)"
    objection = r"(?:我)?(?:不同意|不接受|不认可|反对)(?:您|你|对方)?(?:所说的|说的|提到的|所谓的)?|请(?:不要|勿|停止)(?:再)?(?:用|以)?"
    prefix_pattern = re.compile(attribution + "|" + objection)
    pattern = re.compile(r'''“([^”]{1,200})”|「([^」]{1,200})」|‘([^’]{1,200})’|"([^"\n]{1,200})"|'([^'\n]{1,200})' ''', re.VERBOSE)
    def quoted(match):
        fragment = next(group for group in match.groups() if group is not None)
        prefix = text[max(0, match.start() - 20):match.start()]
        suffix = text[match.end():match.end() + 30]
        attributed = re.search("(?:" + attribution + "|" + objection + r"|不要|不接受|不认可).{0,6}$", prefix)
        named_report = re.search(_REPORT_ACTOR + r"(?:的)?$", prefix) and re.match(r"(?:的)?(?:说法|表述|表达|话|这句话)", suffix)
        rejected_report = re.match(r"(?:的)?(?:这句话|这种说法|这种方式|这种表述|这样的表达)?[，,]?(?:我|我们)?(?:不能接受|不接受|不认可|不同意|反对)", suffix)
        own_intent = re.search(r"(?:我|我们|本人)(?:也|还|就)?(?:会|要|将)", prefix)
        if fragment in landlord_quote and not own_intent and (attributed or named_report or rejected_report):
            return "_" * len(match.group())
        return match.group()
    stripped = pattern.sub(quoted, text)
    spans = []
    for prefix in prefix_pattern.finditer(stripped):
        start = prefix.end()
        while start < len(stripped) and stripped[start] in " \t:：":
            start += 1
        if start == len(stripped) or stripped[start] in ",，。！？；;\n_":
            continue
        # Only attribution can introduce the landlord's quoted first person.
        if not re.fullmatch(attribution, prefix.group()) and stripped[start:].startswith(("我", "本人")):
            continue
        for end in range(min(start + 200, len(stripped)), start + 1, -1):
            fragment = stripped[start:end]
            if fragment not in landlord_quote:
                continue
            folded = _fold(fragment)
            if any(term in folded for term in _THREATS) or _UNSAFE_INTENT.search(folded) or _FABRICATED.search(folded):
                spans.append((start, end))
            break
    # A report may enumerate exact source fragments: "您以堵门和后果自负...".
    # Mask only each proven risky fragment. A comma, contrast or new tenant
    # intent ends that attribution; never exempt an entire reported sentence.
    reported_risks = [match for term in _THREATS for match in re.finditer(re.escape(term), stripped)]
    reported_risks += list(_UNSAFE_INTENT.finditer(stripped))
    for risk in reported_risks:
        if risk.group() not in landlord_quote:
            continue
        prefix = stripped[max(0, risk.start() - 40):risk.start()]
        reporters = list(re.finditer(attribution, prefix))
        if not reporters:
            continue
        gap = prefix[reporters[-1].end():].lstrip(' \t:：,，')
        if re.search(r'[，,。！？；;\n]|但|不过|然而|否则|不然|(?:我|我们|本人)(?:也|还|就)?(?:会|要|将)', gap):
            continue
        spans.append(risk.span())
    # Narrow defensive conditional: third-party conduct followed by a protective
    # response. "如果...我会找人堵门" is deliberately not exempted.
    defensive = re.compile(r"(?:如果|假如|若)(?:对方|您|你|房东)[^，,。！？；;\n]{1,60}[，,](?:我|我们)(?:会|将|可|就)?(?:立即|及时|先|依法)?(?:报警|保留证据|保留记录|记录|求助|寻求调解)")
    for match in defensive.finditer(stripped):
        comma = re.search(r"[，,]", match.group())
        spans.append((match.start(), match.start() + comma.end()))
    # A bounded prohibition does not assert that the landlord already did it.
    # No arbitrary gap: "不要拒绝，否则我会堵门" must retain the tenant threat.
    prohibitions = re.compile(r'(?:请不要|请勿|不要|不得|不应|不可以|不接受|不同意|不认可|拒绝)(?:再|继续|以|用|采用|采取|通过|说|提及|提|给我|对我){0,3}[“‘"「]?(?:找人|让人)?(?:堵门|骚扰|断水断电|断水|断电|人肉|曝光(?:我的|个人)?信息|后果自负)[”’"」]?')
    spans.extend(match.span() for match in prohibitions.finditer(stripped))
    # Denying an outcome is not guaranteeing it. Do not erase double negatives.
    # A bounded predicate grammar, not "any 不 in the preceding window": that
    # would also excuse "不接受协商，我保证胜诉" or double negatives.
    negative = r"(?:不能|无法|不会|不敢|不愿|不应|不宜|不可能|没有|没法|无从|未曾|并非|并不是|不是|不代表|不|没|未)"
    denials = re.compile(negative + r"(?:保证|承诺|认定|断言|认为)?(?:保证一定能赢|保证能赢|保证胜诉|一定能赢|一定违法)")
    for match in denials.finditer(stripped):
        before = _fold(stripped[max(0, match.start() - 10):match.start()])
        if not re.search(r"(?:不是|并非|不能|无法|不得|不会|不要|不敢|不愿|未必|不|没|未|无)(?:说|表示|代表|意味着)?$", before):
            spans.append(match.span())
    chars = list(stripped)
    for start, end in spans:
        chars[start:end] = "_" * (end - start)
    return "".join(chars)


def safe_reply_hints(replies):
    """UI hints are not outgoing messages; degrade unsafe advice, not the card.

    Keep normal descriptions of the landlord's conduct. This separate display
    fallback neither applies the outgoing blocklist nor relaxes text validation.
    """
    own_threat = re.compile(r"(?:我|我们|本人)(?:也|还|就)?(?:会|将|要|打算|准备|决定).{0,10}(?:堵门|骚扰|断水|断电|人肉|曝光|弄死|搞臭|找人收拾|后果自负|付出代价)")
    insult = re.compile(r"傻[逼比]|蠢货|狗东西|去死")
    defaults = {"tactful": "适合先核对情况、温和协商时", "reasoned": "适合核对依据、明确争议时", "firm": "适合明确边界、保留沟通记录时"}
    updates = {}
    for tone, default in defaults.items():
        reply = getattr(replies, tone)
        hint = _fold(reply.best_for)
        if own_threat.search(hint) or insult.search(hint):
            updates[tone] = reply.model_copy(update={"best_for": default})
    return replies.model_copy(update=updates)


def validate_quote(content, request, sources):
    if not isinstance(content, str) or not content.strip() or len(content) > 24000:
        raise ValueError("invalid output size")
    raw = json.loads(content, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    draft = QuoteDraft.model_validate(raw)
    if any(redact_pii(value) != value for value in _strings(raw)):
        raise ValueError("unsafe personal number")
    if draft.status == "out_of_scope":
        return draft
    labels = [t.label for t in draft.breakdown.tactics]
    if len(set(labels)) != len(labels):
        raise ValueError("duplicate tactic")
    for tactic in draft.breakdown.tactics:
        if not tactic.quote_span.strip() or tactic.quote_span not in request.landlord_quote:
            raise ValueError("invalid quote span")
    ids = [g.source_id for g in draft.grounds]
    if len(set(ids)) != len(ids) or any(i not in sources for i in ids):
        raise ValueError("invalid source identity")
    # Only selected law titles authorize legal article numbers, not cross-references
    # embedded inside a provided law's body or a user-authored contract.
    authorized = set()
    contract_numbers = set()
    for i in ids:
        if sources[i].kind == "law":
            authorized.update(_article_number(n) for n in _LEGAL_NUMBER.findall(sources[i].title))
            authorized.add(_article_number(sources[i].law_id.removeprefix("LAW-")))
        else:
            contract_numbers.update(_article_number(n) for n in _LEGAL_NUMBER.findall(sources[i].original_text))
    authored = [draft.breakdown.landlord_position, draft.breakdown.analysis,
                *[t.detail for t in draft.breakdown.tactics],
                *[g.application for g in draft.grounds], *draft.clarification_questions]
    quantities = []
    input_text = "\n".join([request.contract_text, request.landlord_quote, request.user_goal, request.context_note])
    for reply in draft.replies.model_dump().values():
        if len(set(reply["source_ids"])) != len(reply["source_ids"]) or any(i not in ids for i in reply["source_ids"]):
            raise ValueError("invalid reply sources")
        # best_for is UI metadata, never an outgoing threat/action assertion.
        for clause in re.split(r"[。！？；;\n]", _outgoing_view(reply["text"], request.landlord_quote)):
            outgoing = _fold(clause)
            if any(term in outgoing for term in _THREATS) or _UNSAFE_INTENT.search(outgoing) or _unsupported_action(outgoing, request.landlord_quote):
                raise UnsafeReplyError("unsafe outgoing statement")
        if _INTERNAL.search(reply["text"]) or reply["text"].lstrip().startswith(("回复：", "回复:")):
            raise ValueError("internal identifier in message")
        if any(marker in value for value in (reply["text"], reply["best_for"]) for marker in ("```", "**", "<script", "<iframe")):
            raise ValueError("non-plain-text message")
        authored.extend([reply["text"], reply["best_for"]])
        if any(match.group() not in input_text for match in _TIME_EXPRESSION.finditer(reply["text"])):
            raise ValueError("unprovided schedule or deadline")
        availability = re.search(r"(?:我这边|我们|我)([^。！？；\n]{0,24})(?:方便|有空|都可以)", reply["text"])
        if availability and not re.search(r"不确定|尚未|还没|需.*确认|再确认|核实", availability.group(1)):
            for timing in ("工作日", "周末", "上午", "下午", "晚上", "白天"):
                if timing in availability.group(1) and timing not in request.user_goal + request.context_note:
                    raise ValueError("invented tenant availability")
        quantities.append(_quantity_roles(reply["text"]))
    for value in authored:
        for match in _LEGAL_NUMBER.finditer(value):
            is_contract = bool(re.search(r"合同(?:中的|的|约定)?$", value[max(0, match.start() - 8):match.start()]))
            if _article_number(match.group(1)) not in (contract_numbers if is_contract else authorized):
                raise ValueError("unprovided legal article")
    for index, values in enumerate(quantities):
        for other in quantities[index + 1:]:
            for unit in values.keys() & other.keys():
                # Obvious disjoint claims are rejected; subset omission is allowed.
                if not (values[unit] <= other[unit] or other[unit] <= values[unit]):
                    raise ValueError("conflicting reply quantities")
    if any(not value.strip() for value in authored):
        raise ValueError("blank authored text")
    return draft
