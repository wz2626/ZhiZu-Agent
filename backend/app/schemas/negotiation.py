"""Day 6 negotiation state; scoring and legal semantics are Day 7 work."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

MAX_ROUNDS = 5
MAX_RETRIES = 2


class NegotiationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "tenant_coach", "landlord"]
    content: str = Field(min_length=1, strict=True)


class NegotiationState(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    session_id: str = Field(min_length=1, strict=True)
    round_count: int = Field(default=0, ge=0, le=MAX_ROUNDS, strict=True)
    history: list[NegotiationMessage] = Field(default_factory=list)
    confirmed_terms: dict[str, JsonValue] = Field(default_factory=dict)
    candidate_terms: dict[str, JsonValue] = Field(default_factory=dict)
    # None means no scoring rule has been applied; never invent a model score.
    trial_score: int | None = Field(default=None, ge=0, le=100, strict=True)
    retry_count: int = Field(default=0, ge=0, le=MAX_RETRIES, strict=True)
    status: Literal["active", "success", "completed", "needs_review"] = "active"
    request_id: str | None = None
    user_input: str = ""
    coach_advice: str = ""
    landlord_response: str = ""
    landlord_confirmed: bool = False
    errors: list[str] = Field(default_factory=list)

    @field_validator("session_id")
    @classmethod
    def reject_blank_session_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must contain text")
        return value
