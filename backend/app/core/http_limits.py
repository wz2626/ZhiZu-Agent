"""Bound bytes before Starlette buffers JSON; never log rejected payloads."""

import json
from uuid import uuid4

from starlette.responses import JSONResponse
from python_multipart.multipart import parse_options_header
from backend.app.core.document_limits import BODY_BYTES, PARSE_PATH, DocumentError, error_body


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("nonfinite JSON")


class ApiBoundary:
    def __init__(self, app, max_bytes=256 * 1024, max_depth=32, max_nodes=8192):
        self.app, self.max_bytes = app, max_bytes
        self.max_depth, self.max_nodes = max_depth, max_nodes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        response_started = False

        async def safe_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message = {**message, "headers": [
                    (key, value) for key, value in message["headers"] if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]}
            await send(message)

        async def reject(status, code):
            await JSONResponse(status_code=status, content={"detail": {
                "code": code, "message": "请求内容过大或格式无效，请检查后重试。"
            }})(scope, receive, safe_send)

        upload = scope["method"] == "POST" and scope["path"] == PARSE_PATH
        if upload:
            state = scope.setdefault("state", {})
            request_id = state.setdefault("parse_request_id", uuid4().hex)
            headers = dict(scope["headers"])
            try:
                length = int(headers.get(b"content-length", b"0"))
                if length < 0:
                    raise ValueError()
                if length > BODY_BYTES:
                    raise DocumentError("REQUEST_TOO_LARGE", status=413)
                if headers.get(b"content-encoding", b"identity").lower() != b"identity":
                    raise DocumentError("INVALID_UPLOAD", status=400)
                media, options = parse_options_header(headers.get(b"content-type", b""))
                boundary = options.get(b"boundary", b"")
                if media != b"multipart/form-data" or not 1 <= len(boundary) <= 70 or b"\r" in boundary or b"\n" in boundary:
                    raise DocumentError("INVALID_UPLOAD", status=400)
            except (ValueError, DocumentError) as exc:
                error = exc if isinstance(exc, DocumentError) else DocumentError("INVALID_UPLOAD", status=400)
                response_headers = {"Connection": "close"} if scope.get("http_version") == "1.1" else {}
                return await JSONResponse(error_body(error, request_id), status_code=error.status, headers=response_headers)(scope, receive, safe_send)
            upstream, read_bytes, tail = receive, 0, b""
            closing = b"--" + boundary + b"--"

            async def bounded_receive():
                nonlocal read_bytes, tail
                message = await upstream()
                if message["type"] == "http.request":
                    read_bytes += len(message.get("body", b""))
                    if read_bytes > BODY_BYTES:
                        raise DocumentError("REQUEST_TOO_LARGE", status=413)
                    tail_size = len(closing) + 4
                    tail = (tail + message.get("body", b"")[-tail_size:])[-tail_size:]
                    if not message.get("more_body", False) and not tail.rstrip(b"\r\n").endswith(closing):
                        # Raise while the form parser owns its partial spools, so
                        # its BaseException cleanup also covers truncated bodies.
                        raise DocumentError("INVALID_UPLOAD", status=400)
                return message

            receive = bounded_receive
        elif scope["method"] in {"POST", "PUT", "PATCH"}:
            headers = dict(scope["headers"])
            try:
                if int(headers.get(b"content-length", b"0")) > self.max_bytes:
                    return await reject(413, "REQUEST_TOO_LARGE")
            except ValueError:
                return await reject(422, "INVALID_JSON")
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.max_bytes:
                    return await reject(413, "REQUEST_TOO_LARGE")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            content_type = headers.get(b"content-type", b"").decode("latin1").lower()
            if body and (not content_type or "json" in content_type):
                try:
                    payload = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
                    pending, count = [(payload, 1)], 0
                    while pending:
                        value, depth = pending.pop()
                        count += 1
                        if depth > self.max_depth or count > self.max_nodes:
                            return await reject(413, "JSON_COMPLEXITY_LIMIT")
                        if isinstance(value, dict):
                            pending.extend((item, depth + 1) for item in value.values())
                        elif isinstance(value, list):
                            pending.extend((item, depth + 1) for item in value)
                except (ValueError, UnicodeError, RecursionError):
                    return await reject(422, "INVALID_JSON")
            delivered, upstream = False, receive

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await upstream()

            receive = replay
        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            # Starlette's outer ServerErrorMiddleware re-raises even after an
            # exception handler has returned a safe response. Contain here so
            # Uvicorn cannot log an untrusted exception/Pydantic input string.
            if response_started:
                raise RuntimeError("API response failed after headers") from None
            await JSONResponse(status_code=500, content={"detail": {
                "code": "INTERNAL_ERROR", "message": "服务暂时不可用，请保留原请求编号重试。"
            }})(scope, receive, safe_send)
