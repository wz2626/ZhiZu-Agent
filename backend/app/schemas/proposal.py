"""Independent proposal drafting contracts; no negotiation state is accepted."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from backend.app.core.privacy import redact_pii
from backend.app.schemas.knowledge import LawId

ContextId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$", strict=True)]
ClauseId = Annotated[str, StringConstraints(pattern=r"^C-\d{2,}$", strict=True)]
RequestId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", strict=True)]


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_context_id: ContextId
    clause_id: ClauseId
    goal_text: str = Field(min_length=1, max_length=2000, strict=True)
    draft_request_id: RequestId

    @field_validator("goal_text")
    @classmethod
    def nonblank_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal cannot be blank")
        return value

    @field_validator("draft_request_id")
    @classmethod
    def safe_request_id(cls, value: str) -> str:
        if redact_pii(value) != value:
            raise ValueError("request identifier contains sensitive numbers")
        return value


class ProposalTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sequence: int = Field(ge=1, strict=True)
    node: Literal["context", "configuration", "drafting", "critic", "retry"]
    attempt: int = Field(ge=0, le=3, strict=True)
    status: Literal["completed", "failed", "retry", "needs_review"]
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    evidence_ids: list[LawId] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)


class ProposalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposed_message: str = Field(min_length=1, max_length=2000, strict=True)
    evidence_ids: list[LawId]
    questions: list[Annotated[str, StringConstraints(min_length=1, max_length=300, strict=True)]] = Field(max_length=8)

    @model_validator(mode="after")
    def valid_text(self):
        if not self.proposed_message.strip() or any(not item.strip() for item in self.questions):
            raise ValueError("draft text cannot be blank")
        return self


class ProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_context_id: ContextId
    clause_id: ClauseId
    draft_request_id: RequestId
    status: Literal["success", "needs_review"]
    proposed_message: str = ""
    evidence_ids: list[LawId] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    failure_code: str | None = None
    reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0, le=2, strict=True)
    trace_label: Literal["本次执行回放"] = "本次执行回放"
    trace: list[ProposalTraceEvent] = Field(default_factory=list)
    replayed: bool = False

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "success":
            if not self.proposed_message.strip() or self.failure_code or self.reason or self.errors:
                raise ValueError("successful proposal requires a valid draft")
        elif self.proposed_message or self.evidence_ids or self.questions or not self.failure_code or not self.reason or not self.errors:
            raise ValueError("failed proposal cannot expose a candidate draft")
        if [item.sequence for item in self.trace] != list(range(1, len(self.trace) + 1)):
            raise ValueError("trace sequence must be continuous")
        return self
