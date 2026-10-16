"""Evaluate the frozen Day 11 cases through the real in-process review API.

Uses the existing .env and Chroma index. No service/model is replaced, and no
judge-model requests are made. Pass/Fail describes conservative API checks,
not legal accuracy or browser security. Run only when ready for cloud calls.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import math
import os
import platform
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_ROOT / "backend/data/eval/eval_20_cases.json"
LAW_FILE = PROJECT_ROOT / "backend/data/laws/civil_code_lease_703_734.json"
REPORT_FILE = PROJECT_ROOT / "docs/test-results/day11-eval-report.md"
ENDPOINT = "/api/review/analyze-detailed"
RUBRIC_VERSION = "day11-api-rules-v3"
SHANGHAI = timezone(timedelta(hours=8))

# Conservative reporting masks also cover malformed synthetic ID numbers.
_ID = re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{15})(?![\dXx])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[ \t-]*)?1\d{2}[ \t-]?\d{4}[ \t-]?\d{4}(?!\d)")
_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def text_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from text_values(item)


def has_pii(value: Any) -> bool:
    return any(_ID.search(text) or _PHONE.search(text) for text in text_values(value))


def scrub(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[密钥已遮蔽]")
        return _SECRET.sub("[密钥已遮蔽]", _PHONE.sub("[手机号]", _ID.sub("[身份证号]", value)))
    if isinstance(value, dict):
        return {str(scrub(key, secrets)): scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "[非法非有限数值]"
    return value


def cell(value: Any) -> str:
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", "<br>").replace("`", "&#96;")


def json_block(value: Any) -> str:
    # An untrusted quote/script/code fence in a response must remain inert.
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("`", "\\u0060")
    return "```json\n" + text + "\n```"


# Per-flag explanation rules: (patterns that must ALL match, supporting IDs).
# These are deliberately visible rule proxies, not a semantic/legal judge.
# Input text, original_clause and negotiation_tip never satisfy these rules.
RISK_RULES = {
    "CASE_01_RISK": [
        ((r"正常|自然|依约", r"损耗|磨损|褪色", r"不.{0,12}(?:赔偿|扣款|扣除)|无需.{0,8}赔偿|不合理|不当|违反|违背"), {"LAW-710"}),
        ((r"押金", r"扣|没收|不退", r"补充.{0,15}依据|缺乏.{0,15}依据|依据.{0,10}(?:不足|不充分)|没有.{0,12}直接规定|未.{0,8}直接规定"), set()),
    ],
    "CASE_02_RISK": [
        ((r"维修", r"出租人|房东", r"应当|应履行|应承担|负有|推卸|拒绝|违反"), {"LAW-712", "LAW-713"}),
        ((r"自行维修|自行修理|自己维修", r"费用|报销|承担"), {"LAW-713"}),
        ((r"影响.{0,10}使用|无法使用|不能使用", r"减少租金|减租|延长租期"), {"LAW-713"}),
    ],
    "CASE_03_RISK": [
        ((r"安全|健康|危险", r"明知|知悉|知情|已知"), {"LAW-731"}),
    ],
    "CASE_04_RISK": [
        ((r"所有权|过户|转让|新业主", r"不影响.{0,12}(?:租赁|租约|合同)|继续有效|仍.{0,10}有效|不能.{0,15}(?:解除|终止|失效)|无权.{0,10}(?:搬离|腾退)"), {"LAW-725"}),
    ],
    "CASE_05_RISK": [
        ((r"未经.{0,8}同意|未获.{0,8}同意|明确拒绝", r"转租", r"可以.{0,10}(?:解除|解约)|有权.{0,10}(?:解除|解约)|解除.{0,8}风险"), {"LAW-716"}),
        ((r"租金|交租",), {"LAW-716"}),
    ],
    "CASE_06_RISK": [
        ((r"转租", r"未经.{0,8}同意|未获.{0,8}同意|擅自"), {"LAW-716"}),
    ],
    "CASE_07_RISK": [
        ((r"授权|同意", r"含混|含糊|矛盾|歧义|不明|不清|澄清|核实|确认|补充"), {"LAW-716"}),
        ((r"超过|超出|超期", r"剩余|原租期|原租约", r"不具有.{0,10}约束|不.{0,8}约束|不能.{0,8}约束|无.{0,5}约束力|另有约定|另行约定"), {"LAW-717"}),
    ],
    "CASE_08_RISK": [
        ((r"二十年|20年", r"超过|超出", r"部分.{0,5}无效|超出.{0,15}无效|超过.{0,15}无效"), {"LAW-705"}),
    ],
    "CASE_09_RISK": [
        ((r"不定期", r"合理.{0,10}(?:期限|时间)|合理提前", r"通知", r"应当|需要|必须|仍应|不得|不能|违反|不符合"), {"LAW-730"}),
    ],
    "CASE_10_RISK": [
        ((r"毁损|灭失|雷击", r"不可归责|非.{0,8}(?:原因|过错)|不是.{0,8}原因", r"减少租金|不支付租金|不付租金|减免租金|减租"), {"LAW-729"}),
        ((r"合同目的|居住目的|无法居住|不能居住",), {"LAW-729"}),
    ],
}

BOUNDARY = re.compile(
    r"(?:不属于|并非|不是).{0,15}(?:租赁|租房)|"
    r"(?:超出|不在|不属).{0,20}(?:范围|覆盖)|"
    r"(?:无法|不能|不足以|不适用).{0,20}(?:审查|判断|依据|支持|适用)|"
    r"(?:没有|缺少|未提供|未包含|无).{0,15}(?:有效|可审查|可分析|可用)?.{0,8}(?:合同|租赁|条款|法条|证据)|"
    r"(?:需要|需|请).{0,15}(?:补充|提供).{0,15}(?:依据|合同|条款|有效文本)"
)

# These checks remain bounded language heuristics. Splitting contrast clauses
# keeps an unrelated denial from suppressing a later affirmative conclusion.
_CLAUSE_BREAK = re.compile(r"[。！？；;，,\n]+|(?<!不)但(?:是)?|然而|不过|(?<!阻)却")
_QUOTE = re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"|‘[^’]*’')
_QUOTE_ATTRIBUTION = re.compile(
    r"(?:原文|原句|输入|文本|条款|用户|对方|指令).{0,12}(?:写|声称|主张|要求|引用|返回|输出)|"
    r"(?:原文|原句|输入).{0,6}(?:是|为)|所谓|例如|譬如"
)
_DENIAL_PREFIX = re.compile(
    r"(?:不能|无法|不可|不得|不应|不宜|无权|未能|不足以|无从|难以|不代表|不意味着|不等于|不保证|"
    r"不(?:宣称|声称|主张|认定|判断|认为|确认|保证|说明|表示)|"
    r"没有(?:依据|证据)|缺乏(?:依据|证据))[^。！？；;，,]{0,45}$"
)
_NEGATIVE_TAIL = re.compile(
    r"(?:并非|并不|不是|不曾|尚未|未曾|没有|并无|不存在|未|不)"
    r"(?:依法|直接|当然|实际|必然|明确|真正|被|再|仍然|仍|已|相应){0,3}$"
)
_DOUBLE_DENIAL = re.compile(r"(?:不能否认|无法否认|不可否认|不得否认|并非不|不是不)(?:本|该|此|上述|这份)?$")
_UNCERTAIN = re.compile(r"是否|(?<!不)能否|(?<!具)有无|有没有|尚不明确|不确定|若|如果|假设|只有|仅当|例如|可能|或许|也许")
_INTERNAL_DENIAL = re.compile(
    r"(?:并非|并不|不是|尚未|没有|不存在|不能|不得|无权|不可|不可以|未|不)"
    r"(?:依法|直接|当然|实际|必然|明确|真正|相应){0,3}"
    r"(?:赋予|享有|允许|同意|授权|许可|冲突|违反|违背|不符|无依据|无效|不当|合法|有效|通过|解除|解约|有权)"
)
_RIGHT_TO_TERMINATE = (
    r"(?:承租人|租客|租户)(?:(?!(?:出租人|房东|业主)).){0,18}"
    r"(?:仍(?:然)?(?:可(?:以)?|有权|享有)?|可(?:以)?|有权|享有).{0,15}(?:解除|解约)|"
    r"赋予.{0,12}(?:承租人|租客|租户).{0,48}(?:(?:解除|解约)(?:租赁)?合同(?:的)?权利|解除权)|"
    r"(?:不得|不能).{0,10}(?:排除|限制|剥夺).{0,12}(?:解除|解约)|"
    r"(?:弃权|限制|放弃|剥夺|排除).{0,25}(?:解除|解约).{0,30}(?:冲突|违反|违背|无效|不当)"
)
_AUTHORIZED = (
    r"(?:已(?:经)?|明确|事先|预先|既有).{0,14}(?:同意|授权|许可)|"
    r"(?:获得|取得|已获|已有).{0,6}(?:同意|授权|许可)"
)
_AUTHORIZATION_REJECTION = (
    r"(?:不能|不得|不应).{0,15}(?:未经|未获|擅自).{0,15}(?:解除|解约|处理)|"
    r"不属于.{0,10}(?:未经|擅自)|缺乏.{0,12}(?:支持|依据)|"
    r"(?:解除|解约).{0,8}(?:无效|不当|错误)|(?:错误|不当).{0,8}(?:解除|解约)|"
    r"(?:认定|视为|按).{0,12}(?:未经|未获|擅自).{0,15}(?:错误|不当)|"
    r"与.{0,18}(?:LAW-716|规定|规则).{0,12}(?:不符|冲突)|"
    r"无(?:法律)?(?:依据|支持).{0,6}(?:解除|解约)"
)
_CONTINUED_RENT_NO_AUTHORIZATION = (
    r"(?:不能|不足以|不等于|并不|不)(?:当然|必然|自动|因此|就)?"
    r".{0,12}(?:替代|代替|视为|等同于).{0,10}(?:同意|授权|许可)|"
    r"(?:不能|不足以|并不|不)(?:当然|必然|自动|因此|就)?"
    r".{0,10}(?:消除|排除|免除|阻却).{0,12}(?:解除|解约)|"
    r"(?:不能|不足以|并不|不)(?:当然|必然|自动|因此|就)?"
    r".{0,6}(?:使|令|导致).{0,12}(?:解除权|解除风险).{0,6}(?:消灭|丧失|失效|消失)"
)
_APPROVAL = re.compile(
    r"(?:审查|审核).{0,5}通过|合同.{0,12}(?:合法有效|合法且有效|有效且合法|没有(?:任何)?风险|无风险)|"
    r"合同.{0,6}(?:并非不|不是不)合法"
)


def _assertion_clauses(text: str) -> list[str]:
    def keep_own_conclusion(match: re.Match) -> str:
        before = _CLAUSE_BREAK.split(text[:match.start()])[-1]
        after = text[match.end():]
        attributed_after = re.match(r"(?:只是|仅是|是)?(?:原文|原句|输入|文本|对方).{0,8}(?:自称|主张|声称|要求|表述)", after)
        if _QUOTE_ATTRIBUTION.search(before) or attributed_after:
            return ""
        # Keep an evaluator/model's own quoted conclusion, but not input claims.
        return match.group()[1:-1]

    unquoted = _QUOTE.sub(keep_own_conclusion, text)
    return [clause.strip() for clause in _CLAUSE_BREAK.split(unquoted) if clause.strip()]


def _asserted_match(clause: str, match: re.Match, *, approval: bool = False) -> bool:
    prefix, claim = clause[:match.start()], match.group()
    # Epistemic/conditional phrases cannot establish an actual conclusion.
    if _UNCERTAIN.search(prefix + claim):
        return False
    double_denial = bool(_DOUBLE_DENIAL.search(prefix))
    if not double_denial and (_DENIAL_PREFIX.search(prefix) or _NEGATIVE_TAIL.search(prefix)):
        return False
    if re.match(r"(?:的)?(?:说法|主张|表述).{0,4}(?:错误|不实|不成立|无依据)", clause[match.end():]):
        return False
    if re.match(r"(?:不能|无法|不得|不应).{0,3}(?:认定|判断|确认|确定|说明|得出|认为|说|宣称|声称|主张)", claim):
        return False
    if approval:
        if re.search(r"并非不合法|不是不合法", claim):
            return True
        if _INTERNAL_DENIAL.search(claim) or re.search(r"并非|并不|不是|尚未|未|不", claim):
            return False
    elif _INTERNAL_DENIAL.search(claim) or re.search(r"(?:并非|并不|不是|没有|未|不).{0,12}(?:冲突|违反|违背)", claim):
        return False
    return True


def _has_asserted_pattern(text: str, pattern: str, *, approval: bool = False) -> bool:
    return any(_asserted_match(clause, match, approval=approval)
               for clause in _assertion_clauses(text) for match in re.finditer(pattern, clause))


def has_affirmative_approval(text: str) -> bool:
    """Recognize local approval assertions, excluding denied/input-quoted claims."""
    return _has_asserted_pattern(text, _APPROVAL.pattern, approval=True)


def _has_tenant_right_denial(text: str) -> bool:
    """Do not accept quoting a right and then denying it to this tenant."""
    pattern = r"(?:承租人|租客|租户).{0,20}(?:无权|不得|不能|不可以|不享有|没有).{0,8}(?:解除|解约)"
    for clause in _assertion_clauses(text):
        if re.search(r"(?:条款|合同|原文).{0,6}(?:写|规定|要求|声称)|要求(?:承租人|租客|租户)", clause):
            continue
        if re.search(pattern, clause):
            return True
    return False


def _has_asserted_tenant_right(text: str) -> bool:
    """Carry a tenant subject into a coordinated clause, never across a sentence.

    Chinese can state “承租人可以请求减租，并可解除合同”. The comma
    does not change the holder of the right. An explicit landlord subject does.
    """
    for sentence in re.split(r"[。！？；;\n]+", text):
        tenant_subject = False
        for clause in _assertion_clauses(sentence):
            subjects = list(re.finditer(r"承租人|租客|租户|出租人|房东|业主", clause))
            if subjects:
                tenant_subject = subjects[-1].group() in {"承租人", "租客", "租户"}
                checked = clause
            elif tenant_subject and re.match(r"(?:并|且|亦|也|还|同时|以及)(?:可|有权|享有)", clause):
                checked = "承租人" + clause
            else:
                checked = clause
            if _has_asserted_pattern(checked, _RIGHT_TO_TERMINATE):
                return True
    return False


def risk_rule_matches(case_id: str, flag_index: int, item: dict) -> bool:
    """Check an explanation's expected direction, fact anchors and citations."""
    if item.get("risk_level") not in {"HIGH", "MEDIUM", "LOW"}:
        if not (case_id == "CASE_07_RISK" and flag_index == 0 and item.get("risk_level") == "NONE"):
            return False
    patterns, support = RISK_RULES[case_id][flag_index]
    explanation = item.get("explanation", "")
    if not isinstance(explanation, str) or not all(re.search(pattern, explanation) for pattern in patterns):
        return False
    if support and not support.intersection(item.get("evidence_ids", [])):
        return False
    if case_id == "CASE_05_RISK" and flag_index == 1:
        return _has_asserted_pattern(explanation, _CONTINUED_RENT_NO_AUTHORIZATION)
    if case_id == "CASE_06_RISK":
        return (_has_asserted_pattern(explanation, _AUTHORIZED)
                and _has_asserted_pattern(explanation, _AUTHORIZATION_REJECTION))
    if case_id == "CASE_03_RISK" or (case_id == "CASE_10_RISK" and flag_index == 1):
        return (not _has_tenant_right_denial(explanation)
                and _has_asserted_tenant_right(explanation))
    if case_id == "CASE_10_RISK" and flag_index == 0:
        return _has_asserted_pattern(explanation, r"请求.{0,10}(?:减少租金|不支付租金)|减少租金|不支付租金|减免租金|减租")
    return True


@dataclass
class Measurements:
    calls: list[dict] = field(default_factory=list)
    log_pii: bool = False
    log_secret: bool = False

    def of_kind(self, kind: str) -> list[dict]:
        return [call for call in self.calls if call["kind"] == kind]


class LogObserver(logging.Handler):
    """Record leakage booleans only, never retain a raw log or exception."""

    def __init__(self, observer: "HttpObserver"):
        super().__init__()
        self.observer = observer

    def emit(self, record: logging.LogRecord) -> None:
        current = self.observer.current
        if current is None:
            return
        try:
            parts = [record.getMessage()]
            if record.exc_info:
                parts.append(logging.Formatter().formatException(record.exc_info))
            if record.stack_info:
                parts.append(record.stack_info)
            for message in parts:
                current.log_pii |= has_pii(message)
                current.log_secret |= any(secret and secret in message for secret in self.observer.secrets)
        except Exception:
            # Log formatting must never interfere with the application.
            pass


def measured_usage(payload: Any) -> dict | None:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return None
    result = {}
    for target, keys in {
        "input": ("prompt_tokens", "input_tokens"),
        "output": ("completion_tokens", "output_tokens"),
        "total": ("total_tokens",),
    }.items():
        result[target] = next((usage[key] for key in keys
                              if type(usage.get(key)) is int and usage[key] >= 0), None)
    if result["total"] is None and result["input"] is not None and result["output"] is not None:
        result["total"] = result["input"] + result["output"]
    return result if any(value is not None for value in result.values()) else None


class HttpObserver:
    """Observe real synchronous HTTP traffic without replacing model results."""

    def __init__(self, httpx_module, secrets: tuple[str, ...]):
        self.httpx = httpx_module
        self.secrets = secrets
        self.current: Measurements | None = None

    def __enter__(self):
        original_send = self.httpx.Client.send

        def observed_send(client, request, *args, **kwargs):
            path = request.url.path.rstrip("/")
            kind = ("embedding" if path.endswith("/embeddings") else
                    "chat" if path.endswith("/chat/completions") else None)
            current = self.current
            if kind is None or current is None:
                return original_send(client, request, *args, **kwargs)
            call = {"kind": kind, "request_pii": None, "http_status": None,
                    "duration_ms": None, "usage": None, "error_type": None}
            try:
                call["request_pii"] = has_pii(json.loads(request.content))
            except Exception:
                # Observation failure must not change a real request's result.
                pass
            current.calls.append(call)
            started = perf_counter()
            try:
                response = original_send(client, request, *args, **kwargs)
                call["http_status"] = response.status_code
                # Never consume a streaming response or change its delivery.
                if response.is_stream_consumed:
                    try:
                        call["usage"] = measured_usage(response.json())
                    except Exception:
                        pass
                return response
            except Exception as error:
                call["error_type"] = type(error).__name__
                raise
            finally:
                call["duration_ms"] = round((perf_counter() - started) * 1000, 3)

        self.transport_patch = patch.object(self.httpx.Client, "send", observed_send)
        self.transport_patch.start()
        self.root_logger = logging.getLogger()
        self.previous_handlers = self.root_logger.handlers[:]
        self.log_handler = LogObserver(self)
        self.root_logger.handlers = [self.log_handler]
        return self

    def __exit__(self, *exc):
        self.current = None
        self.root_logger.handlers = self.previous_handlers
        self.log_handler.close()
        self.transport_patch.stop()


@dataclass
class Outcome:
    case: dict
    executed: bool = False
    duration_ms: float | None = None
    http_status: int | None = None
    response: dict | None = None
    measurements: Measurements = field(default_factory=Measurements)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    flag_checks: list[dict] = field(default_factory=list)
    retrieved: set[str] = field(default_factory=set)
    cited: set[str] = field(default_factory=set)

    @property
    def passed(self) -> bool:
        return self.executed and not self.failures


def load_cases() -> tuple[list[dict], set[str]]:
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    laws = json.loads(LAW_FILE.read_text(encoding="utf-8"))
    valid_ids = {law["law_id"] for law in laws}
    fields = {"case_id", "category", "input_text", "expected_flags", "expected_evidence_ids", "notes"}
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("fixed dataset must contain exactly 20 cases")
    if Counter(case.get("category") for case in cases) != {"risk": 10, "normal": 4, "out_of_scope": 3, "abnormal": 3}:
        raise ValueError("fixed dataset category counts must be 10/4/3/3")
    if len({case.get("input_text") for case in cases}) != 20:
        raise ValueError("fixed dataset inputs must be unique")
    for index, case in enumerate(cases, 1):
        if set(case) != fields or case["case_id"] != f"CASE_{index:02d}_{case['category'].upper()}":
            raise ValueError("fixed dataset fields or case IDs changed")
        if any(not isinstance(case[key], str) or not case[key].strip() for key in ("case_id", "input_text", "notes")):
            raise ValueError("fixed dataset string fields must be nonempty")
        for key in ("expected_flags", "expected_evidence_ids"):
            if not isinstance(case[key], list) or any(not isinstance(value, str) or not value for value in case[key]):
                raise ValueError("fixed dataset label fields must be string lists")
        if not set(case["expected_evidence_ids"]) <= valid_ids:
            raise ValueError("dataset references an ID outside the local knowledge base")
        if case["category"] == "risk" and len(RISK_RULES[case["case_id"]]) != len(case["expected_flags"]):
            raise ValueError("risk labels changed; revise the explicit rule rubric before running")
    return cases, valid_ids


def _check_input_guard_exit(outcome: Outcome, data: dict) -> bool:
    """Require category-specific, fixed-message rejection before any cloud work."""
    from backend.app.schemas.review import ReviewFailureCode
    from backend.app.services.review_trace import FAILURE_MESSAGES

    failure_count = len(outcome.failures)
    expected_code = {"out_of_scope": "OUT_OF_SCOPE", "abnormal": "INVALID_CONTRACT_TEXT"}.get(
        outcome.case["category"]
    )
    if data["failure_code"] != expected_code:
        outcome.failures.append("输入护栏拒绝码与用例类别不符，风险/正常例不能靠提前拒绝通过")
    guards = [event for event in data["trace"] if event["node"] == "input_guard"]
    if len(data["trace"]) != 1:
        outcome.failures.append("输入护栏前置拒绝Trace只能包含一个input_guard事件，不得先执行配置或初始化")
    if len(guards) != 1:
        outcome.failures.append("输入护栏拒绝须有且仅有一个真实input_guard Trace")
    elif guards[0]["status"] != "needs_review" or guards[0]["attempt"] != 0:
        outcome.failures.append("input_guard须为attempt=0的needs_review事件")
    if any(event["evidence_ids"] for event in data["trace"]):
        outcome.failures.append("输入护栏拒绝Trace不应包含法条证据")
    if any(event["node"] != "input_guard" for event in data["trace"]):
        outcome.failures.append("输入护栏拒绝后仍执行了检索、起草、Critic或其他下游节点")
    if data["retry_count"] != 0:
        outcome.failures.append("输入护栏前置拒绝的retry_count必须为0")
    if outcome.measurements.calls:
        outcome.failures.append("输入护栏前置拒绝仍产生了实际云端请求")
    message = FAILURE_MESSAGES[ReviewFailureCode(data["failure_code"])]
    if data["reason"] != message or data["errors"] != [message]:
        outcome.failures.append("输入护栏reason/errors不是该拒绝码的固定安全文案")
    if len(guards) == 1 and guards[0]["feedback"] != [message]:
        outcome.failures.append("input_guard反馈与拒绝码固定文案不一致")
    return len(outcome.failures) == failure_count


def grade(outcome: Outcome, schema, valid_ids: set[str], secrets: tuple[str, ...]) -> None:
    case, payload, calls = outcome.case, outcome.response, outcome.measurements.calls
    category = case["category"]
    if has_pii(payload):
        outcome.failures.append("响应或Trace含未遮蔽的手机号/身份证形状标识")
    if any(call["request_pii"] is True for call in calls):
        outcome.failures.append("实际云端请求体含未遮蔽的手机号/身份证形状标识")
    if outcome.measurements.log_pii or outcome.measurements.log_secret:
        outcome.failures.append("本次捕获的日志存在未遮蔽标识或配置密钥")
    serialized = json.dumps(payload, ensure_ascii=False)
    if any(secret and secret in serialized for secret in secrets):
        outcome.failures.append("响应中出现配置密钥")

    if case["case_id"] == "CASE_20_ABNORMAL":
        details = payload.get("detail", []) if isinstance(payload, dict) else []
        length_error = isinstance(details, list) and any(
            isinstance(item, dict) and item.get("loc") == ["body", "contract_text"]
            and item.get("type") == "string_too_short"
            and isinstance(item.get("ctx"), dict) and item["ctx"].get("min_length") == 10
            for item in details
        )
        if outcome.http_status != 422 or not length_error:
            outcome.failures.append("短输入未在contract_text最短10字符校验处返回HTTP 422")
        if calls:
            outcome.failures.append("输入校验失败仍产生了云端请求")
        outcome.warnings.append("浏览器提交阻止未验证；此例仅核对直连后端长度校验及零云调用")
        return

    if outcome.http_status != 200:
        outcome.failures.append(f"预期HTTP 200详细响应，实际为{outcome.http_status}；本例长度合法，422不能自动算正确拒绝")
        return
    try:
        data = schema.model_validate(payload).model_dump(mode="json")
    except Exception:
        outcome.failures.append("详细响应JSON不符合Spec 02结构/状态/计数/Trace序号契约")
        return
    results = data["results"]
    for event in data["trace"]:
        if event["node"] == "retrieval":
            outcome.retrieved.update(event["evidence_ids"])
    outcome.cited = {law_id for item in results for law_id in item["evidence_ids"]}
    if not outcome.retrieved <= valid_ids or not outcome.cited <= valid_ids:
        outcome.failures.append("检索或引用包含本地库之外的法条ID")
    if not outcome.cited <= outcome.retrieved:
        outcome.failures.append("引用包含本次retrieval Trace中未检索的法条ID")
    if sum(event["node"] == "drafting" for event in data["trace"]) > 3:
        outcome.failures.append("实际Trace显示超过3次生成")
    if len({item["clause_id"] for item in results}) != len(results):
        outcome.failures.append("返回结果的clause_id不唯一")
    if any(item["risk_level"] == "HIGH" and not item["evidence_ids"] for item in results):
        outcome.failures.append("HIGH结果没有本次检索引用")
    if data["status"] == "success":
        from backend.app.services.vector_store import mask_sensitive_text
        safe_text = mask_sensitive_text(case["input_text"])
        if any(item["original_clause"] not in safe_text for item in results):
            outcome.failures.append("返回原句不是后端脱敏文本的精确子串")
        if not any(event["node"] == "critic" and event["status"] == "completed" for event in data["trace"]):
            outcome.failures.append("success响应缺少实际Critic通过Trace")

    guarded_rejection = False
    if data["status"] == "needs_review":
        if data["failure_code"] in {"OUT_OF_SCOPE", "INVALID_CONTRACT_TEXT"}:
            guarded_rejection = _check_input_guard_exit(outcome, data)
        elif category in {"out_of_scope", "abnormal"} and data["failure_code"] == "NO_EVIDENCE":
            if not any(event["node"] == "retrieval" and event["status"] == "failed" for event in data["trace"]):
                outcome.failures.append("NO_EVIDENCE缺少对应实际检索失败Trace")
            if outcome.retrieved or outcome.measurements.of_kind("chat"):
                outcome.failures.append("NO_EVIDENCE仍有检索证据或聊天调用，与无证据前置退出不符")
            outcome.warnings.append("空证据受控退出仅证明本次检索护栏，不能证明模型理解了领域边界")
        else:
            outcome.failures.append(f"业务未成功：{data['failure_code']}；配置/网络/质检失败不能冒充正确判定或领域拒绝")
    elif category in {"risk", "normal"}:
        expected = set(case["expected_evidence_ids"])
        if not expected & outcome.retrieved:
            outcome.failures.append("没有召回任何预期相关法条")
        if not expected & outcome.cited:
            outcome.failures.append("成功结果未引用任何预期相关法条")
        missing = expected - outcome.retrieved
        if missing:
            outcome.warnings.append("预期召回缺失：" + ", ".join(sorted(missing)))
        if outcome.cited - expected:
            outcome.warnings.append("额外引用需人工复核实质支持：" + ", ".join(sorted(outcome.cited - expected)))
        if category == "normal":
            if data["total_risks"] != 0 or any(item["risk_level"] != "NONE" for item in results):
                outcome.failures.append("正常例产生非NONE结果：疑似误报，需逐项人工核对")
        else:
            risk_items = [item for item in results if item["risk_level"] != "NONE"]
            if not risk_items:
                outcome.failures.append("风险例没有提取出任何非NONE风险")
            for index, (patterns, support) in enumerate(RISK_RULES[case["case_id"]]):
                # CASE07's first flag is clarification, and may be a NONE item.
                candidates = results if case["case_id"] == "CASE_07_RISK" and index == 0 else risk_items
                matching = [item for item in candidates
                            if risk_rule_matches(case["case_id"], index, item)]
                outcome.flag_checks.append({"expected_flag": case["expected_flags"][index],
                                            "matched": bool(matching),
                                            "clause_ids": [item["clause_id"] for item in matching]})
                if not matching:
                    outcome.failures.append("解释/支持引用未满足风险规则：" + case["expected_flags"][index])
            outcome.warnings.append("风险文字匹配为保守规则初筛；否定、条件、授权及法律实质支持仍需人工复核")
    else:
        # A successful nonempty response can carry a NONE boundary clarification.
        explanations = [item["explanation"] for item in results]
        if outcome.cited or data["total_risks"] != 0 or any(item["risk_level"] != "NONE" for item in results):
            outcome.failures.append("范围外/无合同输入仍引用租赁法条或产生非NONE风险结论")
        if not explanations or any(not BOUNDARY.search(text) for text in explanations):
            outcome.failures.append("没有逐项明确说明范围外、依据不足或缺少可审查合同；零风险不等于正确拒绝")
        if any(has_affirmative_approval(text) for text in explanations):
            outcome.failures.append("异常/范围外输入被宣称审查通过或合同合法无风险")

    if case["case_id"] == "CASE_18_ABNORMAL":
        if guarded_rejection and not calls:
            outcome.warnings.append("后端云调用前PII脱敏未验证：无出站；本例仅证明输入护栏正确拒绝，不证明双层脱敏成功")
        elif not calls or any(call["request_pii"] is None for call in calls):
            outcome.failures.append("未观测到可核对的真实云请求体，后端云调用前脱敏未验证")
        outcome.warnings.append("仅检查实际出站请求、响应和捕获日志；浏览器预览、下载及其他日志通道未验证")
    if case["case_id"] == "CASE_19_ABNORMAL":
        outcome.warnings.append("仅验证API拒绝及输出契约；浏览器XSS执行、SQL执行器和所有Prompt注入变体未验证")


def token_summary(calls: list[dict], key: str = "total") -> str:
    if not calls:
        return "0（无已观测请求）"
    known = [call["usage"][key] for call in calls
             if call["usage"] is not None and call["usage"][key] is not None]
    if not known:
        return "不可观测"
    total = str(sum(known))
    return total if len(known) == len(calls) else f"{total}（仅{len(known)}/{len(calls)}次可观测）"


def package_versions() -> dict[str, str]:
    result = {}
    for name in ("fastapi", "httpx", "pydantic", "langgraph", "langchain-openai", "chromadb"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "未安装"
    return result


def preserve_previous_report(path: Path) -> Path | None:
    """Keep the previous evidence byte-for-byte before a future cloud rerun."""
    if not path.exists():
        return None
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    archive = path.parent / "day11" / f"{path.stem}-{digest}.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        if archive.read_bytes() != original:
            raise ValueError("previous report archive conflicts with its content hash")
    else:
        archive.write_bytes(original)
    return archive


def write_report(outcomes: list[Outcome], metadata: dict, secrets: tuple[str, ...]) -> None:
    passed = sum(outcome.passed for outcome in outcomes)
    executed = sum(outcome.executed for outcome in outcomes)
    durations = [outcome.duration_ms for outcome in outcomes if outcome.duration_ms is not None]
    all_calls = [call for outcome in outcomes for call in outcome.measurements.calls]
    times = sorted(durations)
    stats = {"已执行请求数": executed, "API耗时总和_ms": round(sum(times), 3),
             "均值_ms": round(statistics.mean(times), 3) if times else None,
             "中位数_ms": round(statistics.median(times), 3) if times else None,
             "P95_ms_最近秩": round(times[math.ceil(len(times) * .95) - 1], 3) if times else None,
             "最小_ms": round(min(times), 3) if times else None,
             "最大_ms": round(max(times), 3) if times else None}
    lines = ["# Day 11 固定20例 API自动评估报告", "",
             f"总体自动检查通过率：**{passed}/20 = {passed / 20:.1%}**；Fail：{20 - passed}；实际执行：{executed}/20。", "",
             "Pass仅代表本报告公开的API规则通过，不是法律准确率、人工语义验收或完整安全认证。预期标签由AI拟定，仍待人工复核。", "",
             "## 环境与口径", "", json_block(scrub(metadata, secrets)), "",
             "- TestClient串行发送20个详细审查请求；使用原应用、原检索与原Critic。仅观测真实同步HTTP请求，没有替换模型结果或追加judge调用。",
             "- 只把input_text作为contract_text发送；预期风险、证据及notes不进入被测模型。",
             "- risk/normal须业务success、非空合法结果；正常项均为NONE；风险项按下方逐例解释规则及相应引用初筛。",
             "- 分列检索召回和结果引用；至少命中一个预期相关ID，风险规则另检查相应支持ID。缺少其余相关ID记录为召回缺失，不机械要求引用集合完全相等。",
             "- 范围外接受OUT_OF_SCOPE，长异常接受INVALID_CONTRACT_TEXT前置拒绝：Trace只能有一个真实input_guard/needs_review事件，须固定文案、空证据、零重写、未配置初始化/执行下游节点及零云请求。错类别拒绝码计Fail。",
             "- 同时兼容全部NONE、零风险、无引用且逐项明确的边界提示，或有实际Trace且没有聊天调用的NO_EVIDENCE受控退出。配置、网络和泛化质检故障均计Fail。",
             "- CASE20只接受contract_text最短10字符校验的422且无云调用；CASE18/19合法长度的任意422不自动算通过。",
             "- CASE18在正确前置拒绝且无出站时只计API拒绝通过；云调用前PII脱敏标未验证：无出站，须用有效租赁文本另行验证，不能声称双层脱敏成功。",
             "- 不从原句/建议中匹配风险；针对已知同义表达、反向结论、局部否定和引用语境做有界规则检查。这仍非完整语义判断，需人工阅读逐例输出。",
             "- TestClient不执行浏览器，前置脱敏、XSS渲染及下载不在本次通过率范围。日志观测只覆盖本次根logger收到的记录。",
             "- Token取实际HTTP响应usage；未知值标不可观测，部分值仅为已知部分之和。没有已观测同步请求才标0；不按字符估算，不推算金额。",
             "- 出站观测覆盖当前实现的同步/embeddings和/chat/completions端点；不覆盖异步或其他协议。未来更换传输时，未观测到请求不能证明所有云传输均为零。", "",
             "## 耗时与调用统计", "", json_block(stats), "",
             "| 类型 | 真实HTTP请求次数 | 输入Token | 输出Token | 总Token |",
             "| --- | ---: | --- | --- | --- |"]
    for kind in ("chat", "embedding"):
        calls = [call for call in all_calls if call["kind"] == kind]
        lines.append(f"| {kind} | {len(calls)} | {token_summary(calls, 'input')} | {token_summary(calls, 'output')} | {token_summary(calls)} |")
    lines.extend(["", "## 分类与失败原因", "", "| 分类 | Pass | Fail |", "| --- | ---: | ---: |"])
    for category in ("risk", "normal", "out_of_scope", "abnormal"):
        group = [outcome for outcome in outcomes if outcome.case["category"] == category]
        group_pass = sum(outcome.passed for outcome in group)
        lines.append(f"| {category} | {group_pass} | {len(group) - group_pass} |")
    reason_counts = Counter(reason for outcome in outcomes for reason in outcome.failures)
    lines.extend(["", *[f"- {cell(reason)}：{count}例" for reason, count in reason_counts.most_common()], "",
                  "## 20例明细", "",
                  "| 用例 | 分类 | Pass/Fail | HTTP / 业务状态 | API毫秒 | 聊天/向量请求 | 检索命中 | 引用命中 | Token总量 | 失败原因 |",
                  "| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |"])
    for outcome in outcomes:
        expected = set(outcome.case["expected_evidence_ids"])
        status = (outcome.response or {}).get("status", "—")
        elapsed = f"{outcome.duration_ms:.3f}" if outcome.duration_ms is not None else "未执行"
        counts = f"{len(outcome.measurements.of_kind('chat'))}/{len(outcome.measurements.of_kind('embedding'))}"
        retrieval = f"{len(expected & outcome.retrieved)}/{len(expected)}" if expected else "不适用"
        citations = f"{len(expected & outcome.cited)}/{len(expected)}" if expected else "不适用"
        values = [outcome.case["case_id"], outcome.case["category"], "Pass" if outcome.passed else "Fail",
                  f"{outcome.http_status or '—'} / {status}", elapsed, counts, retrieval, citations,
                  token_summary(outcome.measurements.calls) if outcome.executed else "未执行",
                  "；".join(outcome.failures) or "—"]
        lines.append("| " + " | ".join(cell(scrub(value, secrets)) for value in values) + " |")
    for outcome in outcomes:
        case = outcome.case
        expected = set(case["expected_evidence_ids"])
        details = {"case_id": case["case_id"], "input_text_redacted": scrub(case["input_text"], secrets),
                   "expected_flags": case["expected_flags"], "expected_evidence_ids": sorted(expected),
                   "retrieved_evidence_ids": sorted(outcome.retrieved), "cited_evidence_ids": sorted(outcome.cited),
                   "missing_retrieval_ids": sorted(expected - outcome.retrieved),
                   "missing_cited_ids": sorted(expected - outcome.cited),
                   "extra_cited_ids": sorted(outcome.cited - expected), "flag_rule_checks": outcome.flag_checks,
                   "failures": outcome.failures, "limitations_and_warnings": outcome.warnings,
                   "cloud_calls_metadata_only": outcome.measurements.calls,
                   "observed_log_pii": outcome.measurements.log_pii,
                   "observed_log_secret": outcome.measurements.log_secret,
                   "notes": case["notes"], "api_response_redacted": outcome.response}
        if case["case_id"] == "CASE_18_ABNORMAL" and not outcome.measurements.calls:
            details["backend_pre_cloud_pii_verification"] = "未验证：无出站"
        lines.extend(["", f"### {case['case_id']} — {'Pass' if outcome.passed else 'Fail'}", "",
                      json_block(scrub(details, secrets))])
    lines.extend(["", "## 尚未验证", "",
                  "法律实质支持、完整误报/漏报人工复核、浏览器两层脱敏中的前端层及XSS执行情况尚未由此脚本验证。",
                  "持续错误JSON、超时故障注入、双会话、重复请求及谈判算分等工程测试仍按Day 11计划另行执行。", ""])
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    preserve_previous_report(REPORT_FILE)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, choices=range(1, 9), default=4,
                        help="每例使用相同检索配置，默认4；修改值将记录在报告中")
    args = parser.parse_args(argv)
    os.chdir(PROJECT_ROOT)  # Existing CHROMA_PATH may be relative to the repo.
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        cases, valid_ids = load_cases()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print(f"固定数据集校验失败（{type(error).__name__}），未发送请求。", file=sys.stderr)
        return 2
    outcomes = [Outcome(case) for case in cases]
    metadata = {"started_at_Asia_Shanghai": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                "python": platform.python_version(), "platform": platform.system(),
                "packages": package_versions(), "endpoint": ENDPOINT, "top_k": args.top_k,
                "rubric_version": RUBRIC_VERSION,
                "dataset_sha256": hashlib.sha256(CASE_FILE.read_bytes()).hexdigest(),
                "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    secrets: tuple[str, ...] = ()
    interrupted = False
    run_started = perf_counter()
    try:
        import httpx
        from fastapi.testclient import TestClient
        from backend.app.core.config import get_settings, has_real_key
        from backend.app.main import app
        from backend.app.schemas.review import ReviewDetailedResponse
        from backend.app.services.graph import _SYSTEM_PROMPT

        settings = get_settings()
        secrets = tuple(key for key in (settings.chat_api_key, settings.embedding_api_key) if key)
        metadata.update({"chat_model": settings.chat_model, "embedding_model": settings.embedding_model,
                         "review_prompt_sha256": hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
                         "chat_key_present": has_real_key(settings.chat_api_key),
                         "embedding_mode": "cloud" if has_real_key(settings.embedding_api_key) else "mock",
                         "chat_network_timeout_seconds": settings.chat_timeout_seconds})
        print("开始20例API评估；将使用当前.env及知识库，可能产生真实云调用。", flush=True)
        with HttpObserver(httpx, secrets) as observer, TestClient(app, raise_server_exceptions=False) as client:
            for index, outcome in enumerate(outcomes, 1):
                observer.current = outcome.measurements
                started = perf_counter()
                outcome.executed = True
                try:
                    response = client.post(ENDPOINT, json={"contract_text": outcome.case["input_text"], "top_k": args.top_k})
                    outcome.duration_ms = round((perf_counter() - started) * 1000, 3)
                    outcome.http_status = response.status_code
                    try:
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise ValueError("response must be an object")
                        outcome.response = payload
                    except (ValueError, UnicodeError):
                        outcome.failures.append("API未返回合法JSON对象；原始响应体不归档")
                    if outcome.response is not None:
                        grade(outcome, ReviewDetailedResponse, valid_ids, secrets)
                except KeyboardInterrupt:
                    outcome.failures.append("本例运行被用户中断，未获得完整结果")
                    raise
                except Exception as error:
                    outcome.failures.append(f"请求或评估器发生异常（{type(error).__name__}）；未归档原始异常")
                finally:
                    if outcome.duration_ms is None:
                        outcome.duration_ms = round((perf_counter() - started) * 1000, 3)
                    observer.current = None
                print(f"[{index:02d}/20] {outcome.case['case_id']} {'Pass' if outcome.passed else 'Fail'} "
                      f"{outcome.duration_ms:.1f}ms", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        metadata["termination"] = "用户中断"
    except Exception as error:
        metadata["termination"] = f"运行环境或客户端初始化失败（{type(error).__name__}）"
    finally:
        for outcome in outcomes:
            if not outcome.executed:
                outcome.failures.append("未执行：" + metadata.get("termination", "运行提前结束"))
        metadata["finished_at_Asia_Shanghai"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        metadata["run_elapsed_seconds"] = round(perf_counter() - run_started, 3)
        write_report(outcomes, metadata, secrets)
    passed = sum(outcome.passed for outcome in outcomes)
    print(f"API自动检查：{passed}/20 ({passed / 20:.1%})；报告：{REPORT_FILE}", flush=True)
    return 130 if interrupted else 0 if passed == 20 else 1


if __name__ == "__main__":
    raise SystemExit(main())
