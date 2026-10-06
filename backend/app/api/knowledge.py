"""Read-only endpoints for lease-law KB status and evidence retrieval."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.config import Settings, get_settings
from backend.app.schemas.knowledge import KBSearchRequest, KBSearchResponse, KBStatusResponse
from backend.app.services.vector_store import LawVectorStoreService, mask_sensitive_text

router = APIRouter(prefix="/api/kb", tags=["knowledge"])


def _not_ready(indexed_count: int) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "KB_NOT_READY",
            "message": "知识库尚未就绪，请先运行 scripts/init_kb.py。",
            "indexed_count": indexed_count,
        },
    )


def _boundary_notice(query: str) -> tuple[bool, str]:
    if "押金" in query or "保证金" in query:
        return (
            False,
            "本章无直接规定押金返还或扣减的条文；仅返回相关条文供参考，"
            "具体返还条件还需补充合同约定及其他适用依据。",
        )
    if "提前退租" in query or re.search(r"几天|多少天|固定天数|违约金", query):
        return (
            False,
            "本章没有对所有提前退租情形规定统一的通知天数或费用；"
            "仅返回相关条文供参考，还需补充合同约定及其他适用依据。",
        )
    return True, ""


@router.get("/status", response_model=KBStatusResponse)
def kb_status(settings: Annotated[Settings, Depends(get_settings)]) -> KBStatusResponse:
    return LawVectorStoreService.inspect_status(settings.chroma_path)


@router.post("/search", response_model=KBSearchResponse)
def kb_search(
    request: KBSearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> KBSearchResponse:
    safe_query = mask_sensitive_text(request.query)
    status = LawVectorStoreService.inspect_status(settings.chroma_path)
    if not status.is_ready:
        raise _not_ready(status.indexed_count)
    try:
        service = LawVectorStoreService(
            persist_directory=settings.chroma_path, create_if_missing=False,
        )
    except ValueError:
        raise _not_ready(status.indexed_count) from None
    sufficient, notice = _boundary_notice(safe_query)
    return KBSearchResponse(
        query=safe_query,
        top_k=request.top_k,
        results=service.search_evidence(safe_query, top_k=request.top_k),
        direct_basis_sufficient=sufficient,
        boundary_notice=notice,
    )
