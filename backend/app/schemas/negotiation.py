"""Isolated negotiation state and candidate evidence boundaries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from backend.app.services.scoring import ScoringRule, default_scoring_rules

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
    # Candidate references are checked by the critic, never used as points.
    evidence_ids: list[str] = Field(default_factory=list)
    available_evidence_ids: list[str] = Field(default_factory=list)
    confirmed_evidence_ids: list[str] = Field(default_factory=list)
    scoring_rules: dict[str, ScoringRule] = Field(default_factory=default_scoring_rules)
    candidate_score: int | None = Field(default=None, ge=0, le=100, strict=True)
    score_explanation: str = ""
    # Official current score: only updated after the candidate passes critic.
    trial_score: int | None = Field(default=None, ge=0, le=100, strict=True)
    retry_count: int = Field(default=0, ge=0, le=MAX_RETRIES, strict=True)
    status: Literal["active", "success", "completed", "needs_review"] = "active"
    request_id: str | None = None
    user_input: str = ""
    coach_advice: str = ""
    landlord_response: str = ""
    landlord_confirmed: bool = False
    errors: list[str] = Field(default_factory=list)

    @field_validator("scoring_rules", mode="before")
    @classmethod
    def preserve_rule_numbers(cls, value):
        # Graph snapshots serialize dataclasses into dicts. Rebuild before
        # Pydantic can coerce bool/string amounts or weights into numbers.
        if not isinstance(value, dict):
            return value
        try:
            return {
                key: ScoringRule(**rule) if isinstance(rule, dict) else rule
                for key, rule in value.items()
            }
        except TypeError as exc:
            raise ValueError("invalid scoring rule configuration") from exc

    @field_validator("session_id")
    @classmethod
    def reject_blank_session_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must contain text")
        return value
