"""Offline role graph: coach -> landlord -> critic -> commit or bounded retry.

The critic is a structural placeholder, not a legal validity assessment.
The default landlord offers no terms; user demands never become agreements.
"""

from copy import deepcopy
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas.negotiation import (
    MAX_RETRIES, MAX_ROUNDS, NegotiationMessage, NegotiationState,
)

_TERMS_ADAPTER = TypeAdapter(NegotiationState.model_fields["candidate_terms"].annotation)


def tenant_coach_node(state: NegotiationState) -> dict:
    return {"coach_advice": "【模拟辅导】请明确诉求、依据和可接受的协商范围。"}


def landlord_node(state: NegotiationState) -> dict:
    return {
        "landlord_response": "【模拟房东】已收到诉求，请补充合同约定；暂未确认任何条件。",
        "candidate_terms": {},
        "landlord_confirmed": False,
    }


def critic_node(state: NegotiationState) -> dict:
    # Validate only the candidate boundary here. Day 7 adds scenario rules,
    # legal grounding and deterministic trial scoring before this commit.
    try:
        terms = _TERMS_ADAPTER.validate_python(state.candidate_terms, strict=True)
    except ValidationError:
        feedback = "候选条件结构校验失败。"
    else:
        feedback = "候选条件尚未得到模拟房东明确确认。" if terms and not state.landlord_confirmed else ""
    if feedback:
        return {
            "errors": [feedback], "status": "needs_review",
        }

    completed_rounds = state.round_count + 1
    return {
        "confirmed_terms": {**deepcopy(state.confirmed_terms), **deepcopy(terms)},
        "candidate_terms": {},
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
    return {"retry_count": state.retry_count + 1}


def _completed_node(state: NegotiationState) -> dict:
    return {"status": "completed"}


def build_negotiation_graph():
    builder = StateGraph(NegotiationState)
    builder.add_node("tenant_coach", tenant_coach_node)
    builder.add_node("landlord", landlord_node)
    builder.add_node("critic", critic_node)
    builder.add_node("retry", _retry_node)
    builder.add_node("completed", _completed_node)
    builder.add_conditional_edges(START, _route_start, {
        "coach": "tenant_coach", "completed": "completed",
    })
    builder.add_edge("tenant_coach", "landlord")
    builder.add_edge("landlord", "critic")
    builder.add_conditional_edges("critic", _route_critic, {"retry": "retry", "end": END})
    builder.add_edge("retry", "landlord")
    builder.add_edge("completed", END)
    return builder.compile()


negotiation_graph = build_negotiation_graph()
