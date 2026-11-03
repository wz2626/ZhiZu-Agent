"""Bound cloud work; a worker owns clients/capacity until it actually exits."""

import asyncio
import json
import httpx
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from threading import BoundedSemaphore
from time import monotonic

from backend.app.core.privacy import redact_pii
from backend.app.services.operation_store import OperationBusy, OperationExpired

_deadline = ContextVar("cloud_deadline", default=None)
logger = logging.getLogger(__name__)


def check_deadline():
    deadline = _deadline.get()
    if deadline is not None and monotonic() >= deadline:
        raise OperationExpired("cloud deadline exceeded")


def remaining_timeout(limit=20.0):
    check_deadline()
    deadline = _deadline.get()
    return limit if deadline is None else max(0.001, min(limit, deadline - monotonic()))


@contextmanager
def execution_deadline(seconds):
    existing = _deadline.get()
    deadline = monotonic() + seconds
    token = _deadline.set(min(existing, deadline) if existing is not None else deadline)
    try:
        check_deadline()
        yield
    finally:
        _deadline.reset(token)


def invoke_model(llm, messages):
    check_deadline()
    # Conservative character admission, not a claim of tokenizer equivalence.
    text = "".join(message.content for message in messages if isinstance(message.content, str))
    if len(text) > 48000:
        raise ValueError("unsafe or oversized model payload")
    # Payload envelope is assembled by the server. Do not treat opaque server
    # IDs as free text: a UUID can coincidentally contain a phone-shaped run.
    data = json.loads(messages[1].content)
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(item for key, item in value.items() if key not in {"question_id", "clause_id", "law_id", "evidence_ids"})
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and redact_pii(value) != value:
            raise ValueError("unsafe model text field")
    result = llm.invoke(messages)
    check_deadline()
    return result


class _BoundedStream(httpx.SyncByteStream):
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit
        self.closed = False

    def __iter__(self):
        size = 0
        try:
            for chunk in self.stream:
                check_deadline()
                size += len(chunk)
                if size > self.limit:
                    raise ValueError("cloud response exceeds byte budget")
                yield chunk
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.stream.close()


class CloudTransport(httpx.BaseTransport):
    """Bound actual response bytes, including absent/false Content-Length."""

    def __init__(self, transport=None, max_bytes=256 * 1024):
        self.transport = transport if transport is not None else httpx.HTTPTransport(retries=0)
        self.max_bytes = max_bytes

    def handle_request(self, request):
        check_deadline()
        request.headers["Accept-Encoding"] = "identity"
        response = self.transport.handle_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            response.close()
            raise ValueError("compressed cloud response is not supported")
        response.stream = _BoundedStream(response.stream, self.max_bytes)
        return response

    def close(self):
        self.transport.close()


def post_embeddings(url, *, headers, json, timeout):
    # 32 x 1024 finite values need a larger wire budget than chat JSON.
    with httpx.Client(transport=CloudTransport(max_bytes=4 * 1024 * 1024)) as client:
        return client.post(url, headers=headers, json=json, timeout=timeout)


class CloudExecutor:
    def __init__(self, *, workers=4, queue=4, queue_timeout=2.0, deadline=90.0):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="zhizu-cloud")
        self._slots = BoundedSemaphore(workers + queue)
        self._queue_timeout, self._deadline_seconds = queue_timeout, deadline

    async def run(self, call, *, cleanup=None):
        def close_resources():
            if cleanup is not None:
                try:
                    cleanup()
                except Exception as error:
                    # Cleanup must not replace a committed result or expose a
                    # raw exception in logs. Capacity is still released below.
                    logger.warning("Cloud task cleanup failed (%s)", type(error).__name__)

        if not self._slots.acquire(blocking=False):
            close_resources()
            raise OperationBusy("cloud executor full")
        accepted = monotonic()

        def work():
            if monotonic() - accepted > self._queue_timeout:
                raise OperationBusy("cloud queue deadline exceeded")
            with execution_deadline(self._deadline_seconds - (monotonic() - accepted)):
                result = call()
                check_deadline()
                return result

        def finish(_future=None):
            try:
                close_resources()
            finally:
                self._slots.release()

        try:
            future = self._pool.submit(work)
        except BaseException:
            finish()
            raise
        # Successful submit transfers ownership immediately, including queued
        # work. Future completion handles execution, pre-call expiry or cancel;
        # HTTP timeout/cancellation never closes submitted work's resources.
        future.add_done_callback(finish)
        wrapped = asyncio.wrap_future(future)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=self._deadline_seconds)
        except (asyncio.CancelledError, TimeoutError) as error:
            # HTTP loss does not cancel accepted work or discard its receipt.
            wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            if isinstance(error, TimeoutError):
                raise OperationExpired("cloud operation timed out") from None
            raise

    def close(self):
        self._pool.shutdown(wait=True)


cloud_executor = CloudExecutor()
