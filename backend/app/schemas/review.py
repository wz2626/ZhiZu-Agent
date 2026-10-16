"""Legacy and detailed contract-review response contracts."""

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


class ReviewFailureCode(str, Enum):
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INVALID_CONTRACT_TEXT = "INVALID_CONTRACT_TEXT"
    CHAT_NOT_CONFIGURED = "CHAT_NOT_CONFIGURED"
    CHAT_INIT_FAILED = "CHAT_INIT_FAILED"
    KB_NOT_READY = "KB_NOT_READY"
    UPSTREAM_EMBEDDING_ERROR = "UPSTREAM_EMBEDDING_ERROR"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    NO_EVIDENCE = "NO_EVIDENCE"
    CHAT_TIMEOUT = "CHAT_TIMEOUT"
    CHAT_CALL_FAILED = "CHAT_CALL_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    GRAPH_EXECUTION_FAILED = "GRAPH_EXECUTION_FAILED"


class ReviewTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1, strict=True)
    node: Literal["input_guard", "configuration", "retrieval", "drafting", "critic", "mock", "graph"]
    attempt: int = Field(ge=0, le=3, strict=True)
    status: Literal["completed", "failed", "retry", "needs_review"]
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    evidence_ids: list[LawId] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)


class ReviewDetailedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "needs_review"]
    results: list[ReviewClauseResult]
    total_risks: int = Field(ge=0, strict=True)
    failure_code: ReviewFailureCode | None = None
    reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0, le=2, strict=True)
    trace_label: Literal["本次执行回放"] = "本次执行回放"
    trace: list[ReviewTraceEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> "ReviewDetailedResponse":
        expected = sum(item.risk_level != RiskLevel.NONE for item in self.results)
        if self.total_risks != expected:
            raise ValueError("total_risks must count HIGH, MEDIUM and LOW findings")
        if self.status == "success":
            if not self.results or self.failure_code is not None or self.reason is not None or self.errors:
                raise ValueError("successful review requires findings and no terminal errors")
        elif self.results or not self.failure_code or not self.reason or not self.errors:
            raise ValueError("failed review requires a reason and errors, without findings")
        if [event.sequence for event in self.trace] != list(range(1, len(self.trace) + 1)):
            raise ValueError("trace sequence must be continuous from one")
        return self
