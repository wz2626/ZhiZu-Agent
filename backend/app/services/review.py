"""RAG preparation and legacy API adapter for the bounded review graph."""

import logging
import math
import re
from typing import Protocol
from time import perf_counter

import httpx
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from backend.app.core.config import Settings, get_settings, has_real_key
from backend.app.schemas.knowledge import EvidenceItem
from backend.app.schemas.review import (
    ReviewClauseResult, ReviewDetailedResponse, ReviewFailureCode, ReviewRequest,
    ReviewResponse, ReviewTraceEvent, RiskLevel,
)
from backend.app.services.graph import review_graph
from backend.app.services.review_input_guard import classify_review_input
from backend.app.services.review_trace import FAILURE_MESSAGES, append_trace, public_feedback
from backend.app.services.vector_store import (
    STORAGE_ERRORS, LawVectorStoreService, load_authoritative_laws, mask_sensitive_text,
)

logger = logging.getLogger(__name__)


class ReviewLLM(Protocol):
    def invoke(self, messages: list[BaseMessage]) -> BaseMessage: ...


class ContractReviewService:
    def __init__(
        self,
        vector_store: LawVectorStoreService | None = None,
        llm: ReviewLLM | None = None,
        settings: Settings | None = None,
        *,
        defer_chat_init: bool = False,
    ) -> None:
        self.settings = settings if settings is not None else get_settings()
        self.vector_store = vector_store
        self.llm = llm
        self.mock_mode = not has_real_key(self.settings.chat_api_key)
        self._chat_initialization_failed = False
        self._owns_vector_store = False
        self._owns_llm = False
        self._http_client: httpx.Client | None = None
        if not defer_chat_init:
            self._initialize_chat_if_needed()

    def _initialize_chat_if_needed(self) -> None:
        if not self.mock_mode and self.llm is None:
            try:
                # LangChain caches its default transport. A request-scoped
                # service must own its transport so close() cannot poison the
                # next request or another service that is still using it.
                self._http_client = httpx.Client(timeout=self.settings.chat_timeout_seconds)
                self.llm = ChatOpenAI(
                    base_url=self.settings.chat_base_url,
                    model=self.settings.chat_model,
                    api_key=self.settings.chat_api_key,
                    temperature=0.1,
                    timeout=self.settings.chat_timeout_seconds,
                    max_retries=0,
                    use_responses_api=False,
                    http_client=self._http_client,
                )
                self._owns_llm = True
            except Exception as error:
                logger.warning("Review client initialization failed (%s)", type(error).__name__)
                self.mock_mode = True
                self._chat_initialization_failed = True
                self._close_http_client()

    def _close_http_client(self) -> None:
        client, self._http_client = self._http_client, None
        if client is not None:
            try:
                client.close()
            except Exception as error:
                logger.warning("Review transport cleanup failed (%s)", type(error).__name__)

    def close(self) -> None:
        if self._owns_vector_store:
            self._owns_vector_store = False
            try:
                self.vector_store.close()
            except Exception as error:
                logger.warning("Review store cleanup failed (%s)", type(error).__name__)
        if self._owns_llm:
            self._owns_llm = False
            try:
                self.llm.root_client.close()
            except Exception as error:
                logger.warning("Review chat cleanup failed (%s)", type(error).__name__)
        self._close_http_client()

    def analyze_contract(self, text: str, top_k: int = 4) -> ReviewResponse:
        request = ReviewRequest(contract_text=text, top_k=top_k)
        safe_text = mask_sensitive_text(request.contract_text)
        # Keep the legacy success/mock shape, but reject through the same local
        # guard as the detailed API before clients, retrieval or cloud calls.
        if classify_review_input(safe_text) is not None:
            return self._mock_response(safe_text)
        self._initialize_chat_if_needed()
        # An absent chat key must not depend on storage or embedding credentials.
        if self.mock_mode:
            return self._mock_response(safe_text)

        try:
            if self.vector_store is None:
                self.vector_store = LawVectorStoreService(
                    persist_directory=self.settings.chroma_path, create_if_missing=False,
                )
                self._owns_vector_store = True
            if not self.vector_store.get_status().is_ready:
                return self._mock_response(safe_text)
            evidence = self._filter_evidence(
                self.vector_store.search_evidence(safe_text, top_k=request.top_k), request.top_k,
            )
        except Exception as error:
            logger.warning("Review retrieval failed (%s)", type(error).__name__)
            return self._mock_response(safe_text)

        if not evidence:
            return self._mock_response(safe_text)
        try:
            state = review_graph.invoke({
                "contract_text": safe_text, "evidence_list": evidence,
                "current_draft": None, "errors": [], "retry_count": 0,
                "final_results": [], "status": "drafting", "messages": [],
                "retry_pending": False,
            }, context={"llm": self.llm})
            if state["status"] == "success":
                results = state["final_results"]
                return ReviewResponse(
                    status="success", results=results,
                    total_risks=sum(item.risk_level != RiskLevel.NONE for item in results),
                )
        except Exception as error:
            logger.warning("Review graph execution failed (%s)", type(error).__name__)
        return self._mock_response(safe_text)

    def analyze_contract_detailed(self, text: str, top_k: int = 4) -> ReviewDetailedResponse:
        request = ReviewRequest(contract_text=text, top_k=top_k)
        safe_text = mask_sensitive_text(request.contract_text)
        trace: list[ReviewTraceEvent] = []
        started = perf_counter()
        guard_code = classify_review_input(safe_text)
        if guard_code is not None:
            append_trace(trace, node="input_guard", attempt=0, status="needs_review",
                         started=started, feedback=[FAILURE_MESSAGES[guard_code]])
            return self._detailed_failure(guard_code, trace)

        started = perf_counter()
        self._initialize_chat_if_needed()
        if self.mock_mode:
            code = (ReviewFailureCode.CHAT_INIT_FAILED if self._chat_initialization_failed
                    else ReviewFailureCode.CHAT_NOT_CONFIGURED)
            append_trace(trace, node="configuration", attempt=0, status="failed",
                         started=started, feedback=[FAILURE_MESSAGES[code]])
            return self._detailed_failure(code, trace)
        append_trace(trace, node="configuration", attempt=0, status="completed", started=started)

        started = perf_counter()
        evidence: list[EvidenceItem] = []
        retrieval_code = None
        searching = False
        try:
            if self.vector_store is None:
                self.vector_store = LawVectorStoreService(
                    persist_directory=self.settings.chroma_path, create_if_missing=False,
                )
                self._owns_vector_store = True
            if not self.vector_store.get_status().is_ready:
                retrieval_code = ReviewFailureCode.KB_NOT_READY
            else:
                searching = True
                evidence = self._filter_evidence(
                    self.vector_store.search_evidence(safe_text, top_k=request.top_k), request.top_k,
                )
                if not evidence:
                    retrieval_code = ReviewFailureCode.NO_EVIDENCE
        except (ValueError, *STORAGE_ERRORS):
            retrieval_code = ReviewFailureCode.KB_NOT_READY
        except RuntimeError:
            retrieval_code = (ReviewFailureCode.UPSTREAM_EMBEDDING_ERROR if searching
                              else ReviewFailureCode.RETRIEVAL_FAILED)
        except Exception:
            retrieval_code = ReviewFailureCode.RETRIEVAL_FAILED

        append_trace(
            trace, node="retrieval", attempt=0,
            status="failed" if retrieval_code else "completed", started=started,
            evidence_ids=[item.evidence_id for item in evidence],
            feedback=[FAILURE_MESSAGES[retrieval_code]] if retrieval_code else [],
        )
        if retrieval_code:
            return self._detailed_failure(retrieval_code, trace)

        started = perf_counter()
        try:
            state = review_graph.invoke({
                "contract_text": safe_text, "evidence_list": evidence,
                "current_draft": None, "errors": [], "retry_count": 0,
                "final_results": [], "status": "drafting", "messages": [],
                "retry_pending": False, "failure_code": None, "trace": list(trace),
            }, context={"llm": self.llm, "trace": trace})
            if state["status"] == "success":
                results = state["final_results"]
                return ReviewDetailedResponse(
                    status="success", results=results,
                    total_risks=sum(item.risk_level != RiskLevel.NONE for item in results),
                    retry_count=state["retry_count"], trace=trace,
                )
            code = state.get("failure_code") or ReviewFailureCode.VALIDATION_FAILED
            return self._detailed_failure(code, trace, errors=state["errors"],
                                          retry_count=state["retry_count"])
        except Exception:
            code = ReviewFailureCode.GRAPH_EXECUTION_FAILED
            append_trace(trace, node="graph", attempt=0, status="failed", started=started,
                         evidence_ids=[item.evidence_id for item in evidence],
                         feedback=[FAILURE_MESSAGES[code]])
            retry_count = max((event.attempt - 1 for event in trace if event.node == "drafting"), default=0)
            return self._detailed_failure(code, trace, retry_count=retry_count)

    @staticmethod
    def _detailed_failure(
        code: ReviewFailureCode, trace: list[ReviewTraceEvent],
        *, errors: list[str] | None = None, retry_count: int = 0,
    ) -> ReviewDetailedResponse:
        return ReviewDetailedResponse(
            status="needs_review", results=[], total_risks=0, failure_code=code,
            reason=FAILURE_MESSAGES[code], errors=public_feedback(errors or [FAILURE_MESSAGES[code]]),
            retry_count=retry_count, trace=trace,
        )

    @staticmethod
    def _filter_evidence(items: list[EvidenceItem], top_k: int) -> list[EvidenceItem]:
        authoritative = {law.law_id: law.content for law in load_authoritative_laws()}
        filtered = []
        seen = set()
        for item in items:
            if (
                type(item.score) not in (int, float)
                or not math.isfinite(item.score)
                or not 0.0 < item.score <= 1.0
                or item.evidence_id not in authoritative
                or item.content != authoritative[item.evidence_id]
                or item.evidence_id in seen
            ):
                continue
            filtered.append(item)
            seen.add(item.evidence_id)
            if len(filtered) == top_k:
                break
        return filtered

    @staticmethod
    def _mock_response(text: str) -> ReviewResponse:
        clauses = [part for part in re.findall(r"[^。！？；\n]+[。！？；]?", text) if part.strip()]
        if len(clauses) < 2:
            midpoint = len(text) // 2
            clauses = [text[:midpoint], text[midpoint:]]
            # A trailing/leading whitespace-only fragment is not a useful clause.
            if not all(part.strip() for part in clauses):
                clauses = [text, text]
        risk_index = next((
            index for index, clause in enumerate(clauses)
            if any(term in clause for term in ("押金不退", "不退押金", "擅自转租", "不得退还"))
        ), 0)
        safe_index = next(index for index in range(len(clauses)) if index != risk_index)
        return ReviewResponse(status="mock", total_risks=1, results=[
            ReviewClauseResult(
                clause_id="C-01", original_clause=clauses[risk_index], risk_level=RiskLevel.HIGH,
                explanation="Mock 演示风险，非真实法律审查结论。请核实押金扣减条件和转租授权；"
                "本章没有押金返还的直接规定，需补充合同约定及其他适用依据。",
                evidence_ids=[],
                negotiation_tip="演示建议：协商明确押金扣减证据、返还安排和转租书面同意条件。",
            ),
            ReviewClauseResult(
                clause_id="C-02", original_clause=clauses[safe_index], risk_level=RiskLevel.NONE,
                explanation="Mock 无风险演示项，不代表实际条款已通过法律审查。",
                evidence_ids=[], negotiation_tip="",
            ),
        ])
