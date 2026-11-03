"""Public text-only import response, separate from review schemas."""

from typing import Literal
from pydantic import BaseModel, Field


class ExtractionWarning(BaseModel):
    code: str
    message: str
    pages: list[int] = Field(default_factory=list)


class ExtractionDocument(BaseModel):
    format: Literal["pdf", "docx"]
    size_bytes: int
    page_count: int | None
    table_count: int


class ExtractorInfo(BaseModel):
    name: str
    version: str
    policy_version: str


class ContractParseResponse(BaseModel):
    status: Literal["success"] = "success"
    text: str = Field(max_length=20000)
    char_count: int
    document: ExtractionDocument
    limits: dict[str, int] = Field(default_factory=lambda: {"analysis_chars": 5000, "import_chars": 20000})
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    request_id: str
    extractor: ExtractorInfo
