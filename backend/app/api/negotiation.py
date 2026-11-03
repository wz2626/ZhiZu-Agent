"""One discoverable HTTP submit route backed by isolated in-memory sessions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header
from backend.app.core.interaction import require_visible_fields
from backend.app.core.privacy import privacy_policy

from backend.app.core.privacy import redact_pii
from backend.app.schemas.negotiation import NegotiationRequest, NegotiationResponse
from backend.app.schemas.interaction import NegotiationMeta, validate_headers
from backend.app.services.negotiation_graph import build_negotiation_graph, scenario_landlord_responder
from backend.app.services.negotiation_service import (NegotiationConflict, NegotiationService,
    NegotiationRoundConflict, NegotiationSessionInvalid)
from backend.app.services.negotiation_service import NegotiationCapacityExceeded
from backend.app.services.practice_policy import MISSING_FACTS as _FACTS, final_offer_round
from backend.app.services.negotiation_trace import public_feedback
from backend.app.services.scoring import scenario_scoring_rules

router = APIRouter(prefix="/api/negotiation", tags=["negotiation"])
_service = NegotiationService(
    build_negotiation_graph(landlord_responder=scenario_landlord_responder), public_api=True,
)


def get_negotiation_service() -> NegotiationService:
    return _service




@router.get("/meta", response_model=NegotiationMeta)
def negotiation_meta(service: Annotated[NegotiationService, Depends(get_negotiation_service)]):
    return {"interaction_version": 4, "practice_epoch": service.practice_epoch,
            "privacy_policy_version": privacy_policy()["version"], "privacy_policy": privacy_policy(),
            "mode": "fixed_offline", "max_rounds": 5,
            "scenarios": {key: {"final_offer_from_round": final_offer_round(key)} for key in _FACTS}}


@router.post("/turn", response_model=NegotiationResponse)
def negotiate_turn(
    request: NegotiationRequest,
    service: Annotated[NegotiationService, Depends(get_negotiation_service)],
    interaction_version: Annotated[str | None, Header(alias="X-Interaction-Version")] = None,
    practice_epoch: Annotated[str | None, Header(alias="X-Practice-Epoch")] = None,
    expected_round: Annotated[int | None, Header(alias="X-Expected-Round", ge=0, le=5)] = None,
) -> NegotiationResponse:
    if interaction_version == "4" and practice_epoch is not None and practice_epoch != service.practice_epoch:
        # A retry may have committed in the old process. Never turn it into a
        # fresh privacy-preview transaction in the new instance.
        raise HTTPException(409, detail={"code": "SESSION_INVALID", "message": "练习服务已重启，旧请求结果无法恢复；记录仍保留。"})
    validate_headers(interaction_version, practice=True, epoch=practice_epoch, expected_round=expected_round)
    require_visible_fields(interaction_version, [{"field": "user_input", "text": request.user_input}])
    # Defense in depth: direct service users receive the same masking guard.
    try:
        result = service.negotiate_with_effect(
            request.session_id, redact_pii(request.user_input), request_id=request.request_id,
            scenario=request.scenario,
            practice_epoch=practice_epoch if interaction_version == "4" else None,
            expected_round=expected_round if interaction_version == "4" else None,
            response_validator=lambda result: _response(request.request_id, result),
        )
    except NegotiationSessionInvalid:
        raise HTTPException(409, detail={"code": "SESSION_INVALID", "message": "练习服务已重启，旧请求结果无法恢复；记录仍保留。"}) from None
    except NegotiationRoundConflict:
        raise HTTPException(409, detail={"code": "ROUND_CONFLICT", "message": "练习轮次已变化，请保留记录并另开练习。"}) from None
    except NegotiationConflict:
        raise HTTPException(status_code=409, detail={"code": "REQUEST_CONFLICT", "message": "会话场景或请求编号冲突，请保留原请求内容。"}) from None
    except NegotiationCapacityExceeded:
        raise HTTPException(429, detail={"code": "PRACTICE_CAPACITY", "message": "当前练习或服务容量已达上限，请保存清单后稍后再试。"}) from None
    # Python callers may have cached a wider public snapshot. The HTTP boundary
    # also checks replay without changing the shared service's compatibility.
    _require_http_terms(result.public_response.scenario, result.public_response.confirmed_terms)
    return result.public_response


def _require_http_terms(scenario, terms):
    rules = scenario_scoring_rules(scenario)
    if any(key not in rules or not rules[key].accepts(value) for key, value in terms.items()):
        raise HTTPException(422, detail={
            "code": "UNSUPPORTED_HTTP_TERMS",
            "message": "HTTP演练仅支持本场景的数值条件，请检查演练配置。",
        })


def _response(request_id, result):
    state = result.state
    # Called under the session lock before either state or receipt publishes.
    # Use an explicit control response, not an uncaught Pydantic exception.
    _require_http_terms(state.scenario, state.confirmed_terms)
    failed = state.status == "needs_review"
    return NegotiationResponse(
        session_id=state.session_id, request_id=request_id, scenario=state.scenario,
        status=state.status, round_count=state.round_count, confirmed_terms=state.confirmed_terms,
        confirmed_evidence_ids=state.confirmed_evidence_ids, trial_score=state.trial_score,
        score_explanation=state.score_explanation,
        coach_advice="" if failed else state.coach_advice,
        landlord_response="" if failed else state.landlord_response,
        retry_count=state.retry_count, errors=public_feedback(state.errors), trace=state.trace,
        unresolved_requests=["本轮未提交，需人工复核后重新协商。"] if failed else ["返还或付款日期、交接安排仍需明确确认。"],
        missing_facts=_FACTS[state.scenario], turn_effect=result.turn_effect, replayed=state.replayed,
    )
