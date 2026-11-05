"""Stateless quote analysis: model drafts and server-owned public sources."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


def text(limit, minimum=1):
    return Annotated[str, StringConstraints(strict=True, min_length=minimum, max_length=limit)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuoteRequest(StrictModel):
    request_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    contract_text: text(5000, 10)
    landlord_quote: text(2000)
    user_goal: text(300, 0) = ""
    context_note: text(1000, 0) = ""

    @field_validator("contract_text", "landlord_quote", "user_goal", "context_note", mode="before")
    @classmethod
    def newlines(cls, value):
        return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value

    @field_validator("contract_text", "landlord_quote")
    @classmethod
    def readable(cls, value):
        if not value.strip():
            raise ValueError("blank input")
        return value


SourceId = Annotated[str, StringConstraints(strict=True, pattern=r"^[CL]-[0-9]{3,4}$")]
SourceIds = Annotated[list[SourceId], Field(max_length=6)]


class Tactic(StrictModel):
    label: Literal["偷换概念", "转移责任", "情绪施压", "以偏概全", "无依据断言", "拖延推诿"]
    detail: text(200)
    quote_span: text(200)


class Breakdown(StrictModel):
    landlord_position: text(200)
    assessment: Literal["supported", "unsupported", "unclear"]
    analysis: text(500)
    tactics: Annotated[list[Tactic], Field(max_length=3)]


class Ground(StrictModel):
    source_id: SourceId
    application: text(200)


class Reply(StrictModel):
    text: text(500)
    best_for: text(60)
    source_ids: SourceIds


class Replies(StrictModel):
    tactful: Reply
    reasoned: Reply
    firm: Reply


def validate_state_binding(status, assessment, questions):
    """The same invariant is checked by Schema and again before publication."""
    if status == "success":
        if assessment not in {"supported", "unsupported"} or questions:
            raise ValueError("invalid success assessment")
    elif status == "needs_context":
        if assessment != "unclear" or not 1 <= len(questions) <= 2:
            raise ValueError("invalid needs-context assessment")
    elif status != "out_of_scope":
        raise ValueError("invalid status")


class QuoteDraft(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra={"allOf": [
        {"if": {"properties": {"status": {"const": "success"}}},
         "then": {"properties": {"breakdown": {"type": "object", "properties": {"assessment": {"enum": ["supported", "unsupported"]}}}, "replies": {"type": "object"},
                                  "clarification_questions": {"maxItems": 0}}}},
        {"if": {"properties": {"status": {"const": "needs_context"}}},
         "then": {"properties": {"breakdown": {"type": "object", "properties": {"assessment": {"const": "unclear"}}}, "replies": {"type": "object"},
                                  "clarification_questions": {"minItems": 1, "maxItems": 2}}}},
        {"if": {"properties": {"status": {"const": "out_of_scope"}}},
         "then": {"properties": {"breakdown": {"type": "null"}, "replies": {"type": "null"},
                                  "grounds": {"maxItems": 0}, "clarification_questions": {"maxItems": 0}}}},
    ]})
    breakdown: Breakdown | None
    clarification_questions: Annotated[list[text(100)], Field(max_length=2)]
    grounds: Annotated[list[Ground], Field(max_length=6)]
    replies: Replies | None
    # Emission order is a prompt aid, not a repair: the service still rejects
    # contradictory values. Let the model assess before choosing its status.
    status: Literal["success", "needs_context", "out_of_scope"]

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "out_of_scope":
            if self.breakdown is not None or self.grounds or self.replies is not None or self.clarification_questions:
                raise ValueError("invalid out-of-scope result")
        else:
            if self.breakdown is None or self.replies is None:
                raise ValueError("missing card content")
            validate_state_binding(self.status, self.breakdown.assessment, self.clarification_questions)
        return self


class QuoteSource(StrictModel):
    source_id: SourceId
    kind: Literal["contract", "law"]
    title: str
    original_text: str
    source_url: str | None = None
    law_id: str | None = None
    verified_date: str | None = None
    paragraph_index: int | None = None
    part_index: int | None = None


class PublicGround(QuoteSource):
    application: str


class QuoteCard(StrictModel):
    breakdown: Breakdown
    grounds: list[PublicGround]
    replies: Replies
    clarification_questions: list[str]


class QuoteResponse(StrictModel):
    schema_version: Literal["quote-v1"] = "quote-v1"
    request_id: str
    status: Literal["success", "needs_context", "out_of_scope"]
    card: QuoteCard | None

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "out_of_scope":
            if self.card is not None:
                raise ValueError("unexpected out-of-scope card")
        else:
            if self.card is None:
                raise ValueError("missing public card")
            validate_state_binding(self.status, self.card.breakdown.assessment, self.card.clarification_questions)
        return self
