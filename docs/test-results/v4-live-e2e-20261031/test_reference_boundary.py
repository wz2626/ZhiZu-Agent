"""Pure validator checks; no model client, fake response or dependency override."""
import json
import pytest
from backend.app.services.proposal import validate_proposal, DraftValidationError

@pytest.mark.parametrize("text", [
    "请核对合同中的维修责任约定，并明确维修费用和安排。",
    "请核对合同第三条，并协商维修安排。",
    "请说明租约中的第十二条约定。",
])
def test_contract_expression_keeps_existing_compatibility(text):
    result = validate_proposal(json.dumps({"proposed_message":text,"evidence_ids":[],"questions":[]},ensure_ascii=False),{})
    assert result.proposed_message == text

@pytest.mark.parametrize("field,text", [
    ("proposed_message","依据第七百一十二条，请安排维修。"),
    ("proposed_message","依据第712条，请安排维修。"),
    ("proposed_message","依据LAW-712，请安排维修。"),
    ("questions","第712条是否适用？"),
    ("questions","LAW-712是否适用？"),
])
def test_empty_evidence_still_rejects_unprovided_references(field,text):
    payload={"proposed_message":"请核对维修安排。","evidence_ids":[],"questions":[]}
    payload[field]=text if field=="proposed_message" else [text]
    with pytest.raises(DraftValidationError) as caught:
        validate_proposal(json.dumps(payload,ensure_ascii=False),{})
    assert caught.value.category == "reference"
