"""Single-process, in-memory sessions; share one service for its lifetime.

Each session has its own lock and detached state snapshots. A restart clears
all sessions. No review module or external model is involved.
"""

from dataclasses import dataclass, field
from copy import deepcopy
from threading import Lock
from time import perf_counter, monotonic
from typing import Protocol
from uuid import uuid4

from backend.app.schemas.negotiation import (
    MAX_ROUNDS, NegotiationMessage, NegotiationState, NegotiationResponse, NegotiationTraceEvent, NegotiationTurnEffect, normalize_scenario,
)
from backend.app.core.privacy import redact_pii
from backend.app.services.negotiation_graph import negotiation_graph, _extract_landlord_terms, _contains_sensitive_numbers
from backend.app.services.scoring import ScoringRule, scenario_scoring_rules, calculate_score
from backend.app.services.negotiation_trace import GRAPH_FAILURE, public_feedback, trace_collector
from backend.app.services.negotiation_effect import describe_turn
from backend.app.schemas.knowledge import LawId
from pydantic import TypeAdapter


class NegotiationGraph(Protocol):
    def invoke(self, state: dict) -> dict: ...


class NegotiationConflict(ValueError):
    pass


class NegotiationRoundConflict(NegotiationConflict):
    pass


class NegotiationSessionInvalid(NegotiationConflict):
    pass


class NegotiationCapacityExceeded(ValueError):
    pass


class CommitRejected(ValueError):
    """Untrusted graph output; neither formal state nor receipts may publish."""


@dataclass(frozen=True)
class NegotiationTurnResult:
    """One request's frozen comparison and detached execution snapshot."""

    state: NegotiationState
    turn_effect: NegotiationTurnEffect
    public_response: NegotiationResponse | None = None

    def detached(self, *, replayed: bool | None = None) -> "NegotiationTurnResult":
        updates = {} if replayed is None else {"replayed": replayed}
        return NegotiationTurnResult(
            self.state.model_copy(deep=True, update=updates),
            self.turn_effect.model_copy(deep=True),
            None if self.public_response is None else self.public_response.model_copy(deep=True, update=updates),
        )


@dataclass
class _Session:
    state: NegotiationState
    lock: object = field(default_factory=Lock)
    requests: dict[str, tuple[str, NegotiationTurnResult]] = field(default_factory=dict)
    last_used: float = 0.0
    pins: int = 0


class NegotiationService:
    def __init__(
        self, graph: NegotiationGraph | None = None, *,
        scoring_rules: dict[str, ScoringRule] | None = None,
        available_evidence_ids: tuple[str, ...] = (),
        public_api: bool = False,
        capacity: int = 1000, identity_capacity: int = 10000,
        request_capacity: int = 64, ttl_seconds: float = 3600, clock=monotonic,
    ) -> None:
        self._graph = graph if graph is not None else negotiation_graph
        self._scoring_rules = deepcopy(scoring_rules)
        self._public_api = public_api
        self._available_evidence_ids = TypeAdapter(list[LawId]).validate_python(
            list(available_evidence_ids), strict=True,
        )
        self._sessions: dict[str, _Session] = {}
        self._registry_lock = Lock()
        self.practice_epoch = uuid4().hex
        self._capacity, self._identity_capacity = capacity, identity_capacity
        self._request_capacity, self._ttl, self._clock = request_capacity, ttl_seconds, clock
        self._expired = set()
        if min(capacity, identity_capacity, request_capacity, ttl_seconds) <= 0:
            raise ValueError("session bounds must be positive")

    def _initial(self, session_id, scenario=None):
        scenario = normalize_scenario(scenario) if scenario is not None else None
        return NegotiationState(
            session_id=session_id, scenario=scenario or "deposit",
            scoring_rules=deepcopy(self._scoring_rules) if self._scoring_rules is not None else scenario_scoring_rules(scenario or "deposit"),
            available_evidence_ids=self._available_evidence_ids.copy(),
        )
    def _session(self, session_id: str, scenario: str | None = None, expected_round=None) -> _Session:
        scenario = normalize_scenario(scenario) if scenario is not None else None
        with self._registry_lock:
            now = self._clock()
            for key, value in list(self._sessions.items()):
                if not value.pins and now - value.last_used >= self._ttl:
                    del self._sessions[key]
                    self._expired.add(key)
            if session_id in self._expired:
                raise NegotiationSessionInvalid("session expired")
            if session_id not in self._sessions:
                if expected_round not in (None, 0):
                    raise NegotiationRoundConflict("new session must start at round zero")
                if len(self._sessions) >= self._capacity or len(self._sessions) + len(self._expired) >= self._identity_capacity:
                    raise NegotiationCapacityExceeded("session capacity exceeded")
                self._sessions[session_id] = _Session(self._initial(session_id, scenario), last_used=now)
            elif scenario is not None and self._sessions[session_id].state.scenario != scenario:
                raise NegotiationConflict("session_id already used for different scenario")
            session = self._sessions[session_id]
            session.pins += 1
            return session

    def _release(self, session):
        with self._registry_lock:
            session.pins -= 1
            session.last_used = self._clock()

    def get_session(self, session_id: str) -> NegotiationState:
        """Read a detached snapshot; absent IDs do not allocate storage."""
        with self._registry_lock:
            session = self._sessions.get(session_id)
            if session is not None and not session.pins and self._clock() - session.last_used >= self._ttl:
                del self._sessions[session_id]
                self._expired.add(session_id)
                session = None
            if session is None:
                return self._initial(session_id)
            session.pins += 1
        try:
            with session.lock:
                return session.state.model_copy(deep=True)
        finally:
            self._release(session)

    def negotiate(
        self, session_id: str, user_input: str, *, request_id: str | None = None,
        scenario: str | None = None,
    ) -> NegotiationState:
        """Preserve the existing Python snapshot interface."""
        return self.negotiate_with_effect(
            session_id, user_input, request_id=request_id, scenario=scenario,
        ).state

    def negotiate_with_effect(
        self, session_id: str, user_input: str, *, request_id: str | None = None,
        scenario: str | None = None,
        expected_round: int | None = None, practice_epoch: str | None = None,
        response_validator=None,
    ) -> NegotiationTurnResult:
        """Commit at most one turn and cache its original comparison atomically."""
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input must contain text")
        user_input = redact_pii(user_input)
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
            raise ValueError("request_id must contain text")
        request_id = request_id if request_id is not None else uuid4().hex
        if practice_epoch is not None and practice_epoch != self.practice_epoch:
            raise NegotiationSessionInvalid("practice service restarted")
        session = self._session(session_id, scenario, expected_round)
        try:
            return self._execute_turn(session, session_id, user_input, request_id, expected_round, response_validator)
        finally:
            self._release(session)

    @staticmethod
    def _validated(response, validator):
        if validator is None or response.public_response is not None:
            return response
        public = NegotiationResponse.model_validate(validator(response).model_dump())
        public.model_dump_json()  # serialization failures must precede publication
        return NegotiationTurnResult(response.state, response.turn_effect, public)

    def _execute_turn(self, session, session_id, user_input, request_id, expected_round, response_validator):
        with session.lock:
            if request_id in session.requests:
                previous_input, response = session.requests[request_id]
                if previous_input != user_input:
                    raise NegotiationConflict("request_id already used for different input")
                return self._validated(response.detached(replayed=self._public_api), response_validator)
            if expected_round is not None and expected_round != session.state.round_count:
                raise NegotiationRoundConflict("practice baseline conflict")
            if len(session.requests) >= self._request_capacity:
                raise NegotiationCapacityExceeded("request capacity exceeded")
            if session.state.round_count >= MAX_ROUNDS:
                effect = describe_turn(session.state, session.state, round_limit=True)
                if self._public_api:
                    result = session.state.model_copy(deep=True, update={"request_id": request_id, "trace": [], "replayed": False})
                    response = self._validated(NegotiationTurnResult(result, effect), response_validator)
                    stored, returned = response.detached(), response.detached()
                    session.requests = {**session.requests, request_id: (user_input, stored)}
                    return returned
                return NegotiationTurnResult(session.state.model_copy(deep=True), effect)

            # The graph receives no mutable references to the canonical session.
            working = session.state.model_copy(deep=True)
            working.request_id = request_id
            working.user_input = user_input
            working.candidate_terms = {}
            working.evidence_ids = []
            working.candidate_score = None
            working.coach_advice = ""
            working.landlord_response = ""
            working.landlord_confirmed = False
            working.retry_count = 0
            working.errors = []
            working.status = "active"
            working.trace = []
            working.replayed = False
            collected: list[NegotiationTraceEvent] = []
            effect = None
            commit_rejected = False
            token = trace_collector.set(collected)
            started = perf_counter()
            try:
                result = NegotiationState.model_validate(self._graph.invoke(working.model_dump()))
                if result.session_id != session_id or result.scenario != working.scenario or result.request_id != request_id or result.user_input != user_input:
                    raise ValueError("graph returned a different owner or operation")
                if result.status in {"success", "completed"} and result.round_count != session.state.round_count + 1:
                    raise ValueError("graph must commit exactly one round")
                if self._public_api and result.status in {"success", "completed"}:
                    self._verify_commit(session.state, result)
                effect = describe_turn(session.state, result)
            except Exception as error:
                if not self._public_api:
                    raise
                commit_rejected = isinstance(error, CommitRejected)
                if not collected or collected[-1].status != "failed":
                    collected.append(NegotiationTraceEvent(
                        sequence=len(collected) + 1, node="graph", attempt=0, status="failed",
                        duration_ms=max(0.0, perf_counter() - started) * 1000, feedback=[GRAPH_FAILURE],
                    ))
                result = working.model_copy(deep=True, update={
                    "status": "needs_review", "errors": [GRAPH_FAILURE], "trace": collected,
                    "retry_count": max((max(0, event.attempt - 1) for event in collected), default=0),
                })
            finally:
                trace_collector.reset(token)
            if self._public_api and result.status == "needs_review":
                # Discard rejected drafts before storing an idempotent failure.
                result = result.model_copy(deep=True, update={
                    "confirmed_terms": deepcopy(session.state.confirmed_terms),
                    "confirmed_evidence_ids": session.state.confirmed_evidence_ids.copy(),
                    "round_count": session.state.round_count, "history": deepcopy(session.state.history),
                    "trial_score": session.state.trial_score, "score_explanation": session.state.score_explanation,
                    "coach_advice": "", "landlord_response": "", "candidate_terms": {},
                    "candidate_score": None, "evidence_ids": [], "landlord_confirmed": False,
                    "errors": public_feedback(result.errors),
                })
            if effect is None:
                effect = describe_turn(session.state, result)
            response = self._validated(NegotiationTurnResult(result, effect), response_validator)
            next_state = result.model_copy(deep=True) if result.status in {"success", "completed"} else session.state
            stored, returned = response.detached(), response.detached()
            requests = session.requests
            if not commit_rejected and (self._public_api or result.status in {"success", "completed"}):
                requests = {**requests, request_id: (user_input, stored)}
            session.state, session.requests = next_state, requests
            return returned

    @staticmethod
    def _verify_commit(before, result):
        if _contains_sensitive_numbers([result.coach_advice, result.landlord_response, result.confirmed_terms]):
            raise CommitRejected("graph output contains unsafe text")
        if result.history != [*before.history,
            NegotiationMessage(role="user", content=result.user_input),
            NegotiationMessage(role="tenant_coach", content=result.coach_advice),
            NegotiationMessage(role="landlord", content=result.landlord_response)]:
            raise CommitRejected("graph altered committed history")
        if result.scoring_rules != before.scoring_rules or result.available_evidence_ids != before.available_evidence_ids:
            raise CommitRejected("graph altered protected scoring or evidence")
        extracted = _extract_landlord_terms(result.landlord_response, before.scenario)
        prefix = "【模拟房东】确认本轮安排："
        if result.landlord_response.startswith(prefix):
            text = result.landlord_response[len(prefix):]
            if not text.strip():
                raise CommitRejected("empty arrangement")
            extracted = {f"round_{before.round_count + 1}": {"arrangement": [text]}}
        expected = {**before.confirmed_terms, **extracted}
        if result.confirmed_terms != expected:
            raise CommitRejected("graph terms do not match confirmed response")
        if any(not before.scoring_rules[key].accepts(value) for key, value in extracted.items() if key in before.scoring_rules):
            raise CommitRejected("graph terms outside trusted rules")
        if result.trial_score != calculate_score(expected, before.scoring_rules):
            raise CommitRejected("graph score does not match trusted rules")
        if not set(result.confirmed_evidence_ids).issubset(before.available_evidence_ids):
            raise CommitRejected("graph introduced untrusted evidence")
