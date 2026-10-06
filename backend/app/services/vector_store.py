"""Dedicated Chroma collection for the 32 authoritative lease articles."""

import json
import re
from pathlib import Path

import chromadb
from langchain_core.embeddings import Embeddings

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.schemas.knowledge import EvidenceItem, KBInitResult, LawArticle
from backend.app.services.embedding import get_embeddings

LAW_FILE = PROJECT_ROOT / "backend" / "data" / "laws" / "civil_code_lease_703_734.json"
VALID_IDS = {f"LAW-{number}" for number in range(703, 735)}


def _mask_sensitive_text(text: str) -> str:
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", text)
    return re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "[身份证号]", text)


def load_authoritative_laws() -> list[LawArticle]:
    """Read only the pinned authoritative JSON file; never scan directories."""
    raw = json.loads(LAW_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) != 32:
        raise ValueError("authoritative law file must contain exactly 32 articles")
    articles = [LawArticle.model_validate(item) for item in raw]
    if {item.law_id for item in articles} != VALID_IDS:
        raise ValueError("authoritative law IDs must be exactly LAW-703 through LAW-734")
    if [item.article_number for item in articles] != list(range(703, 735)):
        raise ValueError("authoritative law articles must be ordered and consecutive")
    return articles


class LawVectorStoreService:
    def __init__(
        self,
        persist_directory: str | Path | None = None,
        collection_name: str = "civil_code_lease_laws",
        embeddings: Embeddings | None = None,
    ) -> None:
        directory = persist_directory if persist_directory is not None else get_settings().chroma_path
        self.persist_directory = Path(directory).resolve()
        self.collection_name = collection_name
        self.embeddings = embeddings if embeddings is not None else get_embeddings()
        self.embedding_mode = getattr(self.embeddings, "mode", "custom")
        self.embedding_identity = (
            f"{self.embedding_mode}:{getattr(self.embeddings, 'model', 'deterministic-v1')}"
        )
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
                "embedding_mode": self.embedding_mode,
                "embedding_identity": self.embedding_identity,
            },
        )
        self._check_mode()

    def _check_mode(self) -> None:
        existing_mode = (self.collection.metadata or {}).get("embedding_mode")
        if existing_mode != self.embedding_mode:
            raise ValueError(
                "collection embedding mode differs; use a new collection or rebuild it explicitly"
            )
        if (self.collection.metadata or {}).get("embedding_identity") != self.embedding_identity:
            raise ValueError(
                "collection embedding model differs; use a new collection or rebuild it explicitly"
            )

    def _check_ids(self) -> list[str]:
        ids = self.collection.get(include=[])["ids"]
        unexpected = set(ids) - VALID_IDS
        if unexpected:
            raise ValueError("dedicated law collection contains non-authoritative IDs")
        return ids

    @staticmethod
    def _document(article: LawArticle) -> str:
        return f"{article.article_no} {article.content}\n主题：{'、'.join(article.topic_tags)}"

    @staticmethod
    def _metadata(article: LawArticle) -> dict:
        return {
            "article_number": article.article_number,
            "article_no": article.article_no,
            "law_name": article.law_name,
            "part_chapter": article.part_chapter,
            "source_url": str(article.source_url),
            "verified_date": article.verified_date.isoformat(),
            "topic_tags": json.dumps(article.topic_tags, ensure_ascii=False),
        }

    def ingest_laws(self) -> KBInitResult:
        self._check_mode()
        laws = load_authoritative_laws()
        existing = set(self._check_ids())
        before_count = len(existing)
        ids = [article.law_id for article in laws]
        documents = [self._document(article) for article in laws]
        vectors = self.embeddings.embed_documents(documents)
        if len(vectors) != 32:
            raise ValueError("embedding service returned an unexpected vector count")
        self.collection.upsert(
            ids=ids,
            documents=[article.content for article in laws],
            metadatas=[self._metadata(article) for article in laws],
            embeddings=vectors,
        )
        total_count = self.collection.count()
        if total_count != 32:
            raise RuntimeError("authoritative law collection must contain exactly 32 records")
        return KBInitResult(
            collection_name=self.collection_name,
            persist_directory=str(self.persist_directory),
            loaded_articles=len(laws),
            before_count=before_count,
            inserted_count=len(VALID_IDS - existing),
            updated_count=len(existing),
            total_count=total_count,
            embedding_mode=self.embedding_mode,
        )

    @staticmethod
    def _evidence(article: LawArticle, score: float) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=article.law_id,
            article_number=article.article_number,
            article_no=article.article_no,
            law_name=article.law_name,
            part_chapter=article.part_chapter,
            content=article.content,
            source_url=article.source_url,
            verified_date=article.verified_date,
            score=max(0.0, min(1.0, score)),
        )

    def search_evidence(self, query: str, top_k: int = 4) -> list[EvidenceItem]:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= top_k <= 32:
            raise ValueError("top_k must be between 1 and 32")
        self._check_mode()
        self._check_ids()
        if self.collection.count() == 0:
            return []
        safe_query = _mask_sensitive_text(query) if self.embedding_mode == "cloud" else query
        result = self.collection.query(
            query_embeddings=[self.embeddings.embed_query(safe_query)],
            n_results=min(top_k, self.collection.count()),
            include=["distances"],
        )
        authoritative = {article.law_id: article for article in load_authoritative_laws()}
        return [
            self._evidence(authoritative[law_id], 1.0 - distance)
            for law_id, distance in zip(result["ids"][0], result["distances"][0])
            if law_id in authoritative
        ]

    def get_laws_by_ids(self, evidence_ids: list[str]) -> list[EvidenceItem]:
        self._check_mode()
        self._check_ids()
        valid = list(dict.fromkeys(
            item for item in evidence_ids
            if isinstance(item, str) and re.fullmatch(r"LAW-\d{3}", item) and item in VALID_IDS
        ))
        if not valid:
            return []
        found = set(self.collection.get(ids=valid, include=[])["ids"])
        authoritative = {article.law_id: article for article in load_authoritative_laws()}
        return [self._evidence(authoritative[law_id], 1.0) for law_id in valid if law_id in found]
