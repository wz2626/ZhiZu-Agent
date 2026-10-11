"""Single-process, in-memory sessions; share one service for its lifetime.

Each session has its own lock and detached state snapshots. A restart clears
all sessions. No review module or external model is involved.
"""

from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol
from uuid import uuid4

from backend.app.schemas.negotiation import MAX_ROUNDS, NegotiationState
from backend.app.services.negotiation_graph import negotiation_graph


class NegotiationGraph(Protocol):
    def invoke(self, state: dict) -> dict: ...


@dataclass
class _Session:
    state: NegotiationState
    lock: object = field(default_factory=Lock)
    requests: dict[str, tuple[str, NegotiationState]] = field(default_factory=dict)


class NegotiationService:
    def __init__(self, graph: NegotiationGraph | None = None) -> None:
        self._graph = graph if graph is not None else negotiation_graph
        self._sessions: dict[str, _Session] = {}
        self._registry_lock = Lock()

    def _session(self, session_id: str) -> _Session:
        initial = NegotiationState(session_id=session_id)
        with self._registry_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _Session(initial)
            return self._sessions[session_id]

    def get_session(self, session_id: str) -> NegotiationState:
        """Read a detached snapshot, creating an empty session if necessary."""
        session = self._session(session_id)
        with session.lock:
            return session.state.model_copy(deep=True)

    def negotiate(
        self, session_id: str, user_input: str, *, request_id: str | None = None,
    ) -> NegotiationState:
        """Run at most one committed round; reuse request_id for safe retries."""
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input must contain text")
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
            raise ValueError("request_id must contain text")
        request_id = request_id if request_id is not None else uuid4().hex
        session = self._session(session_id)
        with session.lock:
            if request_id in session.requests:
                previous_input, response = session.requests[request_id]
                if previous_input != user_input:
                    raise ValueError("request_id already used for different input")
                return response.model_copy(deep=True)
            if session.state.round_count >= MAX_ROUNDS:
                return session.state.model_copy(deep=True)

            # The graph receives no mutable references to the canonical session.
            working = session.state.model_copy(deep=True)
            working.request_id = request_id
            working.user_input = user_input
            working.candidate_terms = {}
            working.coach_advice = ""
            working.landlord_response = ""
            working.landlord_confirmed = False
            working.retry_count = 0
            working.errors = []
            working.status = "active"
            result = NegotiationState.model_validate(self._graph.invoke(working.model_dump()))
            if result.session_id != session_id:
                raise ValueError("graph returned a different session_id")
            if result.status in {"success", "completed"}:
                if result.round_count != session.state.round_count + 1:
                    raise ValueError("graph must commit exactly one round")
                session.state = result.model_copy(deep=True)
                session.requests[request_id] = (user_input, result.model_copy(deep=True))
            return result.model_copy(deep=True)
