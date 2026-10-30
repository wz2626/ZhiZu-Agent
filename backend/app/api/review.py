"""Contract risk-review endpoint with request-scoped service cleanup."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.config import Settings, get_settings
from backend.app.schemas.review import ReviewDetailedResponse, ReviewRequest, ReviewResponse
from backend.app.services.review import ContractReviewService
from backend.app.schemas.proposal import ProposalRequest, ProposalResponse
from backend.app.services.proposal import (
    ProposalService, ProposalConflict, ProposalClauseMissing, ProposalCapacityExceeded, proposal_service,
)
from backend.app.services.review_context import ReviewContextMissing

router = APIRouter(tags=["review"])


def get_proposal_service() -> ProposalService:
    return proposal_service


@router.post("/proposal", response_model=ProposalResponse, operation_id="generate_review_proposal")
def generate_proposal(
    request: ProposalRequest,
    service: Annotated[ProposalService, Depends(get_proposal_service)],
) -> ProposalResponse:
    try:
        return service.generate(request)
    except ReviewContextMissing:
        raise HTTPException(status_code=410, detail="审查上下文已失效，请重新分析合同后生成草稿。") from None
    except ProposalClauseMissing:
        raise HTTPException(status_code=404, detail="该条款不属于当前审查结果，请重新选择。") from None
    except ProposalConflict:
        raise HTTPException(status_code=409, detail="草稿请求编号已用于不同内容，请使用新编号。") from None
    except ProposalCapacityExceeded:
        raise HTTPException(status_code=429, detail="当前审查的草稿请求已达上限，请重新分析合同。") from None


def get_review_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[ContractReviewService]:
    # Both APIs check masked input before creating any cloud client.
    service = ContractReviewService(settings=settings, defer_chat_init=True)
    try:
        yield service
    finally:
        service.close()


@router.post("/analyze", response_model=ReviewResponse)
def analyze_contract(
    request: ReviewRequest,
    service: Annotated[ContractReviewService, Depends(get_review_service)],
) -> ReviewResponse:
    return service.analyze_contract(request.contract_text, top_k=request.top_k)


@router.post("/analyze-detailed", response_model=ReviewDetailedResponse)
def analyze_contract_detailed(
    request: ReviewRequest,
    service: Annotated[ContractReviewService, Depends(get_review_service)],
) -> ReviewDetailedResponse:
    return service.analyze_contract_detailed(request.contract_text, top_k=request.top_k)
