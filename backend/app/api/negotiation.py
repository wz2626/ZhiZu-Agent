"""One discoverable HTTP submit route backed by isolated in-memory sessions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.privacy import redact_pii
from backend.app.schemas.negotiation import NegotiationRequest, NegotiationResponse
from backend.app.services.negotiation_graph import build_negotiation_graph, scenario_landlord_responder
from backend.app.services.negotiation_service import NegotiationConflict, NegotiationService
from backend.app.services.negotiation_trace import public_feedback

router = APIRouter(prefix="/api/negotiation", tags=["negotiation"])
_service = NegotiationService(
    build_negotiation_graph(landlord_responder=scenario_landlord_responder), public_api=True,
)


def get_negotiation_service() -> NegotiationService:
    return _service


_FACTS = {
    "deposit": ["核对押金收据、扣减明细与交接记录。"],
    "maintenance": ["核对损坏原因、报修记录与维修费用凭证。"],
    "early_termination": ["核对通知日期、费用约定与房屋交接安排。"],
}


@router.post("/turn", response_model=NegotiationResponse)
def negotiate_turn(
    request: NegotiationRequest,
    service: Annotated[NegotiationService, Depends(get_negotiation_service)],
) -> NegotiationResponse:
    # Defense in depth: direct service users receive the same masking guard.
    try:
        state = service.negotiate(
            request.session_id, redact_pii(request.user_input), request_id=request.request_id,
            scenario=request.scenario,
        )
    except NegotiationConflict:
        raise HTTPException(status_code=409, detail="会话场景或请求编号冲突，请开始新会话或使用新请求编号。") from None
    failed = state.status == "needs_review"
    return NegotiationResponse(
        session_id=state.session_id, request_id=request.request_id, scenario=state.scenario,
        status=state.status, round_count=state.round_count, confirmed_terms=state.confirmed_terms,
        confirmed_evidence_ids=state.confirmed_evidence_ids, trial_score=state.trial_score,
        score_explanation=state.score_explanation,
        coach_advice="" if failed else state.coach_advice,
        landlord_response="" if failed else state.landlord_response,
        retry_count=state.retry_count, errors=public_feedback(state.errors), trace=state.trace,
        unresolved_requests=["本轮未提交，需人工复核后重新协商。"] if failed else ["返还或付款日期、交接安排仍需明确确认。"],
        missing_facts=_FACTS[state.scenario], replayed=state.replayed,
    )
