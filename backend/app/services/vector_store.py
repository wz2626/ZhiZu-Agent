"""Dedicated Chroma collection for the 32 authoritative lease articles."""

import json
import logging
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import chromadb
from langchain_core.embeddings import Embeddings

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.schemas.knowledge import EvidenceItem, KBInitResult, KBStatusResponse, LawArticle
from backend.app.services.embedding import DIMENSIONS, get_embeddings

LAW_FILE = PROJECT_ROOT / "backend" / "data" / "laws" / "civil_code_lease_703_734.json"
VALID_IDS = {f"LAW-{number}" for number in range(703, 735)}
SOURCE_URL = "https://www.court.gov.cn/zixun/xiangqing/233181.html"
VERIFIED_DATE = "2026-10-05"
STORAGE_ERRORS = (chromadb.errors.ChromaError, sqlite3.DatabaseError, OSError)
logger = logging.getLogger(__name__)

_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[ \t-]*)?1[3-9]\d[ \t-]?\d{4}[ \t-]?\d{4}(?!\d)")
_BIRTH_MONTH_DAY = r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
_ID_PATTERN = re.compile(
    r"(?<!\d)(?:"
    r"[1-9]\d{5}(?:18|19|20)\d{2}" + _BIRTH_MONTH_DAY + r"\d{3}[\dXx]|"
    r"[1-9]\d{5}\d{2}" + _BIRTH_MONTH_DAY + r"\d{3})(?!\d)"
)


def mask_sensitive_text(text: str) -> str:
    text = _PHONE_PATTERN.sub("[手机号]", text)
    return _ID_PATTERN.sub("[身份证号]", text)


def _check_sqlite_readable(directory: Path) -> None:
    """Reject damaged files before Chroma can cache a partially started System."""
    database_uri = (directory / "chroma.sqlite3").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        checks = connection.execute("PRAGMA quick_check").fetchall()
        if checks != [("ok",)]:
            raise ValueError("law storage integrity check failed")


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
        create_if_missing: bool = True,
    ) -> None:
        directory = persist_directory if persist_directory is not None else get_settings().chroma_path
        self.persist_directory = Path(directory).resolve()
        self.collection_name = collection_name
        self.embeddings = embeddings if embeddings is not None else get_embeddings()
        self.embedding_mode = getattr(self.embeddings, "mode", "custom")
        self.embedding_identity = (
            f"{self.embedding_mode}:{getattr(self.embeddings, 'model', 'deterministic-v1')}"
        )
        self.embedding_dimension = getattr(self.embeddings, "expected_dimension", DIMENSIONS)
        if create_if_missing:
            self.persist_directory.mkdir(parents=True, exist_ok=True)
        else:
            if not (self.persist_directory / "chroma.sqlite3").is_file():
                raise ValueError("law collection is not initialized")
            _check_sqlite_readable(self.persist_directory)
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        try:
            if create_if_missing:
                self.collection = self.client.get_or_create_collection(
                    name=collection_name,
                    metadata={
                        "hnsw:space": "cosine",
                        "embedding_mode": self.embedding_mode,
                        "embedding_identity": self.embedding_identity,
                        "embedding_dimension": self.embedding_dimension,
                    },
                )
            else:
                try:
                    self.collection = self.client.get_collection(name=collection_name)
                except chromadb.errors.NotFoundError:
                    raise ValueError("law collection is not initialized") from None
            self._check_mode()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "LawVectorStoreService":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

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
        stored_dimension = (self.collection.metadata or {}).get("embedding_dimension")
        if stored_dimension is not None and stored_dimension != self.embedding_dimension:
            raise ValueError(
                f"collection embedding dimension differs: expected {self.embedding_dimension}, "
                f"got {stored_dimension}"
            )

    @classmethod
    def inspect_status(
        cls,
        persist_directory: str | Path | None = None,
        collection_name: str = "civil_code_lease_laws",
        embeddings: Embeddings | None = None,
    ) -> KBStatusResponse:
        """Inspect an existing collection without creating a directory or collection."""
        directory = persist_directory if persist_directory is not None else get_settings().chroma_path
        path = Path(directory).resolve()
        selected_embeddings = embeddings if embeddings is not None else get_embeddings()
        if (path / "chroma.sqlite3").is_file():
            try:
                _check_sqlite_readable(path)
                with chromadb.PersistentClient(path=str(path)) as client:
                    collection = client.get_collection(name=collection_name)
                    return cls._collection_status(path, collection_name, selected_embeddings, collection)
            except (ValueError, *STORAGE_ERRORS) as error:
                # Do not expose database details or assume a damaged DB has zero records.
                logger.warning("KB storage inspection failed (%s)", type(error).__name__)
        return cls._collection_status(path, collection_name, selected_embeddings)

    def get_status(self) -> KBStatusResponse:
        """Inspect the collection already opened by this service."""
        return self._collection_status(
            self.persist_directory, self.collection_name, self.embeddings, self.collection,
        )

    @staticmethod
    def _collection_status(
        path: Path,
        collection_name: str,
        selected_embeddings: Embeddings,
        collection: chromadb.Collection | None = None,
    ) -> KBStatusResponse:
        configured_mode = getattr(selected_embeddings, "mode", "custom")
        expected_identity = (
            f"{configured_mode}:{getattr(selected_embeddings, 'model', 'deterministic-v1')}"
        )
        expected_dimension = getattr(selected_embeddings, "expected_dimension", DIMENSIONS)
        indexed_count = 0
        is_ready = False
        embedding_mode = configured_mode
        if collection is not None:
            metadata = collection.metadata or {}
            embedding_mode = metadata.get("embedding_mode", configured_mode)
            ids = collection.get(include=[])["ids"]
            indexed_count = len(ids)
            is_ready = (
                indexed_count == 32
                and set(ids) == VALID_IDS
                and embedding_mode == configured_mode
                and metadata.get("embedding_identity") == expected_identity
                and metadata.get("embedding_dimension") == expected_dimension
            )
        return KBStatusResponse(
            collection_name=collection_name,
            persist_directory=str(path),
            indexed_count=indexed_count,
            is_ready=is_ready,
            embedding_mode=embedding_mode,
            source_url=SOURCE_URL,
            verified_date=VERIFIED_DATE,
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
        if before_count and (self.collection.metadata or {}).get("embedding_dimension") is None:
            stored_vectors = self.collection.get(include=["embeddings"])["embeddings"]
            if stored_vectors is None or any(len(vector) != self.embedding_dimension for vector in stored_vectors):
                raise ValueError("existing collection has incompatible embedding dimensions")
        ids = [article.law_id for article in laws]
        documents = [self._document(article) for article in laws]
        vectors = self.embeddings.embed_documents(documents)
        if len(vectors) != 32:
            raise ValueError("embedding service returned an unexpected vector count")
        for vector in vectors:
            if len(vector) != self.embedding_dimension:
                raise ValueError(
                    f"embedding dimension mismatch: expected {self.embedding_dimension}, got {len(vector)}"
                )
        self.collection.upsert(
            ids=ids,
            documents=[article.content for article in laws],
            metadatas=[self._metadata(article) for article in laws],
            embeddings=vectors,
        )
        if (self.collection.metadata or {}).get("embedding_dimension") is None:
            updated_metadata = dict(self.collection.metadata or {})
            updated_metadata.pop("hnsw:space", None)
            updated_metadata["embedding_dimension"] = self.embedding_dimension
            self.collection.modify(metadata=updated_metadata)
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
        if not math.isfinite(score):
            raise ValueError("evidence score must be finite")
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
        safe_query = mask_sensitive_text(query) if self.embedding_mode == "cloud" else query
        query_vector = self.embeddings.embed_query(safe_query)
        if len(query_vector) != self.embedding_dimension:
            raise ValueError(
                f"embedding dimension mismatch: expected {self.embedding_dimension}, "
                f"got {len(query_vector)}"
            )
        try:
            norm = math.hypot(*query_vector)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("query vector must contain finite numbers") from None
        if not math.isfinite(norm):
            raise ValueError("query vector norm must be finite")
        if norm == 0.0:
            return []
        result = self.collection.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, self.collection.count()),
            include=["distances"],
        )
        authoritative = {article.law_id: article for article in load_authoritative_laws()}
        evidence = []
        for law_id, distance in zip(result["ids"][0], result["distances"][0]):
            if not math.isfinite(distance):
                raise ValueError("retrieval distance must be finite")
            score = 1.0 - distance
            if law_id in authoritative and score > 0.0:
                evidence.append(self._evidence(authoritative[law_id], score))
        return evidence

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
