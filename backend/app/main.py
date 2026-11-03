from typing import Annotated
from contextlib import asynccontextmanager
from multiprocessing import parent_process
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api.knowledge import router as knowledge_router
from backend.app.api.review import router as review_router
from backend.app.api.negotiation import router as negotiation_router
from backend.app.api.contracts import router as contracts_router
from backend.app.core.config import PROJECT_ROOT, Settings, get_settings
from backend.app.schemas.health import HealthResponse
from backend.app.core.http_limits import ApiBoundary

def require_single_process():
    if parent_process() is not None or any(int(os.getenv(key, "1")) > 1 for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS")):
        raise RuntimeError("In-memory state requires one process; start without multiple workers.")


@asynccontextmanager
async def lifespan(app):
    require_single_process()
    yield


app = FastAPI(title="ZhiZu-Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Interaction-Version", "X-Practice-Epoch", "X-Expected-Round"],
)
app.add_middleware(ApiBoundary)
app.include_router(knowledge_router)
app.include_router(review_router, prefix="/api/review")
app.include_router(negotiation_router)
app.include_router(contracts_router)


@app.exception_handler(RequestValidationError)
async def safe_request_validation(request, exc):
    if request.url.path in {"/api/negotiation/turn", "/api/review/proposal"}:
        label = "草稿" if request.url.path == "/api/review/proposal" else "谈判"
        return JSONResponse(status_code=422, content={"detail": f"{label}请求格式无效，请检查字段、长度与标识。"})
    if request.url.path in {"/api/review/analyze", "/api/review/analyze-detailed", "/api/kb/search"}:
        # Preserve field/type diagnostics without echoing raw contracts, search
        # text, or validator exception payloads before the masking boundary.
        errors = [{
            "type": error["type"], "loc": [part if isinstance(part, int) or part in {
                "body", "query", "header", "path", "contract_text", "top_k", "query_text", "query", "limit"
            } else "field" for part in error["loc"]],
            "msg": "请求字段格式无效，请检查类型、长度与取值范围。",
        } for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})
    return JSONResponse(status_code=422, content={"detail": "请求字段格式无效，请检查类型、长度与取值范围。"})


@app.exception_handler(Exception)
async def safe_unexpected_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": {
        "code": "INTERNAL_ERROR", "message": "服务暂时不可用，请保留原请求编号重试。"
    }}, headers={"Cache-Control": "no-store"})


app.mount(
    "/vendor",
    StaticFiles(directory=PROJECT_ROOT / "frontend-web" / "vendor"),
    name="frontend-vendor",
)


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        project="ZhiZu-Agent",
        version=app.version,
        env_configured=settings.env_configured,
    )


@app.get("/", response_class=FileResponse, include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "frontend-web" / "index.html")
