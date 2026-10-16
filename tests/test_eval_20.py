"""Offline regression checks for the evaluator's direction-sensitive rules.

Excerpts are static fixtures from the first run, not reads of the mutable report.
Importing the evaluator does not call main, run the fixed suite or contact a model.
"""

from copy import deepcopy

import pytest

from backend.app.schemas.review import ReviewDetailedResponse
from scripts.run_eval_20 import (
    Outcome,
    grade,
    has_affirmative_approval,
    risk_rule_matches,
)


_SOURCE = "合成住宅租赁条款，用于离线评分规则验证。"
_VALID_IDS = {f"LAW-{number}" for number in range(703, 735)}
_FLAGS = {
    "CASE_03_RISK": [
        "以签约时已知危险为由排除承租人因安全或健康危险解除合同的权利",
    ],
    "CASE_05_RISK": [
        "明确未获同意仍实际转租，存在出租人解除合同的风险",
        "继续支付租金不能替代转租同意",
    ],
    "CASE_06_RISK": [
        "将符合既有明确授权的转租认定为未经同意，并据此主张解除",
    ],
    "CASE_10_RISK": [
        "不可归责于承租人的全部毁损后仍排除减免租金请求",
        "房屋毁损已不能实现合同目的仍排除承租人解除权",
    ],
}
_SUPPORT = {
    "CASE_03_RISK": "LAW-731",
    "CASE_05_RISK": "LAW-716",
    "CASE_06_RISK": "LAW-716",
    "CASE_10_RISK": "LAW-729",
}

# Preserve the explanations that v1 missed, independently of future reruns.
_FIRST_RUN_EXPLANATIONS = {
    "CASE_03_RISK": (
        "该条款先确认房屋承重结构随时可能坍塌并危及居住者安全，又要求承租人放弃以安全或健康受威胁为由提前解约、必须住满租期。"
        "民法典第731条赋予承租人在租赁物危及安全或健康时随时解除合同的权利，并明确即使订立合同时明知质量不合格也不受影响。"
        "因此该弃权或限制解除承诺与法定权利直接冲突，存在被认定无效及人身安全风险。"
    ),
    "CASE_06_RISK": (
        "出租人已通过补充协议明确同意该次转租，承租人亦按授权履行。"
        "根据LAW-716，经出租人同意转租的，租赁合同继续有效；只有未经出租人同意转租，出租人才可解除合同。"
        "出租人事后单方将已获许可的转租一律按未经同意处理并据此解除，缺乏该条支持，存在被认定解除无效或构成违约的高风险。"
    ),
    "CASE_10_RISK": (
        "该约定要求承租人在不可归责于承租人的雷击致房屋主体全部毁损、无法居住且不能实现居住目的时，仍支付之后全部租金，并排除其请求不付租金或解除合同的权利。"
        "LAW-729直接赋予承租人在此类情形下请求减少租金或不支付租金以及解除合同的权利，故该约定与法定权利直接冲突，存在被认定无效或对承租人显失公平的高风险。"
    ),
}


def _item(explanation, evidence_id, *, risk_level="HIGH", clause_id="C-01"):
    return {
        "clause_id": clause_id,
        "original_clause": _SOURCE,
        "risk_level": risk_level,
        "explanation": explanation,
        "evidence_ids": [evidence_id] if evidence_id else [],
        "negotiation_tip": "核对事实及对应依据后协商修订。",
    }


def _outcome(case_id, items):
    category = "risk" if case_id in _FLAGS else "out_of_scope"
    expected_ids = [_SUPPORT[case_id]] if category == "risk" else []
    retrieved = sorted({law_id for item in items for law_id in item["evidence_ids"]})
    trace = [
        {"sequence": 1, "node": "configuration", "attempt": 0, "status": "completed", "duration_ms": 1.0, "evidence_ids": [], "feedback": []},
        {"sequence": 2, "node": "retrieval", "attempt": 0, "status": "completed", "duration_ms": 1.0, "evidence_ids": retrieved, "feedback": []},
        {"sequence": 3, "node": "drafting", "attempt": 1, "status": "completed", "duration_ms": 1.0, "evidence_ids": retrieved, "feedback": []},
        {"sequence": 4, "node": "critic", "attempt": 1, "status": "completed", "duration_ms": 1.0, "evidence_ids": retrieved, "feedback": []},
    ]
    return Outcome(
        case={
            "case_id": case_id,
            "category": category,
            "input_text": _SOURCE,
            "expected_flags": _FLAGS.get(case_id, ["范围外且需补充适用依据"]),
            "expected_evidence_ids": expected_ids,
            "notes": "静态离线评分夹具，不代表重新执行真实API。",
        },
        executed=True,
        http_status=200,
        duration_ms=1.0,
        response={
            "status": "success",
            "results": deepcopy(items),
            "total_risks": sum(item["risk_level"] != "NONE" for item in items),
            "failure_code": None,
            "reason": None,
            "errors": [],
            "retry_count": 0,
            "trace_label": "本次执行回放",
            "trace": trace,
        },
    )


@pytest.mark.parametrize("case_id", tuple(_FIRST_RUN_EXPLANATIONS))
def test_first_run_correct_explanations_satisfy_each_flag_and_grade(case_id):
    item = _item(_FIRST_RUN_EXPLANATIONS[case_id], _SUPPORT[case_id])
    for index in range(len(_FLAGS[case_id])):
        assert risk_rule_matches(case_id, index, item)
    outcome = _outcome(case_id, [item])
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert outcome.passed, outcome.failures
    assert all(check["matched"] for check in outcome.flag_checks)


@pytest.mark.parametrize(
    "case_id,index,explanation",
    [
        (
            "CASE_03_RISK", 0,
            "租赁物危及安全或健康时，即使订约时明知质量不合格，承租人仍可以随时解除合同；限制该项解除权与法定权利直接冲突。",
        ),
        (
            "CASE_06_RISK", 0,
            "出租人已经明确同意转租，承租人依该授权履行。房东事后将已获许可的转租按未经同意处理并据此解除，缺乏该条支持，存在解除无效风险。",
        ),
        (
            "CASE_10_RISK", 0,
            "房屋全部毁损不可归责于承租人，承租人可以请求减少租金或不支付租金；仍强收租金的条款与法定权利直接冲突。",
        ),
        (
            "CASE_10_RISK", 1,
            "因不可归责于承租人的毁损已不能实现合同目的，法律赋予承租人解除合同的权利，排除其权利的约定与法定权利直接冲突。",
        ),
    ],
)
def test_meaningful_equivalent_expressions_match(case_id, index, explanation):
    assert risk_rule_matches(case_id, index, _item(explanation, _SUPPORT[case_id]))


@pytest.mark.parametrize(
    "case_id,index,explanation",
    [
        (
            "CASE_03_RISK", 0,
            "租赁物虽然危及安全，但承租人签约时已经明知，所以不能解除合同，限制解除权的承诺有效。",
        ),
        (
            "CASE_03_RISK", 0,
            "法律未赋予签约时明知安全危险的承租人解除合同的权利；排除解除权的约定不与法定权利冲突。",
        ),
        (
            "CASE_03_RISK", 0,
            "承租人明知安全危险，其解除权未受排除，该约定不与法定权利冲突。",
        ),
        (
            "CASE_03_RISK", 0,
            "房屋安全危险已被承租人明知。出租人有权解除合同，承租人没有解除权。",
        ),
        (
            "CASE_06_RISK", 0,
            "出租人已经明确同意转租，但已获许可亦可按未经同意转租解除，符合该条支持。",
        ),
        (
            "CASE_06_RISK", 0,
            "出租人没有明确同意转租，已授权的说法错误；出租人可以因未经同意转租解除合同。",
        ),
        (
            "CASE_06_RISK", 0,
            "本次转租未获授权；只有取得明确同意才能转租。当前不能认定房东依据未经同意转租解除是错误的。",
        ),
        (
            "CASE_06_RISK", 0,
            "出租人已明确同意转租，但不能认定将已获许可转租按未经同意处理并解除的做法不当。",
        ),
        (
            "CASE_06_RISK", 0,
            "出租人已明确同意转租。承租人否认存在未经同意转租。出租人可以据此解除合同。",
        ),
        (
            "CASE_10_RISK", 0,
            "房屋毁损虽不可归责于承租人，但承租人无权请求减少租金或不支付租金，继续全额收租合法。",
        ),
        (
            "CASE_10_RISK", 1,
            "房屋毁损不能实现合同目的，但法律未赋予承租人解除合同的权利，排除解除权的约定有效。",
        ),
        (
            "CASE_10_RISK", 1,
            "房屋毁损不可归责于承租人，已不能实现合同目的。出租人有权解除合同，承租人没有解除权。",
        ),
        (
            "CASE_10_RISK", 1,
            "毁损不能实现合同目的。房东有权解除合同，租客无权解除。",
        ),
    ],
)
def test_opposite_conclusions_do_not_match(case_id, index, explanation):
    assert not risk_rule_matches(case_id, index, _item(explanation, _SUPPORT[case_id]))


def test_authorization_risk_requires_affirmative_existing_authorization():
    item = _item(
        "转租是否取得授权或同意尚不明确，应核实事实；若确已获授权，房东按未经同意处理会是不当的解除。",
        "LAW-716",
    )
    assert not risk_rule_matches("CASE_06_RISK", 0, item)


@pytest.mark.parametrize("case_id", tuple(_FIRST_RUN_EXPLANATIONS))
@pytest.mark.parametrize("missing_support", [None, "LAW-704"])
def test_expected_risk_without_corresponding_citation_cannot_match(case_id, missing_support):
    item = _item(_FIRST_RUN_EXPLANATIONS[case_id], missing_support)
    for index in range(len(_FLAGS[case_id])):
        assert not risk_rule_matches(case_id, index, item)


@pytest.mark.parametrize("case_id", tuple(_FIRST_RUN_EXPLANATIONS))
def test_none_findings_cannot_satisfy_expected_substantive_risks(case_id):
    item = _item(_FIRST_RUN_EXPLANATIONS[case_id], _SUPPORT[case_id], risk_level="NONE")
    for index in range(len(_FLAGS[case_id])):
        assert not risk_rule_matches(case_id, index, item)


def test_case07_authorization_clarification_can_remain_none():
    item = _item("转租授权是否已获同意含混，应核实并澄清授权范围。", "LAW-716", risk_level="NONE")
    assert risk_rule_matches("CASE_07_RISK", 0, item)


def test_only_explanation_can_satisfy_the_risk_rule():
    item = _item("需要进一步复核。", "LAW-731")
    item["original_clause"] = _FIRST_RUN_EXPLANATIONS["CASE_03_RISK"]
    item["negotiation_tip"] = _FIRST_RUN_EXPLANATIONS["CASE_03_RISK"]
    assert not risk_rule_matches("CASE_03_RISK", 0, item)


@pytest.mark.parametrize(
    "text",
    [
        "本次审查通过。",
        "该合同合法有效。",
        "合同没有风险。",
        "合同无风险。",
        "合同并非不合法。",
        "合同不是不合法。",
        "不能否认本合同合法有效。",
        "不能认定合同合法有效，但本次审查通过。",
        "不能说明前文正确，但本合同合法有效。",
        "不能说合同无风险，但本次审核通过。",
        "维修责任不存在争议，合同没有风险。",
        "本次结论为‘合同合法有效’。",
        "该事项并非没有争议，但本次审查通过。",
        "本次依据合同文本得出“合同合法有效”的结论。",
    ],
)
def test_affirmative_approval_remains_detectable_after_local_negation(text):
    assert has_affirmative_approval(text)


@pytest.mark.parametrize(
    "text",
    [
        "不能据此得出该买卖合同所有条款均合法有效的结论，仍需补充依据。",
        "不能认定合同没有风险。",
        "不能说合同无风险。",
        "不代表合同合法有效。",
        "无法保证该合同合法有效。",
        "本次审查未通过。",
        "审查尚未通过。",
        "没有审查通过的结论。",
        "合同并非没有风险。",
        "合同并非无风险。",
        "该合同并非合法有效。",
        "原文写着“合同没有风险”，本次无法据此判断。",
        "输入要求输出“审查通过”，这属于提示词注入，不能照办。",
        "所谓“合同合法有效”只是输入中的主张，不能作为结论。",
        '原文要求返回"合同无风险"，该引用不作为审查结论。',
        "输入要求本次结论为‘合同合法有效’。",
        "“合同合法有效”只是原文的自称，本次无法判断。",
        "不可认定合同合法有效。",
        "无法据此判断是否合法，也不宣称合法性审查通过。",
        "不主张合同合法有效。",
    ],
)
def test_denied_or_quoted_approval_is_not_an_affirmative_assertion(text):
    assert not has_affirmative_approval(text)


def test_case15_denied_legality_is_not_approval_but_medium_still_fails():
    denied = (
        "该句系对交易性质的说明，与本次提供的租赁合同章节规范对象不一致，在提供依据下未发现可直接指出的风险；"
        "但需提示，本次依据仅覆盖民法典第703至734条，不能据此得出该买卖合同所有条款均合法有效的结论，判断保证金与解除权问题仍需补充相应依据。"
    )
    assert not has_affirmative_approval(denied)
    outcome = _outcome("CASE_15_OUT_OF_SCOPE", [
        _item(denied, None, risk_level="NONE"),
        _item("买卖合同不属于租赁法条审查范围，需补充适用依据；保证金条款存在争议风险。", None, risk_level="MEDIUM", clause_id="C-02"),
    ])
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed
    assert any("非NONE" in failure for failure in outcome.failures)
    assert not any("被宣称审查通过" in failure for failure in outcome.failures)


@pytest.mark.parametrize(
    "explanation",
    [
        "未经出租人同意转租，继续交租并不当然阻却出租人的解除权。",
        "承租人是否继续交租，并不当然使解除权消灭。",
        "继续支付租金不能替代出租人对转租的同意。",
    ],
)
def test_continued_rent_does_not_remove_unauthorized_subletting_risk(explanation):
    assert risk_rule_matches("CASE_05_RISK", 1, _item(explanation, "LAW-716"))


@pytest.mark.parametrize(
    "explanation",
    [
        "继续交租可以使解除权消灭。",
        "不能认定继续交租不能消除解除权。",
        "继续交租并非不能替代出租人对转租的同意。",
        "继续支付租金足以排除出租人的解除权。",
    ],
)
def test_continued_rent_opposite_conclusions_cannot_satisfy_flag(explanation):
    assert not risk_rule_matches("CASE_05_RISK", 1, _item(explanation, "LAW-716"))


@pytest.mark.parametrize(
    "explanation",
    [
        "补充协议已明确同意转租。出租人将已获同意的转租重新定性为未经同意并据此解除，与LAW-716的直接规定不符。",
        "出租人已明确授权本次转租，却事后按未经同意转租解除，承租人面临无依据解除的风险。",
    ],
)
def test_authorization_rejection_can_be_expressed_as_statutory_mismatch(explanation):
    assert risk_rule_matches("CASE_06_RISK", 0, _item(explanation, "LAW-716"))


@pytest.mark.parametrize(
    "explanation",
    [
        "出租人已明确同意转租。将本次转租认定为未经同意并据此解除，与LAW-716的规定并非不符。",
        "出租人已明确同意转租。不能说按未经同意转租解除属于无依据解除。",
    ],
)
def test_denied_statutory_mismatch_is_not_a_supported_authorization_finding(explanation):
    assert not risk_rule_matches("CASE_06_RISK", 0, _item(explanation, "LAW-716"))


@pytest.mark.parametrize(
    "explanation",
    [
        "房屋全部毁损不能实现居住目的。LAW-729规定承租人可以请求减少租金或者不支付租金，并可解除合同。",
        "LAW-729赋予承租人在不可归责事由致房屋全部毁损、不能实现合同目的时的减租请求权和解除权。",
    ],
)
def test_tenant_termination_right_can_use_coordination_or_named_right(explanation):
    assert risk_rule_matches("CASE_10_RISK", 1, _item(explanation, "LAW-729"))


@pytest.mark.parametrize(
    "explanation",
    [
        "房屋全部毁损不能实现合同目的。承租人可请求减少租金，出租人有权解除合同。",
        "房屋全部毁损不能实现合同目的。房东可以请求减少租金，并可解除合同。",
        "房屋全部毁损不能实现合同目的。LAW-729未赋予承租人减租请求权和解除权。",
    ],
)
def test_coordination_does_not_change_landlord_into_tenant_or_remove_denial(explanation):
    assert not risk_rule_matches("CASE_10_RISK", 1, _item(explanation, "LAW-729"))


def test_case17_denied_approval_still_grades_as_successful_scope_refusal():
    explanation = (
        "该文本为家政服务协议。本次提供的法律依据仅为租赁合同相关条文，"
        "无法据此审查家政服务收费与责任条款；不能据现有依据判断其合法或违法，也不宣称合法性审查通过。"
    )
    outcome = _outcome("CASE_17_OUT_OF_SCOPE", [_item(explanation, None, risk_level="NONE")])
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert outcome.passed, outcome.failures


def _guard_outcome(case_id="CASE_15_OUT_OF_SCOPE", *, category="out_of_scope", code="OUT_OF_SCOPE"):
    from backend.app.schemas.review import ReviewFailureCode
    from backend.app.services.review_trace import FAILURE_MESSAGES

    outcome = _outcome(case_id, [])
    outcome.case["category"] = category
    message = FAILURE_MESSAGES[ReviewFailureCode(code)]
    outcome.response.update({
        "status": "needs_review",
        "failure_code": code,
        "reason": message,
        "errors": [message],
        "trace": [{
            "sequence": 1, "node": "input_guard", "attempt": 0,
            "status": "needs_review", "duration_ms": 1.0,
            "evidence_ids": [], "feedback": [message],
        }],
    })
    return outcome


@pytest.mark.parametrize(
    "case_id,category,code",
    [
        ("CASE_15_OUT_OF_SCOPE", "out_of_scope", "OUT_OF_SCOPE"),
        ("CASE_18_ABNORMAL", "abnormal", "INVALID_CONTRACT_TEXT"),
        ("CASE_19_ABNORMAL", "abnormal", "INVALID_CONTRACT_TEXT"),
    ],
)
def test_fixed_message_guard_rejection_passes_only_the_correct_category(case_id, category, code):
    outcome = _guard_outcome(case_id, category=category, code=code)
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert outcome.passed, outcome.failures
    assert outcome.measurements.calls == []
    if case_id == "CASE_18_ABNORMAL":
        assert any("未验证：无出站" in warning for warning in outcome.warnings)


@pytest.mark.parametrize(
    "case_id,category,code",
    [
        ("CASE_15_OUT_OF_SCOPE", "out_of_scope", "INVALID_CONTRACT_TEXT"),
        ("CASE_19_ABNORMAL", "abnormal", "OUT_OF_SCOPE"),
        ("CASE_03_RISK", "risk", "OUT_OF_SCOPE"),
        ("CASE_11_NORMAL", "normal", "INVALID_CONTRACT_TEXT"),
        ("CASE_20_ABNORMAL", "abnormal", "INVALID_CONTRACT_TEXT"),
    ],
)
def test_wrong_category_or_short_input_cannot_pass_via_guard_exit(case_id, category, code):
    outcome = _guard_outcome(case_id, category=category, code=code)
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed


@pytest.mark.parametrize("field,value", [("status", "completed"), ("attempt", 1), ("evidence_ids", ["LAW-716"]), ("feedback", ["非固定反馈"])])
def test_guard_trace_fields_are_checked_independently(field, value):
    outcome = _guard_outcome()
    outcome.response["trace"][0][field] = value
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed


@pytest.mark.parametrize("node", ["configuration", "retrieval", "drafting", "critic", "mock", "graph"])
def test_guard_rejection_cannot_have_downstream_work(node):
    outcome = _guard_outcome()
    outcome.response["trace"].append({
        "sequence": 2, "node": node, "attempt": 0, "status": "completed",
        "duration_ms": 1.0, "evidence_ids": [], "feedback": [],
    })
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed


def test_guard_rejection_must_precede_configuration_and_initialization():
    outcome = _guard_outcome()
    outcome.response["trace"][0]["sequence"] = 2
    outcome.response["trace"].insert(0, {
        "sequence": 1, "node": "configuration", "attempt": 0,
        "status": "completed", "duration_ms": 1.0, "evidence_ids": [], "feedback": [],
    })
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed
    assert any("配置或初始化" in failure for failure in outcome.failures)


@pytest.mark.parametrize("trace_count", [0, 2])
def test_guard_exit_requires_exactly_one_guard_event(trace_count):
    outcome = _guard_outcome()
    original = outcome.response["trace"][0]
    outcome.response["trace"] = [dict(deepcopy(original), sequence=index + 1) for index in range(trace_count)]
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed


@pytest.mark.parametrize("field,value", [("reason", "未知拒绝原因"), ("errors", ["未知拒绝原因"]), ("retry_count", 1)])
def test_guard_rejection_requires_fixed_response_messages_and_zero_retry(field, value):
    outcome = _guard_outcome()
    outcome.response[field] = value
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed


@pytest.mark.parametrize("kind", ["embedding", "chat"])
def test_guard_rejection_fails_if_a_cloud_call_was_observed(kind):
    outcome = _guard_outcome()
    outcome.measurements.calls.append({"kind": kind, "request_pii": False})
    grade(outcome, ReviewDetailedResponse, _VALID_IDS, ())
    assert not outcome.passed
    assert any("云端请求" in failure for failure in outcome.failures)

