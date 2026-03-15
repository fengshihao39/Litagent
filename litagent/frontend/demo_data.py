"""Litagent - 前端示例数据"""

from typing import Any


# ruff: noqa E501
def get_demo_results() -> list[dict[str, Any]]:
    return [
        {
            "title": "Transformer-based Literature Review Agent",
            "abstract": "We propose an agentic system that retrieves, ranks, and summarizes papers for rapid review.",
            "authors": ["Li Wei", "Ana Gomez", "Rahul Iyer"],
            "year": 2024,
            "keywords": ["LLM", "retrieval", "summarization", "automation"],
            "venue": "ACL",
            "doi": "10.1234/acl-demo-24",
        },
        {
            "title": "Scientific Document Understanding with Multimodal Models",
            "abstract": "A model that fuses text, layout, and figures to improve downstream scholarly tasks.",
            "authors": ["Chen Yu", "Maria Rossi"],
            "year": 2023,
            "keywords": ["multimodal", "vision-language", "scholar"],
            "venue": "NeurIPS",
            "doi": "10.5555/nips-mm-23",
        },
        {
            "title": "Trends in Automated Bibliography Generation",
            "abstract": "Survey of toolchains that convert structured metadata to BibTeX and CSL-JSON.",
            "authors": ["Smith John"],
            "year": 2021,
            "keywords": ["citation", "bibtex", "tooling"],
            "venue": "JASIST",
            "doi": "10.7777/jasist-21",
        },
    ]
