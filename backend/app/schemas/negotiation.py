"""Isolated negotiation state and candidate evidence boundaries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from backend.app.core.privacy import redact_pii
from backend.app.schemas.knowledge import LawId
from backend.app.services.scoring import ScoringRule, default_scoring_rules

MAX_ROUNDS = 5
MAX_RETRIES = 2
Scenario = Literal["deposit", "maintenance", "early_termination"]


def normalize_scenario(value: str) -> str:
    return {"repair": "maintenance", "termination": "early_termination"}.get(value, value)


class NegotiationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", strict=True)
    user_input: str = Field(min_length=1, max_length=2000, strict=True)
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", strict=True)
    scenario: Literal["deposit", "maintenance", "repair", "early_termination", "termination"] = "deposit"

    @field_validator("session_id", "request_id")
    @classmethod
    def reject_sensitive_identifiers(cls, value: str) -> str:
        if redact_pii(value) != value:
            raise ValueError("identifiers cannot contain sensitive numbers")
        return value

    @field_validator("user_input")
    @classmethod
    def reject_blank_input(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_input must contain text")
        return value


class NegotiationTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1, strict=True)
    node: Literal["tenant_coach", "landlord", "rule_score", "critic", "retry", "completed", "graph"]
    attempt: int = Field(ge=0, le=3, strict=True)
    status: Literal["completed", "failed", "retry", "needs_review"]
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    feedback: list[str] = Field(default_factory=list)
    evidence_ids: list[LawId] = Field(default_factory=list)


class NegotiationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "tenant_coach", "landlord"]
    content: str = Field(min_length=1, strict=True)


class NegotiationTermChange(BaseModel):
    """A factual change between two committed snapshots, never a stance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    term: str = Field(min_length=1, strict=True)
    change_type: Literal["added", "updated"]
    before: JsonValue
    after: JsonValue
    direction: Literal["improved", "worsened", "adjusted"]

    @model_validator(mode="after")
    def validate_added_term(self):
        if self.change_type == "added" and (self.before is not None or self.direction != "adjusted"):
            raise ValueError("new confirmations have no previous value or inferred direction")
        return self


class NegotiationTurnEffect(BaseModel):
    """Request-scoped comparison; excluded from the graph and score inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "first_confirmation", "improved", "worsened", "adjusted", "unchanged",
        "not_committed", "round_limit",
    ]
    score_before: int | None = Field(ge=0, le=100, strict=True)
    score_after: int | None = Field(ge=0, le=100, strict=True)
    score_delta: int | None = Field(ge=-100, le=100, strict=True)
    changes: list[NegotiationTermChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_comparison(self):
        if len({change.term for change in self.changes}) != len(self.changes):
            raise ValueError("term changes must be unique")
        if self.kind in {"not_committed", "round_limit"}:
            if self.changes or self.score_delta is not None or self.score_before != self.score_after:
                raise ValueError("uncommitted requests have no changes or score delta")
        else:
            expected = (self.score_after - self.score_before
                        if self.score_before is not None and self.score_after is not None else None)
            if self.score_delta != expected:
                raise ValueError("score delta must compare the recorded official scores")
        if self.kind == "unchanged" and self.changes:
            raise ValueError("unchanged outcomes cannot contain term changes")
        return self


class NegotiationState(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    session_id: str = Field(min_length=1, strict=True)
    scenario: Scenario = "deposit"
    trace_label: Literal["本次执行回放"] = "本次执行回放"
    trace: list[NegotiationTraceEvent] = Field(default_factory=list)
    replayed: bool = False
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


class NegotiationResponse(BaseModel):
    """Public snapshot excludes user history and rejected candidate drafts."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    request_id: str
    scenario: Scenario
    status: Literal["success", "completed", "needs_review"]
    round_count: int = Field(ge=0, le=MAX_ROUNDS, strict=True)
    confirmed_terms: dict[str, JsonValue]
    confirmed_evidence_ids: list[LawId]
    trial_score: int | None = Field(ge=0, le=100, strict=True)
    score_explanation: str
    coach_advice: str
    landlord_response: str
    retry_count: int = Field(ge=0, le=MAX_RETRIES, strict=True)
    errors: list[str]
    trace_label: Literal["本次执行回放"] = "本次执行回放"
    trace: list[NegotiationTraceEvent]
    unresolved_requests: list[str]
    missing_facts: list[str]
    turn_effect: NegotiationTurnEffect
    replayed: bool = False

    @model_validator(mode="after")
    def continuous_trace(self):
        if [event.sequence for event in self.trace] != list(range(1, len(self.trace) + 1)):
            raise ValueError("trace sequence must be continuous from one")
        return self
