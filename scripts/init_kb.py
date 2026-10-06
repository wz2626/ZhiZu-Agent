"""Initialize and optionally verify the local lease-law Chroma collection."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings
from backend.app.services.embedding import get_embeddings
from backend.app.services.vector_store import LawVectorStoreService

VERIFY_QUERIES = (
    "房东扣留押金，退租后如何返还押金？",
    "房屋漏水需要维修，房东不修谁承担维修费用？",
    "承租人未经同意擅自转租，出租人可以解约吗？",
    "不定期租赁解除合同，需要提前多久通知对方？",
    "房屋危及安全或者甲醛超标影响健康，承租人能否解除合同？",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auto", "cloud", "mock"), default="auto")
    parser.add_argument("--persist-dir", default=get_settings().chroma_path)
    parser.add_argument("--verify-queries", action="store_true")
    args = parser.parse_args(argv)

    service = LawVectorStoreService(
        persist_directory=args.persist_dir,
        embeddings=get_embeddings(args.mode),
    )
    print(json.dumps(service.ingest_laws().model_dump(), ensure_ascii=False))
    if args.verify_queries:
        for query in VERIFY_QUERIES:
            evidence = service.search_evidence(query, top_k=3)
            print(json.dumps({
                "query": query,
                "evidence": [
                    {"article_no": item.article_no, "law_id": item.evidence_id,
                     "source_url": str(item.source_url)}
                    for item in evidence
                ],
                "note": "本章没有直接规定押金返还，召回条文不得充当直接依据。" if "押金" in query else None,
            }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
