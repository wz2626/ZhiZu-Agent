"""Single-process, in-memory sessions; share one service for its lifetime.

Each session has its own lock and detached state snapshots. A restart clears
all sessions. No review module or external model is involved.
"""

from dataclasses import dataclass, field
from copy import deepcopy
from threading import Lock
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from backend.app.schemas.negotiation import MAX_ROUNDS, NegotiationState, NegotiationTraceEvent, normalize_scenario
from backend.app.core.privacy import redact_pii
from backend.app.services.negotiation_graph import negotiation_graph
from backend.app.services.scoring import ScoringRule, scenario_scoring_rules
from backend.app.services.negotiation_trace import GRAPH_FAILURE, public_feedback, trace_collector
from backend.app.schemas.knowledge import LawId
from pydantic import TypeAdapter


class NegotiationGraph(Protocol):
    def invoke(self, state: dict) -> dict: ...


class NegotiationConflict(ValueError):
    pass


@dataclass
class _Session:
    state: NegotiationState
    lock: object = field(default_factory=Lock)
    requests: dict[str, tuple[str, NegotiationState]] = field(default_factory=dict)


class NegotiationService:
    def __init__(
        self, graph: NegotiationGraph | None = None, *,
        scoring_rules: dict[str, ScoringRule] | None = None,
        available_evidence_ids: tuple[str, ...] = (),
        public_api: bool = False,
    ) -> None:
        self._graph = graph if graph is not None else negotiation_graph
        self._scoring_rules = deepcopy(scoring_rules)
        self._public_api = public_api
        self._available_evidence_ids = TypeAdapter(list[LawId]).validate_python(
            list(available_evidence_ids), strict=True,
        )
        self._sessions: dict[str, _Session] = {}
        self._registry_lock = Lock()

    def _session(self, session_id: str, scenario: str | None = None) -> _Session:
        scenario = normalize_scenario(scenario) if scenario is not None else None
        initial = NegotiationState(
            session_id=session_id, scenario=scenario or "deposit",
            scoring_rules=deepcopy(self._scoring_rules) if self._scoring_rules is not None else scenario_scoring_rules(scenario or "deposit"),
            available_evidence_ids=self._available_evidence_ids.copy(),
        )
        with self._registry_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _Session(initial)
            elif scenario is not None and self._sessions[session_id].state.scenario != scenario:
                raise NegotiationConflict("session_id already used for different scenario")
            return self._sessions[session_id]

    def get_session(self, session_id: str) -> NegotiationState:
        """Read a detached snapshot, creating an empty session if necessary."""
        session = self._session(session_id)
        with session.lock:
            return session.state.model_copy(deep=True)

    def negotiate(
        self, session_id: str, user_input: str, *, request_id: str | None = None,
        scenario: str | None = None,
    ) -> NegotiationState:
        """Run at most one committed round; reuse request_id for safe retries."""
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input must contain text")
        user_input = redact_pii(user_input)
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
            raise ValueError("request_id must contain text")
        request_id = request_id if request_id is not None else uuid4().hex
        session = self._session(session_id, scenario)
        with session.lock:
            if request_id in session.requests:
                previous_input, response = session.requests[request_id]
                if previous_input != user_input:
                    raise NegotiationConflict("request_id already used for different input")
                return response.model_copy(deep=True, update={"replayed": self._public_api})
            if session.state.round_count >= MAX_ROUNDS:
                if self._public_api:
                    result = session.state.model_copy(deep=True, update={"request_id": request_id, "trace": [], "replayed": False})
                    session.requests[request_id] = (user_input, result.model_copy(deep=True))
                    return result
                return session.state.model_copy(deep=True)

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
            token = trace_collector.set(collected)
            started = perf_counter()
            try:
                result = NegotiationState.model_validate(self._graph.invoke(working.model_dump()))
                if result.session_id != session_id or result.scenario != working.scenario:
                    raise ValueError("graph returned a different session_id or scenario")
                if result.status in {"success", "completed"} and result.round_count != session.state.round_count + 1:
                    raise ValueError("graph must commit exactly one round")
            except Exception:
                if not self._public_api:
                    raise
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
            if result.status in {"success", "completed"}:
                session.state = result.model_copy(deep=True)
            if self._public_api or result.status in {"success", "completed"}:
                session.requests[request_id] = (user_input, result.model_copy(deep=True))
            return result.model_copy(deep=True)
