"""Manual multipart ownership and text-only import. Never invokes cloud services."""

import asyncio
from uuid import uuid4

import anyio
from fastapi import APIRouter, Request
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.requests import ClientDisconnect

from backend.app.core.document_limits import Budget, DocumentError, FILE_BYTES, UPLOAD_SECONDS, error_body, extractor_info
from backend.app.schemas.contracts import ContractParseResponse
from backend.app.schemas.interaction import validate_headers
from backend.app.services.contract_parser import document_format, parse_contract
from backend.app.services.parse_jobs import close_form, parse_runtime

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.post("/parse", response_model=ContractParseResponse, openapi_extra={"requestBody": {
    "required": True, "content": {"multipart/form-data": {"schema": {"type": "object",
        "required": ["file"], "additionalProperties": False,
        "properties": {"file": {"type": "string", "format": "binary"}}}}}}})
async def parse_upload(request: Request):
    request_id = request.scope.setdefault("state", {}).setdefault("parse_request_id", uuid4().hex)
    form, lease, transferred, info = None, None, False, None
    try:
        try:
            validate_headers(request.headers.get("X-Interaction-Version"))
        except HTTPException:
            raise DocumentError("INTERACTION_VERSION", status=409) from None
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
            raise DocumentError("INVALID_UPLOAD", status=400)
        lease = parse_runtime.admit()
        if lease is None:
            raise DocumentError("PARSER_BUSY", status=503)
        try:
            with anyio.fail_after(UPLOAD_SECONDS):
                form = await request.form(max_files=1, max_fields=0)
        except TimeoutError:
            raise DocumentError("UPLOAD_TIMEOUT", status=504) from None
        except (MultiPartException, HTTPException, ClientDisconnect):
            raise DocumentError("INVALID_UPLOAD", status=400) from None
        items = form.multi_items()
        if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
            raise DocumentError("INVALID_UPLOAD", status=400)
        upload = items[0][1]
        if not upload.size:
            raise DocumentError("EMPTY_FILE")
        if upload.size > FILE_BYTES:
            raise DocumentError("FILE_TOO_LARGE", status=413)
        format_name = document_format(upload.filename)
        info = extractor_info(format_name)
        request.scope["state"]["parse_extractor"] = info
        budget = Budget()
        job = parse_runtime.start(form, lease, lambda: parse_contract(upload.file, format_name, upload.size, request_id, budget))
        transferred = True
        # A native Task.cancel on this HTTP waiter must not cancel the job task.
        result = await asyncio.shield(job.task)
        return ContractParseResponse(**result)
    except DocumentError as error:
        headers = {"Cache-Control": "no-store"}
        if error.code == "PARSER_BUSY":
            headers["Retry-After"] = "2"
            if request.scope.get("http_version") == "1.1":
                headers["Connection"] = "close"
        return JSONResponse(error_body(error, request_id, info), status_code=error.status, headers=headers)
    except Exception:
        return JSONResponse(error_body(DocumentError("PARSE_FAILED", status=500), request_id, info), status_code=500)
    finally:
        if not transferred:
            close_form(form)
            if lease is not None:
                lease.release()
