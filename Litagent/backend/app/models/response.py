"""Pydantic response models."""

from typing import List, Optional

from pydantic import BaseModel


class PaperResult(BaseModel):
    title: str
    abstract: str
    authors: List[str]
    year: Optional[int]
    keywords: List[str]
    venue: str
    doi: str
    source: str
    abs_url: str
    citation_count: int
    tldr: str


class SearchResponse(BaseModel):
    results: List[PaperResult]
    translated_query: str
    total: int
