"""Typed V4 controls; practice controls never spill into cloud endpoints."""

import os
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class InteractionHeaders(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["4"]


class PracticeHeaders(InteractionHeaders):
    epoch: str = Field(pattern=r"^[a-f0-9]{32}$", strict=True)
    expected_round: int = Field(ge=0, le=5, strict=True)


def validate_headers(version, *, practice=False, epoch=None, expected_round=None):
    if version is None and (not practice or epoch is None and expected_round is None) and os.getenv("V4_ALLOW_LEGACY_HEADERS", "false").lower() == "true":
        return None
    try:
        if practice:
            return PracticeHeaders(version=version, epoch=epoch, expected_round=expected_round)
        return InteractionHeaders(version=version)
    except ValidationError:
        raise HTTPException(409, detail={"code": "INTERACTION_VERSION", "message": "交互协议已更新，请刷新页面。"}) from None


class PrivacySpan(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    kind: Literal["phone", "id"]


class PrivacyField(BaseModel):
    field: str
    index: int | None = None
    question_id: str | None = None
    safe_text: str
    spans: list[PrivacySpan]
    counts: dict[str, int]


class PrivacyPreview(BaseModel):
    code: Literal["PRIVACY_PREVIEW_REQUIRED"] = "PRIVACY_PREVIEW_REQUIRED"
    privacy_policy_version: str
    fields: list[PrivacyField]


class PrivacyPolicy(BaseModel):
    engine: Literal["fold-codepoint-v1"]
    replacement: Literal["***"]
    char_map: dict[str, str]
    version: str
    digit_zeros: list[int]
    id_pattern: str
    phone_pattern: str
    separator_pattern: str
    ignored_points: list[int] = Field(default_factory=list)
    space_points: list[int] = Field(default_factory=list)


class ScenarioMeta(BaseModel):
    final_offer_from_round: int


class NegotiationMeta(BaseModel):
    interaction_version: Literal[4] = 4
    practice_epoch: str
    privacy_policy_version: str
    privacy_policy: PrivacyPolicy
    mode: Literal["fixed_offline"] = "fixed_offline"
    max_rounds: Literal[5] = 5
    scenarios: dict[str, ScenarioMeta]
