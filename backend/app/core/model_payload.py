"""Server-owned quote delimiters around JSON data, with lossless decoding.

User angle brackets are escaped before wrapping, so a user-authored closing tag
cannot become an actual envelope boundary. Delimiters are not a security proof.
"""

import json

TENANT_OPEN = "<tenant_input>\n"
QUOTE_OPEN = "\n<landlord_quote_data>\n"
ENVELOPE_CLOSE = "\n</landlord_quote_data>\n</tenant_input>"


def _data_json(value):
    return json.dumps(value, ensure_ascii=False).replace("&", r"\u0026").replace("<", r"\u003c").replace(">", r"\u003e")


def encode_quote_payload(payload):
    tenant = {key: value for key, value in payload.items() if key != "landlord_quote"}
    return TENANT_OPEN + _data_json(tenant) + QUOTE_OPEN + _data_json(payload["landlord_quote"]) + ENVELOPE_CLOSE


def decode_model_payload(content):
    if not content.startswith(TENANT_OPEN):
        return json.loads(content)  # Unchanged legacy JSON envelope.
    if not content.endswith(ENVELOPE_CLOSE):
        raise ValueError("invalid quote envelope")
    tenant_json, quote_json = content[len(TENANT_OPEN):-len(ENVELOPE_CLOSE)].split(QUOTE_OPEN)
    tenant, quote = json.loads(tenant_json), json.loads(quote_json)
    if not isinstance(tenant, dict) or "landlord_quote" in tenant or not isinstance(quote, str):
        raise ValueError("invalid quote data")
    return {**tenant, "landlord_quote": quote}
