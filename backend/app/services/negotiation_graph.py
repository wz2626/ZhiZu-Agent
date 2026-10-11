"""Offline extraction -> trial rules -> critic -> atomic commit or retry.

This checks explicit simulated agreements and reference identity, not full
legal semantic support. User demands never become landlord agreements.
"""

from collections.abc import Callable
from copy import deepcopy
import re
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas.negotiation import (
    MAX_RETRIES, MAX_ROUNDS, NegotiationMessage, NegotiationState,
)
from backend.app.schemas.knowledge import LawId
from backend.app.services.scoring import calculate_score, explain_score

_TERMS_ADAPTER = TypeAdapter(NegotiationState.model_fields["candidate_terms"].annotation)
_EVIDENCE_ADAPTER = TypeAdapter(list[LawId])

# Conservative offline semantic adapter. A future model adapter can propose
# terms, but the critic must still establish that the landlord accepted them.
_DEPOSIT_ACCEPTANCE = re.compile(
    r"【模拟房东】我确认返还押金(?P<amount>-?\d+(?:\.\d+)?)元[。]?"
    r"(?:依据LAW-\d{3}(?:[、,，]LAW-\d{3})*。?)?"
)


def _extract_landlord_terms(response: str) -> dict[str, int | float]:
    match = _DEPOSIT_ACCEPTANCE.fullmatch(response.strip())
    if match is None:
        return {}
    amount = match.group("amount")
    return {"deposit_refund": float(amount) if "." in amount else int(amount)}


def tenant_coach_node(state: NegotiationState) -> dict:
    return {"coach_advice": "【模拟辅导】请明确诉求、依据和可接受的协商范围。"}


def landlord_node(
    state: NegotiationState, *,
    responder: Callable[[NegotiationState], str] | None = None,
) -> dict:
    if responder is not None:
        response = responder(state.model_copy(deep=True))
        terms = _extract_landlord_terms(response)
        return {
            "landlord_response": response,
            "candidate_terms": terms,
            "landlord_confirmed": bool(terms),
            "evidence_ids": re.findall(r"LAW-\d+", response),
        }
    return {
        "landlord_response": "【模拟房东】已收到诉求，请补充合同约定；暂未确认任何条件。",
        "candidate_terms": {},
        "landlord_confirmed": False,
        "evidence_ids": [],
    }


def rule_score_node(state: NegotiationState) -> dict:
    try:
        score = calculate_score(
            {**state.confirmed_terms, **state.candidate_terms}, state.scoring_rules,
        )
    except (ValueError, TypeError):
        score = None  # The critic rejects the malformed candidate next.
    return {"candidate_score": score}


def _check_candidate(state: NegotiationState) -> str:
    try:
        terms = _TERMS_ADAPTER.validate_python(state.candidate_terms, strict=True)
        evidence_ids = _EVIDENCE_ADAPTER.validate_python(state.evidence_ids, strict=True)
    except ValidationError:
        return "候选条件或法条引用结构校验失败。"
    if terms and not state.landlord_confirmed:
        return "候选条件尚未得到模拟房东明确确认。"
    if len(evidence_ids) != len(set(evidence_ids)):
        return "候选法条引用重复。"
    if not set(evidence_ids).issubset(state.available_evidence_ids):
        return "候选法条不属于本次已核验的证据集合。"
    if evidence_ids != re.findall(r"LAW-\d+", state.landlord_response):
        return "候选法条与模拟房东回复不一致。"

    extracted = _extract_landlord_terms(state.landlord_response)
    for key, value in terms.items():
        if key in state.scoring_rules:
            if not state.scoring_rules[key].accepts(value):
                return "候选数值无效或碰撞协商底线。"
            if key not in extracted or value != extracted[key]:
                return "候选数值未在模拟房东回复中明确确认。"
        else:
            # Preserve Day 6's unscored explicit simulated arrangements only.
            prefix = "【模拟房东】确认本轮安排："
            if not (
                state.landlord_response.startswith(prefix)
                and value == {"arrangement": [state.landlord_response[len(prefix):]]}
            ):
                return "候选条件缺少适用规则或明确的安排确认。"
    if set(extracted) - set(terms):
        return "候选条件遗漏模拟房东已确认的数值。"
    return ""


def critic_node(state: NegotiationState) -> dict:
    feedback = _check_candidate(state)
    if feedback:
        return {
            "errors": [feedback], "status": "needs_review",
        }

    merged_terms = {**deepcopy(state.confirmed_terms), **deepcopy(state.candidate_terms)}
    # Recompute from validated terms; never trust a model-provided trial score.
    score = calculate_score(merged_terms, state.scoring_rules)
    completed_rounds = state.round_count + 1
    return {
        "confirmed_terms": merged_terms,
        "confirmed_evidence_ids": list(dict.fromkeys([
            *state.confirmed_evidence_ids, *state.evidence_ids,
        ])),
        "candidate_terms": {},
        "evidence_ids": [],
        "candidate_score": None,
        "trial_score": score,
        "score_explanation": explain_score(score),
        "history": [
            *deepcopy(state.history),
            NegotiationMessage(role="user", content=state.user_input),
            NegotiationMessage(role="tenant_coach", content=state.coach_advice),
            NegotiationMessage(role="landlord", content=state.landlord_response),
        ],
        "round_count": completed_rounds,
        "status": "completed" if completed_rounds == MAX_ROUNDS else "success",
        "errors": [],
    }


def _route_start(state: NegotiationState) -> Literal["coach", "completed"]:
    return "completed" if state.round_count >= MAX_ROUNDS else "coach"


def _route_critic(state: NegotiationState) -> Literal["retry", "end"]:
    # retry_count counts rewrites, so it is incremented only by the retry node.
    return "retry" if state.status == "needs_review" and state.retry_count < MAX_RETRIES else "end"


def _retry_node(state: NegotiationState) -> dict:
    return {
        "retry_count": state.retry_count + 1,
        "candidate_terms": {}, "evidence_ids": [], "candidate_score": None,
        "landlord_confirmed": False,
    }


def _completed_node(state: NegotiationState) -> dict:
    return {"status": "completed"}


def build_negotiation_graph(
    *, landlord_responder: Callable[[NegotiationState], str] | None = None,
):
    builder = StateGraph(NegotiationState)
    builder.add_node("tenant_coach", tenant_coach_node)
    if landlord_responder is None:
        builder.add_node("landlord", landlord_node)
    else:
        def respond(state: NegotiationState) -> dict:
            return landlord_node(state, responder=landlord_responder)
        builder.add_node("landlord", respond)
    builder.add_node("rule_score", rule_score_node)
    builder.add_node("critic", critic_node)
    builder.add_node("retry", _retry_node)
    builder.add_node("completed", _completed_node)
    builder.add_conditional_edges(START, _route_start, {
        "coach": "tenant_coach", "completed": "completed",
    })
    builder.add_edge("tenant_coach", "landlord")
    builder.add_edge("landlord", "rule_score")
    builder.add_edge("rule_score", "critic")
    builder.add_conditional_edges("critic", _route_critic, {"retry": "retry", "end": END})
    builder.add_edge("retry", "landlord")
    builder.add_edge("completed", END)
    return builder.compile()


negotiation_graph = build_negotiation_graph()
