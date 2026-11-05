"""One external model request, no history, receipts, retries or embeddings."""

import os
from urllib.parse import urlparse
import httpx
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from backend.app.core.config import get_settings, has_real_key
from backend.app.services.model_gateway import CloudTransport, invoke_model, remaining_timeout, execution_deadline, check_deadline
from backend.app.services.operation_store import OperationExpired
from backend.app.services.quote_evidence import evidence_pack
from backend.app.services.quote_prompt import quote_messages
from backend.app.services.quote_output_guard import validate_quote, UnsafeReplyError, safe_reply_hints
from backend.app.schemas.quote_analysis import QuoteCard, QuoteResponse, PublicGround, validate_state_binding


class QuoteFailure(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


class QuoteAnalysisService:
    def __init__(self, *, llm=None, settings=None):
        self.llm, self.settings = llm, settings

    def analyze(self, request):
        # Shares the existing global executor's capacity; a shorter local budget
        # does not release the worker/client before the actual work ends.
        with execution_deadline(45):
            return self._analyze(request)

    def _analyze(self, request):
        try:
            sources = evidence_pack(request)
        except (OSError, ValueError, TypeError, KeyError, ValidationError):
            raise QuoteFailure(503, "KNOWLEDGE_UNAVAILABLE", "本地依据暂不可用，请保留输入后重试。") from None
        settings = self.settings or get_settings()
        client = None
        try:
            llm = self.llm
            if llm is None:
                if not has_real_key(settings.chat_api_key):
                    raise QuoteFailure(503, "MODEL_UNAVAILABLE", "云端模型尚未配置，请保留输入。")
                client = httpx.Client(timeout=remaining_timeout(min(settings.chat_timeout_seconds, 30)), transport=CloudTransport())
                provider_options = {}
                if urlparse(settings.chat_base_url).hostname == "api.deepseek.com":
                    provider_options["extra_body"] = {"thinking": {"type": "disabled"}}
                llm = ChatOpenAI(base_url=settings.chat_base_url,
                    model=os.getenv("QUOTE_CHAT_MODEL", settings.chat_model), api_key=settings.chat_api_key,
                    temperature=0.2, max_tokens=3072, max_retries=0, use_responses_api=False,
                    model_kwargs={"response_format": {"type": "json_object"}},
                    timeout=remaining_timeout(min(settings.chat_timeout_seconds, 30)), http_client=client,
                    **provider_options)
            try:
                # Up to 2500 one-character natural paragraphs are legal within
                # a 5000-character contract. Their source IDs add envelope text;
                # the caller cannot change this bounded admission allowance.
                result = invoke_model(llm, quote_messages(request, sources), max_chars=160000)
            except OperationExpired:
                raise
            except (TimeoutError, httpx.TimeoutException):
                raise QuoteFailure(504, "MODEL_TIMEOUT", "等待模型超时，请保留内容；如重新生成可能再次计费。") from None
            except Exception as error:
                # Do not expose upstream payloads, keys or arbitrary exception text.
                from openai import APITimeoutError
                if isinstance(error, APITimeoutError):
                    raise QuoteFailure(504, "MODEL_TIMEOUT", "等待模型超时，请保留内容后决定是否重新生成。") from None
                raise QuoteFailure(503, "MODEL_UNAVAILABLE", "模型服务暂不可用，请保留内容后重试。") from None
            try:
                if getattr(result, "response_metadata", {}).get("finish_reason", "stop") != "stop":
                    raise ValueError("incomplete generation")
                draft = validate_quote(result.content, request, sources)
                validate_state_binding(draft.status, draft.breakdown.assessment if draft.breakdown else None,
                                       draft.clarification_questions)
                card = None if draft.status == "out_of_scope" else QuoteCard(
                    breakdown=draft.breakdown, replies=safe_reply_hints(draft.replies),
                    clarification_questions=draft.clarification_questions,
                    grounds=[PublicGround(**sources[g.source_id].model_dump(), application=g.application) for g in draft.grounds])
                response = QuoteResponse(request_id=request.request_id, status=draft.status, card=card)
                response.model_dump_json()  # Preflight before exposing any result.
                check_deadline()
                return response
            except UnsafeReplyError:
                raise QuoteFailure(502, "MODEL_OUTPUT_UNSAFE", "生成回复触发内容安全规则，已拦截。请核对原话与诉求后再生成。") from None
            except (ValueError, TypeError, AttributeError, RecursionError):
                raise QuoteFailure(502, "MODEL_OUTPUT_INVALID", "本次结果未通过检查，原输入与旧结果保留。可补充信息后重新生成。") from None
        finally:
            if client is not None:
                client.close()


quote_analysis_service = QuoteAnalysisService()
