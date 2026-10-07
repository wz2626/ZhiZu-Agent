from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.app.api.knowledge import router as knowledge_router
from backend.app.api.review import router as review_router
from backend.app.core.config import PROJECT_ROOT, Settings, get_settings
from backend.app.schemas.health import HealthResponse

app = FastAPI(title="ZhiZu-Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(knowledge_router)
app.include_router(review_router, prefix="/api/review")


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
