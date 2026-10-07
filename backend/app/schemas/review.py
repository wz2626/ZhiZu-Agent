"""Input and output contracts for the Day 3 contract-review service."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from backend.app.schemas.knowledge import LawId


class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ReviewClauseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: Annotated[str, StringConstraints(pattern=r"^C-\d{2,}$")]
    original_clause: str = Field(min_length=1, strict=True)
    risk_level: RiskLevel
    explanation: str = Field(strict=True)
    evidence_ids: list[LawId]
    negotiation_tip: str = Field(strict=True)

    @model_validator(mode="after")
    def validate_risk_details(self) -> "ReviewClauseResult":
        if not self.original_clause.strip():
            raise ValueError("original_clause must contain text")
        if self.risk_level != RiskLevel.NONE:
            if not self.explanation.strip() or not self.negotiation_tip.strip():
                raise ValueError("risk findings require an explanation and negotiation tip")
        return self


class ReviewRequest(BaseModel):
    contract_text: str = Field(min_length=10, max_length=5000, strict=True)
    top_k: int = Field(default=4, ge=1, le=8, strict=True)

    @field_validator("contract_text")
    @classmethod
    def reject_blank_contract(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("contract_text must contain text")
        return value


class ReviewResponse(BaseModel):
    status: Literal["success", "mock"]
    results: list[ReviewClauseResult] = Field(min_length=1)
    total_risks: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_risk_count(self) -> "ReviewResponse":
        expected = sum(item.risk_level != RiskLevel.NONE for item in self.results)
        if self.total_risks != expected:
            raise ValueError("total_risks must count HIGH, MEDIUM and LOW findings")
        return self
