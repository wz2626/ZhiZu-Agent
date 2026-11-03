"""V4 transport controls, deliberately outside graph Trace and request caches."""

from fastapi import HTTPException

from backend.app.core.privacy import PRIVACY_POLICY_VERSION, redact_report
from backend.app.schemas.interaction import PrivacyPreview


def require_visible_fields(version: str | None, fields: list[dict]) -> None:
    if version is None:
        return
    if version != "4":
        raise HTTPException(409, detail={"code": "INTERACTION_VERSION", "message": "交互协议已更新，请刷新页面。"})
    changed = []
    for field in fields:
        report = redact_report(field["text"])
        if report["safe_text"] != field["text"]:
            changed.append({key: value for key, value in field.items() if key != "text"} | report)
    if changed:
        detail = PrivacyPreview(privacy_policy_version=PRIVACY_POLICY_VERSION, fields=changed)
        raise HTTPException(428, detail=detail.model_dump(exclude_none=True),
                            headers={"Cache-Control": "no-store"})
