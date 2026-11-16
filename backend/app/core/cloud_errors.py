"""Public provider diagnostics. Never copy upstream bodies or exception messages."""

STATUS_CODES = {401: "MODEL_AUTH_FAILED", 402: "MODEL_QUOTA_EXCEEDED",
                403: "MODEL_ACCESS_DENIED", 429: "MODEL_RATE_LIMITED"}
HINTS = {
    "MODEL_SERVICE_ERROR": "暂时不可用，请稍后重试。",
    "MODEL_AUTH_FAILED": "认证失败，请检查 API Key 配置。",
    "MODEL_QUOTA_EXCEEDED": "额度不足，请检查账户余额或计费配置。",
    "MODEL_ACCESS_DENIED": "访问被拒绝，请检查账号和模型权限。",
    "MODEL_RATE_LIMITED": "请求受到限流，请稍后重试。",
}


def provider_code(error):
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int) and 500 <= status <= 599:
        return "MODEL_SERVICE_ERROR"
    return STATUS_CODES.get(status)


class EmbeddingResponseError(ValueError):
    """Invalid upstream vector, distinct from a local storage error."""


class EmbeddingRequestError(RuntimeError):
    def __init__(self, code):
        self.code = code
        self.hint = "向量服务" + HINTS[code]
        super().__init__(self.hint)
