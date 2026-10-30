"""Bounded, short-lived review capabilities for proposal drafting.

Only sanitized accepted review material is held in process memory. Possession
of the random identifier grants access in this local, account-free app.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Callable
from uuid import uuid4

from backend.app.core.privacy import redact_pii
from backend.app.schemas.review import ReviewClauseResult, ReviewEvidence


class ReviewContextMissing(ValueError):
    pass


def _redacted_clause(clause: ReviewClauseResult) -> ReviewClauseResult:
    # Mask decoded fields before serialization so escaped phone separators
    # cannot bypass the privacy boundary. Validation also detaches the lists.
    values = clause.model_dump()
    return ReviewClauseResult.model_validate({
        key: redact_pii(value) if isinstance(value, str) else value
        for key, value in values.items()
    })


@dataclass
class ReviewContext:
    context_id: str
    expires_at: float
    contract_text: str
    clauses: dict[str, ReviewClauseResult]
    evidence_by_id: dict[str, ReviewEvidence]
    lock: object = field(default_factory=Lock)
    # Values are (clause_id, masked goal, detached public response).
    requests: OrderedDict = field(default_factory=OrderedDict)


class ReviewContextStore:
    def __init__(self, *, ttl_seconds: float = 1800, capacity: int = 100,
                 clock: Callable[[], float] = monotonic) -> None:
        if ttl_seconds <= 0 or capacity < 1:
            raise ValueError("context lifetime and capacity must be positive")
        self._ttl, self._capacity, self._clock = ttl_seconds, capacity, clock
        self._contexts: OrderedDict[str, ReviewContext] = OrderedDict()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        for key in list(self._contexts):
            if self._contexts[key].expires_at <= now:
                del self._contexts[key]

    def create(self, text: str, clauses: list[ReviewClauseResult],
               evidence_by_id: dict[str, ReviewEvidence]) -> str:
        context_id = uuid4().hex
        with self._lock:
            now = self._clock()
            self._prune(now)
            while len(self._contexts) >= self._capacity:
                self._contexts.popitem(last=False)
            self._contexts[context_id] = ReviewContext(
                context_id=context_id, expires_at=now + self._ttl,
                contract_text=redact_pii(text),
                clauses={item.clause_id: _redacted_clause(item) for item in clauses},
                evidence_by_id={key: item.model_copy(deep=True) for key, item in evidence_by_id.items()},
            )
        return context_id

    def get(self, context_id: str) -> ReviewContext:
        with self._lock:
            self._prune(self._clock())
            context = self._contexts.get(context_id)
            if context is None:
                raise ReviewContextMissing("review context is missing or expired")
            self._contexts.move_to_end(context_id)
            return context


review_context_store = ReviewContextStore()
