from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    project: str
    version: str
    env_configured: bool


class StartupStatusResponse(BaseModel):
    instance_id: str | None
    chat_configured: bool
    embedding_configured: bool
