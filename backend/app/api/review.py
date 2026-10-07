"""Contract risk-review endpoint with request-scoped service cleanup."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.core.config import Settings, get_settings
from backend.app.schemas.review import ReviewRequest, ReviewResponse
from backend.app.services.review import ContractReviewService

router = APIRouter(tags=["review"])


def get_review_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[ContractReviewService]:
    service = ContractReviewService(settings=settings)
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
