"""Contracts for the authoritative lease-law knowledge base."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, model_validator


LawId = Annotated[str, StringConstraints(pattern=r"^LAW-(70[3-9]|71[0-9]|72[0-9]|73[0-4])$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def chinese_article_no(number: int) -> str:
    digits = "零一二三四五六七八九"
    rest = number % 100
    tens, ones = divmod(rest, 10)
    suffix = (digits[tens] + "十" if tens != 0 else "零") + (digits[ones] if ones else "")
    return f"第七百{suffix}条"


class LawArticle(BaseModel):
    law_id: LawId
    article_number: int = Field(ge=703, le=734)
    article_no: NonEmpty
    law_name: NonEmpty
    part_chapter: NonEmpty
    content: NonEmpty
    topic_tags: list[NonEmpty] = Field(min_length=1)
    source_url: HttpUrl
    verified_date: date

    @model_validator(mode="after")
    def validate_identity(self) -> "LawArticle":
        if self.law_id != f"LAW-{self.article_number}":
            raise ValueError("law_id and article_number must match")
        if self.article_no != chinese_article_no(self.article_number):
            raise ValueError("article_no and article_number must match")
        if self.law_name != "中华人民共和国民法典":
            raise ValueError("unexpected law_name")
        if self.part_chapter != "第三编 合同 / 第十四章 租赁合同":
            raise ValueError("unexpected part_chapter")
        if str(self.source_url) != "https://www.court.gov.cn/zixun/xiangqing/233181.html":
            raise ValueError("unexpected source_url")
        if self.verified_date != date(2026, 10, 5):
            raise ValueError("unexpected verified_date")
        if "…" in self.content or "..." in self.content:
            raise ValueError("article content cannot be abbreviated")
        return self


class EvidenceItem(BaseModel):
    evidence_id: LawId
    article_number: int = Field(ge=703, le=734)
    article_no: NonEmpty
    law_name: NonEmpty
    part_chapter: NonEmpty
    content: NonEmpty
    source_url: HttpUrl
    verified_date: date
    score: float = Field(ge=0, le=1)


class KBInitResult(BaseModel):
    collection_name: NonEmpty
    persist_directory: NonEmpty
    loaded_articles: int = Field(ge=0)
    before_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    embedding_mode: NonEmpty


class KBSearchRequest(BaseModel):
    query: NonEmpty
    top_k: int = Field(default=4, ge=1, le=32)


class KBSearchResponse(BaseModel):
    query: NonEmpty
    evidence: list[EvidenceItem]
