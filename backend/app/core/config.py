"""Load local configuration without requiring cloud credentials at startup."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)

_PLACEHOLDER_KEYS = {
    "your_chat_api_key_here",
    "your_embedding_api_key_here",
    "your_api_key_here",
}


@dataclass(frozen=True)
class Settings:
    chat_base_url: str
    chat_model: str
    chat_api_key: str = field(repr=False)
    embedding_base_url: str
    embedding_model: str
    embedding_api_key: str = field(repr=False)
    chroma_path: str

    @property
    def env_configured(self) -> bool:
        """Check presence only; this does not validate keys against a cloud API."""
        values = (
            self.chat_base_url,
            self.chat_model,
            self.chat_api_key,
            self.embedding_base_url,
            self.embedding_model,
            self.embedding_api_key,
            self.chroma_path,
        )
        keys = (self.chat_api_key, self.embedding_api_key)
        return all(values) and all(
            key.casefold() not in _PLACEHOLDER_KEYS for key in keys
        )


def get_settings() -> Settings:
    """Environment variables take precedence over the repository's .env file."""
    return Settings(
        chat_base_url=os.getenv("CHAT_BASE_URL", "https://api.siliconflow.cn/v1").strip(),
        chat_model=os.getenv("CHAT_MODEL", "deepseek-ai/DeepSeek-V3").strip(),
        chat_api_key=os.getenv("CHAT_API_KEY", "").strip(),
        embedding_base_url=os.getenv(
            "EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1"
        ).strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3").strip(),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
        chroma_path=os.getenv("CHROMA_PATH", "./backend/chroma_db").strip(),
    )
