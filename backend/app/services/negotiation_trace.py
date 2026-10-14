"""Per-invocation trace collection, including events before graph exceptions."""

from contextvars import ContextVar
from time import perf_counter

from backend.app.schemas.negotiation import MAX_RETRIES, NegotiationTraceEvent

trace_collector: ContextVar[list[NegotiationTraceEvent] | None] = ContextVar("negotiation_trace", default=None)
GRAPH_FAILURE = "谈判执行异常，未提交本轮，请人工复核。"
CRITIC_OK = "候选结构、明确确认、规则边界与引用身份校验通过。"
SAFE_FEEDBACK = {
    GRAPH_FAILURE, CRITIC_OK,
    "候选条件或法条引用结构校验失败。",
    "候选条件尚未得到模拟房东明确确认。", "候选法条引用重复。",
    "候选法条不属于本次已核验的证据集合。", "候选法条与模拟房东回复不一致。",
    "候选数值无效或碰撞协商底线。", "候选数值未在模拟房东回复中明确确认。",
    "候选条件缺少适用规则或明确的安排确认。", "候选条件遗漏模拟房东已确认的数值。",
    "候选回复或条件含未脱敏信息。",
}


def public_feedback(errors):
    return [item if isinstance(item, str) and item in SAFE_FEEDBACK else GRAPH_FAILURE for item in errors]


def measured_node(name, node):
    def run(state):
        started = perf_counter()
        feedback, status = [], "completed"
        attempt = 0 if name == "completed" else state.retry_count + 1
        try:
            update = node(state)
            if name == "critic":
                failed = update.get("status") == "needs_review"
                status = ("retry" if state.retry_count < MAX_RETRIES else "needs_review") if failed else "completed"
                feedback = public_feedback(update.get("errors", [])) if failed else [CRITIC_OK]
            elif name == "retry":
                status, attempt = "retry", update["retry_count"] + 1
        except Exception:
            status, feedback = "failed", [GRAPH_FAILURE]
            raise
        finally:
            event = NegotiationTraceEvent(
                sequence=len(state.trace) + 1, node=name, attempt=attempt, status=status,
                duration_ms=max(0.0, perf_counter() - started) * 1000,
                feedback=feedback,
                evidence_ids=list(dict.fromkeys(
                    item for item in state.evidence_ids if item in state.available_evidence_ids
                )),
            )
            collector = trace_collector.get()
            if collector is not None:
                collector.append(event)
        return {**update, "trace": [*state.trace, event]}
    return run
