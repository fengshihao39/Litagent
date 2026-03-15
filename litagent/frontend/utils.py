"""Litagent - Streamlit 工具层

该模块是 Litagent 的 Streamlit 前端的工具层，包括了部分前端展示时使用的工具。
"""

from typing import Any


def to_bibtex(entry: dict[str, Any]) -> str:
    """将论文数据字典转换为 BibTeX 字符串。

    Args:
        entry (Dict[str, Any]): 后端获取到的论文数据字典。

    Returns:
        str: 该论文的 BibTeX 字符串。
    """
    authors = entry.get("authors") or []
    author_field = " and ".join(authors)
    year = entry.get("year", "")
    first_author_token = authors[0].split()[-1].lower() if authors else "anon"
    key = f"{first_author_token}{year}"

    return "\n".join(
        [
            f"@article{{{key},",
            f"  title={{ {entry.get('title', '')} }},",
            f"  author={{ {author_field} }},",
            f"  year={{ {year} }},",
            f"  journal={{ {entry.get('venue', '')} }},",
            f"  doi={{ {entry.get('doi', '')} }},",
            "}",
        ]
    )
