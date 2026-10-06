"""Cloud and reproducible local embeddings for Chinese lease-law retrieval."""

import hashlib
import math
import re

import httpx
from langchain_core.embeddings import Embeddings

from backend.app.core.config import get_settings

DIMENSIONS = 1024
_TOPICS = (
    ("维修", "修理", "修缮", "漏水", "坏了", "故障", "维修费"),
    ("转租", "二房东", "次承租", "擅自出租"),
    ("解除", "解约", "终止合同"),
    ("安全", "健康", "危及", "甲醛", "有毒", "危房"),
    ("不定期", "通知期", "提前通知", "合理期限"),
    ("押金", "保证金", "扣押金", "退押金"),
    ("返还", "退还", "归还", "退回"),
    ("损耗", "磨损", "损坏", "毁损"),
    ("租金", "房租", "欠租", "减租"),
    ("优先购买", "买房", "出售房屋"),
    ("续租", "优先承租"),
    ("交付", "交房", "无法使用"),
)


def has_real_key(key: str) -> bool:
    candidate = key.strip().casefold()
    return bool(candidate) and not any(
        marker in candidate for marker in ("your_", "placeholder", "replace_me", "填入", "示例")
    )


class SiliconFlowEmbeddings(Embeddings):
    mode = "cloud"

    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float = 20.0):
        if not has_real_key(api_key):
            raise ValueError("cloud embedding mode requires a configured API key")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"SiliconFlowEmbeddings(model={self.model!r}, mode='cloud')"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            indexed = sorted(payload["data"], key=lambda item: item["index"])
            vectors = [[float(value) for value in item["embedding"]] for item in indexed]
            if len(vectors) != len(texts) or not all(vectors):
                raise ValueError("invalid embedding response")
            return vectors
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise RuntimeError("embedding service request failed; check endpoint, model and credentials") from None

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class DeterministicHashEmbeddings(Embeddings):
    """Stable 1024-dimensional vectors; useful only for offline checks."""

    mode = "mock"

    def _embed(self, text: str) -> list[float]:
        normalized = re.sub(r"\s+", "", text.casefold())
        vector = [0.0] * DIMENSIONS
        for position, aliases in enumerate(_TOPICS):
            if any(alias in normalized for alias in aliases):
                vector[position] = 5.0
        chinese = re.findall(r"[\u3400-\u9fff]", normalized)
        features = chinese + ["".join(chinese[i:i + n]) for n in (2, 3) for i in range(len(chinese) - n + 1)]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = 32 + int.from_bytes(digest, "big") % (DIMENSIONS - 32)
            vector[bucket] += 0.35 if len(feature) == 1 else 0.7
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings(mode: str = "auto") -> Embeddings:
    if mode not in {"auto", "cloud", "mock"}:
        raise ValueError("mode must be auto, cloud or mock")
    settings = get_settings()
    if mode == "mock" or (mode == "auto" and not has_real_key(settings.embedding_api_key)):
        return DeterministicHashEmbeddings()
    return SiliconFlowEmbeddings(
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key,
    )
