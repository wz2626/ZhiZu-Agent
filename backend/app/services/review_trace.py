"""Public review diagnostics contain only measured events and trusted feedback."""

from time import perf_counter
from typing import Literal

from backend.app.schemas.review import ReviewFailureCode, ReviewTraceEvent

FAILURE_MESSAGES = {
    ReviewFailureCode.CHAT_NOT_CONFIGURED: "未配置有效聊天密钥，未执行真实审查。",
    ReviewFailureCode.CHAT_INIT_FAILED: "聊天客户端初始化失败，未执行真实审查。",
    ReviewFailureCode.KB_NOT_READY: "法条知识库未就绪或校验失败，请检查匹配配置并完成入库。",
    ReviewFailureCode.UPSTREAM_EMBEDDING_ERROR: "云端向量服务调用失败，已停止审查。",
    ReviewFailureCode.RETRIEVAL_FAILED: "法条检索执行失败，已停止审查。",
    ReviewFailureCode.NO_EVIDENCE: "未检索到可用法条证据，已停止审查。",
    ReviewFailureCode.CHAT_TIMEOUT: "聊天服务调用超时，已停止生成。",
    ReviewFailureCode.CHAT_CALL_FAILED: "聊天服务调用失败，已停止生成。",
    ReviewFailureCode.VALIDATION_FAILED: "达到最多3次生成，仍未通过校验，需要人工复核。",
    ReviewFailureCode.GRAPH_EXECUTION_FAILED: "审查图执行异常，已停止审查，需要人工复核。",
}

_VALIDATION_FEEDBACK = {
    "non-finite constants are not valid JSON", "duplicate JSON key",
    "review output must be JSON text", "review output must be a JSON array",
    "review array entries must be objects", "evidence_ids must be an array of strings",
    "review output must contain at least one finding", "duplicate clause ID",
    "original clause is not a substring of the masked contract",
    "review output contains unmasked sensitive numbers", "HIGH finding has no retrieved evidence",
    "JSON 解析失败：必须输出一个完整的 JSON 数组。",
    "JSON 字段结构校验失败。", "JSON 字段结构校验失败",
    "JSON 结构校验失败：请核对字段类型和嵌套结构。",
    "校验反馈不可安全展示，请人工复核。",
    *FAILURE_MESSAGES.values(),
}
_FIELDS = {"clause_id", "original_clause", "risk_level", "explanation", "evidence_ids", "negotiation_tip"}


def public_feedback(errors: list[str]) -> list[str]:
    """Fail closed if a future node accidentally hands us untrusted diagnostics."""
    safe = []
    for error in errors:
        if isinstance(error, str) and error in _VALIDATION_FEEDBACK:
            safe.append(error)
        elif isinstance(error, str) and error.startswith("JSON 字段结构校验失败：") and set(
            error.removeprefix("JSON 字段结构校验失败：").split(", ")
        ) <= _FIELDS:
            safe.append(error)
        else:
            safe.append("校验反馈不可安全展示，请人工复核。")
    return safe


def append_trace(
    trace: list[ReviewTraceEvent], *,
    node: Literal["configuration", "retrieval", "drafting", "critic", "mock", "graph"],
    attempt: int, status: Literal["completed", "failed", "retry", "needs_review"],
    started: float, evidence_ids: list[str] | None = None,
    feedback: list[str] | None = None,
) -> ReviewTraceEvent:
    event = ReviewTraceEvent(
        sequence=len(trace) + 1, node=node, attempt=attempt, status=status,
        duration_ms=round(max(0.0, perf_counter() - started) * 1000, 3),
        evidence_ids=list(evidence_ids or []), feedback=public_feedback(feedback or []),
    )
    trace.append(event)
    return event
