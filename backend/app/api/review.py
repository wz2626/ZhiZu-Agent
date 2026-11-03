"""Contract risk-review endpoint with request-scoped service cleanup."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header
from backend.app.core.interaction import require_visible_fields
from backend.app.schemas.interaction import validate_headers

from backend.app.core.config import Settings, get_settings
from backend.app.schemas.review import ReviewDetailedResponse, ReviewRequest, ReviewResponse
from backend.app.services.review import ContractReviewService
from backend.app.schemas.proposal import ProposalRequest, ProposalResponse
from backend.app.services.proposal import (
    ProposalService, ProposalConflict, ProposalClauseMissing, ProposalCapacityExceeded, ProposalAnswerInvalid, proposal_service,
)
from backend.app.services.review_context import ReviewContextMissing
from backend.app.services.operation_store import OperationBusy, OperationExpired
from backend.app.services.model_gateway import cloud_executor

router = APIRouter(tags=["review"])


def get_proposal_service() -> ProposalService:
    return proposal_service


@router.post("/proposal", response_model=ProposalResponse, operation_id="generate_review_proposal")
async def generate_proposal(
    request: ProposalRequest,
    service: Annotated[ProposalService, Depends(get_proposal_service)],
    interaction_version: Annotated[str | None, Header(alias="X-Interaction-Version")] = None,
) -> ProposalResponse:
    validate_headers(interaction_version)
    require_visible_fields(interaction_version, [{"field": "goal_text", "text": request.goal_text},
                          *[{"field": "answers", "index": index, "question_id": answer.question_id, "text": answer.text}
                            for index, answer in enumerate(request.answers)]])
    try:
        return await cloud_executor.run(lambda: service.generate(request))
    except ReviewContextMissing:
        raise HTTPException(status_code=410, detail="审查上下文已失效，请重新分析合同后生成草稿。") from None
    except ProposalClauseMissing:
        raise HTTPException(status_code=404, detail="该条款不属于当前审查结果，请重新选择。") from None
    except ProposalConflict:
        raise HTTPException(status_code=409, detail="草稿请求编号已用于不同内容，请使用新编号。") from None
    except ProposalCapacityExceeded:
        raise HTTPException(status_code=429, detail="当前审查的草稿请求已达上限，请重新分析合同。") from None
    except ProposalAnswerInvalid:
        raise HTTPException(status_code=422, detail="补充回答不属于当前条款的有效问题，请重新核对。") from None
    except OperationBusy:
        raise HTTPException(503, detail={"code": "REQUEST_INFLIGHT", "message": "服务繁忙或原请求仍在处理，请保留编号稍后重试。"}, headers={"Retry-After": "2"}) from None
    except OperationExpired:
        raise HTTPException(410, detail={"code": "OPERATION_EXPIRED", "message": "原操作已超过处理期限，结果不会发布；请保留内容并明确重新生成。"}) from None


def get_review_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewService:
    # Both APIs check masked input before creating any cloud client.
    return ContractReviewService(settings=settings, defer_chat_init=True)


async def _review_job(service, request, *, detailed):
    def work():
        method = service.analyze_contract_detailed if detailed else service.analyze_contract
        return method(request.contract_text, top_k=request.top_k)
    try:
        return await cloud_executor.run(work, cleanup=service.close)
    except OperationBusy:
        raise HTTPException(503, detail={"code": "SERVICE_BUSY", "message": "云端处理繁忙，请稍后重试。"}, headers={"Retry-After": "2"}) from None
    except OperationExpired:
        raise HTTPException(503, detail={"code": "OPERATION_EXPIRED", "message": "本次处理已超过期限，请保留输入后重试。"}) from None


@router.post("/analyze", response_model=ReviewResponse)
async def analyze_contract(
    request: ReviewRequest,
    service: Annotated[ContractReviewService, Depends(get_review_service)],
) -> ReviewResponse:
    return await _review_job(service, request, detailed=False)


@router.post("/analyze-detailed", response_model=ReviewDetailedResponse)
async def analyze_contract_detailed(
    request: ReviewRequest,
    service: Annotated[ContractReviewService, Depends(get_review_service)],
    interaction_version: Annotated[str | None, Header(alias="X-Interaction-Version")] = None,
) -> ReviewDetailedResponse:
    validate_headers(interaction_version)
    require_visible_fields(interaction_version, [{"field": "contract_text", "text": request.contract_text}])
    return await _review_job(service, request, detailed=True)
