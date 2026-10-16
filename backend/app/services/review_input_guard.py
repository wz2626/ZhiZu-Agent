"""Conservative, local input routing before retrieval or model initialization.

This is a bounded syntax guard, not a semantic contract classifier or an XSS
sanitizer. It only rejects explicit other-domain contracts and obvious inputs
without contract content. Ambiguous prose continues to the grounded reviewer.
The caller must validate and mask the text first; classification never changes
the text used for clause locations or subsequent model calls.
"""

import re

from backend.app.schemas.review import ReviewFailureCode


_CLAUSE_BREAK = re.compile(r"[。！？；;，,\n\r]+")
_SCRIPT_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?(?:</\1\s*>|$)", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.S)
_TAG = re.compile(r"<[^>]*>")
_SQL = re.compile(
    r"\b(?:SELECT\b.{0,200}?\bFROM|INSERT\s+INTO|UPDATE\b.{0,60}?\bSET|"
    r"DELETE\s+FROM|DROP\s+(?:TABLE|DATABASE)|ALTER\s+TABLE|CREATE\s+TABLE)"
    r"[^;\n\r]*;?", re.I,
)
_SQL_LOGIC = re.compile(r"['\"]\s*(?:OR|AND)\s*['\"\d]", re.I)
_SQL_COMMENT = re.compile(r"--[^\n\r]*")
_PAYLOAD = re.compile(
    r"<\s*(?:script|img|iframe)\b|\bon\w+\s*=|\b(?:alert|eval|exec)\s*\(|"
    r"\b(?:window|document|console)\s*\.|\b(?:SELECT|INSERT|DELETE|UPDATE|DROP)\b|"
    r"['\"]\s*(?:OR|AND)\s*['\"\d]", re.I,
)
_MODEL_COMMAND = re.compile(
    r"(?:忽略|覆盖|绕过|忘记).{0,12}(?:规则|指令|提示|审查)|"
    r"(?:直接|只需|仅需|只要|只能).{0,6}(?:输出|返回)|"
    r"(?:不要|无需|停止).{0,8}(?:分析输入|审查输入|遵守规则)|"
    r"(?:宣称|伪造).{0,10}(?:通过|结果)|"
    r"ignore\b.{0,24}(?:instructions|rules|prompt)", re.I,
)
_OTHER_DOMAIN = re.compile(
    r"(?:买卖|购销|劳动|劳务|雇佣|用工|家政(?:服务)?|保洁(?:服务)?|清洁服务)(?:合同|协议)|"
    r"(?:卖方|出卖人).{0,40}(?:出售|转让|卖给).{0,25}(?:买方|买受人)|"
    r"(?:公司|用人单位).{0,20}(?:聘用|雇佣).{0,10}(?:员工|劳动者)|"
    r"(?:家政|保洁|上门清洁).{0,20}(?:服务费|收费|服务协议)"
)
_DOMAIN_NEGATION = re.compile(r"(?:不是|并非|而非|不属于|不涉及|不适用|区别于|无关的)[^。！？；;，,]{0,6}$")
_ROLE = r"(?:出租人|出租方|承租人|承租方|房东|租客|租户)"
_ROLE_DUTY = re.compile(
    _ROLE + r"[^。！？；;，,\n]{0,20}"
    r"(?:应当|应|须|必须|负责|承担|拒绝|不得|有权|无权|允许|同意|可以|不再|无需|"
    r"收取|支付|缴纳|交纳|扣留|扣除|没收|不退|拒退|退还|返还|交付|提供|转租|维修)"
    r"[^。！？；;，,\n]{0,22}"
    r"(?:租金|押金|租期|转租|退租|维修|修缮|修理|租赁|租约)"
)
_RENT_DUTY = re.compile(
    r"(?:支付|缴纳|交纳|收取|缴付|交付|交|付)[^。！？；;，,\n]{0,12}(?:租金|月租|年租)(?!补助|补贴|津贴)|"
    r"(?:租金|月租|年租)(?!补助|补贴|津贴)[^。！？；;，,\n]{0,16}(?:[0-9一二三四五六七八九十百千]+元|支付|缴纳)|"
    r"(?:租金|押金|维修责任|维修费用)[^。！？；;，,\n]{0,15}(?:由|归)" + _ROLE
)
_LEASE_GRANT = re.compile(
    r"(?:出租|租给|承租|租赁)[^。！？；;，,\n]{0,14}(?:房屋|住宅|公寓|房间|租赁物|设备)|"
    r"(?:房屋|住宅|公寓|房间|租赁物)[^。！？；;，,\n]{0,12}(?:出租|租给|交由)[^。！？；;，,\n]{0,12}(?:使用|居住|承租人|租客|乙方)"
)
_LEASE_HEADING = re.compile(
    r"(?:^|[：:\n。；;])\s*(?:附件|附录)?\s*(?:房屋|住宅|住房|公寓|设备)?租赁(?:合同|协议)"
    r"(?:摘录|片段|节选|条款)?\s*[:：]"
)
_LEASE_STATUS = re.compile(
    r"(?:房屋|住宅|住房|公寓|设备)?租赁(?:合同|协议)"
    r"[^。！？；;，,\n]{0,20}(?:无法|不能)继续履行"
)
_LEASE_OBLIGATION = re.compile(r"租期|租金|押金|交付|交接|返还|转租|维修|退租|解除")
_CONTRACT_FRAGMENT = re.compile(
    r"(?:租金|房租|押金|租期|转租|退租)[^。！？；;，,\n]{0,12}"
    r"(?:不退|不予返还|不返还|不得退还|退还|返还|没收|扣除|扣留|支付|缴纳|元|年|月|天)|"
    r"(?:禁止|不得|允许|同意)[^。！？；;，,\n]{0,8}(?:转租|退租)"
)
_GRANT_NEGATION = re.compile(r"(?:没有|并未|不曾|不是|并非|不会|未|不)(?:向|为)?[^。！？；;，,\n]{0,8}$")
_LOCATION_PREFIX = re.compile(r"(?:位于|在|进入|前往|来到)[^。！？；;，,\n]{0,12}$")
_LOCATION_TAIL = re.compile(r"[^。！？；;，,\n]{0,10}(?:内|中|里|清洁|打扫|家政)")
_ENGLISH_LEASE = re.compile(r"\b(?:tenant|landlord)\b.{0,50}\b(?:rent|lease|deposit|repair|sublet)\b", re.I)
_TEST_HEADING = re.compile(r"【[^】]*(?:合成|测试|脱敏|压力)[^】]*】")
_PLACEHOLDER = re.compile(r"\[(?:手机号|身份证号|电话|已脱敏|REDACTED)\]", re.I)
_CONTACT_LABEL = re.compile(r"(?:联系方式|联系(?:人)?|编号|手机(?:号)?|身份证(?:号)?|电话号码|号码)\s*[A-Za-z]?\s*[:=：]?", re.I)
_NOISE = re.compile(r"乱码|锟斤拷|锟+|烫+|随机字符|无意义字符|[�□]+")
_PROSE = re.compile(r"[\u3400-\u9fff]{4,}")


def _has_lease_content(text: str) -> bool:
    """Require an obligation/relation, rather than a home or rent keyword."""
    for clause in _CLAUSE_BREAK.split(text):
        if (_ROLE_DUTY.search(clause) or _RENT_DUTY.search(clause)
                or _ENGLISH_LEASE.search(clause) or _LEASE_STATUS.search(clause)):
            return True
        for match in _LEASE_GRANT.finditer(clause):
            prefix, tail = clause[:match.start()], clause[match.end():]
            if not _GRANT_NEGATION.search(prefix) and not (
                _LOCATION_PREFIX.search(prefix) and _LOCATION_TAIL.search(tail)
            ):
                return True
    if _LEASE_HEADING.search(text) and _LEASE_OBLIGATION.search(text):
        return True
    return False


def classify_review_input(text: str) -> ReviewFailureCode | None:
    """Return a fixed rejection code, or None for rental/uncertain masked prose.

    Length and whitespace errors remain ReviewRequest's HTTP 422 responsibility.
    Removing payloads here is solely for classification; it neither executes nor
    rewrites the request, and does not claim browser/SQL injection protection.
    """
    readable = _COMMENT.sub(" ", _SCRIPT_BLOCK.sub(" ", text))
    readable = _TAG.sub(" ", readable)
    if _SQL.search(readable) or _SQL_LOGIC.search(readable):
        readable = _SQL_COMMENT.sub(" ", readable)
    readable = _SQL.sub(" ", readable)
    readable = "。".join(clause for clause in _CLAUSE_BREAK.split(readable)
                       if not _MODEL_COMMAND.search(clause))
    if _has_lease_content(readable):
        return None
    for clause in _CLAUSE_BREAK.split(readable):
        if any(not _DOMAIN_NEGATION.search(clause[:match.start()])
               for match in _OTHER_DOMAIN.finditer(clause)):
            return ReviewFailureCode.OUT_OF_SCOPE

    # Drop only recognizable synthetic metadata, placeholders and corrupt runs.
    # Unrecognized prose, including incomplete rental questions, is not rejected.
    remaining = _NOISE.sub(" ", _CONTACT_LABEL.sub(" ", _PLACEHOLDER.sub(" ", _TEST_HEADING.sub(" ", readable))))
    if (_PAYLOAD.search(text) or _MODEL_COMMAND.search(text)) and not _CONTRACT_FRAGMENT.search(readable):
        return ReviewFailureCode.INVALID_CONTRACT_TEXT
    if any(len(set(match.group())) > 1 for match in _PROSE.finditer(remaining)):
        return None
    if not re.search(r"[A-Za-z\u3400-\u9fff]", remaining):
        return ReviewFailureCode.INVALID_CONTRACT_TEXT
    if _NOISE.search(text) or _PLACEHOLDER.search(text):
        # Isolated A/B labels left by a contact-only/noise document are not prose.
        if not re.search(r"[A-Za-z]{2,}|[\u3400-\u9fff]{3,}", remaining):
            return ReviewFailureCode.INVALID_CONTRACT_TEXT
    return None
