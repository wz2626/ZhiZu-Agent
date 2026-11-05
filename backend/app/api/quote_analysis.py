"""Stateless quote route, separate from the legacy negotiation graph."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.privacy import privacy_policy, redact_report
from backend.app.schemas.quote_analysis import QuoteRequest, QuoteResponse
from backend.app.services.quote_analysis import QuoteAnalysisService, QuoteFailure, quote_analysis_service
from backend.app.services.model_gateway import cloud_executor
from backend.app.services.operation_store import OperationBusy, OperationExpired

router = APIRouter(prefix="/api/negotiation", tags=["quote-analysis"])


def get_quote_service():
    return quote_analysis_service


@router.get("/quote-meta")
def quote_meta():
    return {"schema_version": "quote-v1", "privacy_policy": privacy_policy(),
            "limits": {"contract_text": 5000, "contract_min": 10, "landlord_quote": 2000,
                       "user_goal": 300, "context_note": 1000}}


@router.post("/analyze-quote", response_model=QuoteResponse)
async def analyze_quote(request: QuoteRequest, service: Annotated[QuoteAnalysisService, Depends(get_quote_service)]):
    if redact_report(request.request_id)["safe_text"] != request.request_id:
        raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "请求编号不得包含个人号码。"})
    changed = []
    for field in ("contract_text", "landlord_quote", "user_goal", "context_note"):
        report = redact_report(getattr(request, field))
        if report["safe_text"] != getattr(request, field):
            changed.append({"field": field, **report})
    if changed:
        raise HTTPException(428, detail={"code": "PRIVACY_PREVIEW_REQUIRED",
            "privacy_policy_version": privacy_policy()["version"], "fields": changed})
    try:
        return await cloud_executor.run(lambda: service.analyze(request))
    except QuoteFailure as error:
        raise HTTPException(error.status, detail={"code": error.code, "message": error.message}) from None
    except OperationBusy:
        raise HTTPException(503, detail={"code": "SERVICE_BUSY", "message": "服务繁忙，请稍后明确重新生成。"}, headers={"Retry-After": "2"}) from None
    except OperationExpired:
        raise HTTPException(504, detail={"code": "MODEL_TIMEOUT", "message": "本次等待已超时；重新生成可能再次计费，请保留内容。"}) from None
