"""
Litagent - 论文 AI 结构化总结服务

支持两种模式：
  1. 全文模式（pdf_text 非空）：基于章节化正文做深度解读
  2. 摘要兜底模式：仅凭摘要+元数据做轻量总结

同时提供标题中英互译能力。
"""

from __future__ import annotations

from openai import OpenAI

from litagent.backend.app.core.config import get_deepseek_api_key

_client = OpenAI(
    api_key=get_deepseek_api_key(),
    base_url="https://api.deepseek.com",
)

# ── 全文模式提示词 ─────────────────────────────────────────────────────────────

_FULLTEXT_SUMMARY_PROMPT = """\
你是一名专业科研助手，擅长深度解读学术论文。
用户将提供一篇论文的正文章节内容（包含 Abstract、Introduction、Method、Experiment、Result、Conclusion 等）。
请基于这些内容输出结构化分析报告。

输出格式必须严格如下，每项尽量详细（3~6 句话），有据可依：

【研究背景】
（这篇论文针对什么领域背景和现实问题）

【研究问题】
（作者试图解决的核心科学问题或技术挑战）

【核心方法】
（提出了什么方法/模型/框架，关键设计思路是什么）

【实验设置】
（使用了什么数据集、基线方法、评估指标）

【主要结论】
（实验结果表明什么，取得了哪些性能提升或发现）

【创新点】
（与已有工作相比，这篇论文的核心创新和贡献是什么）

【应用场景】
（这项研究可以应用在哪些实际场景）

【局限性与未来工作】
（作者承认的局限，或尚未解决的问题）

规则：
- 每项内容必须基于论文原文，不得凭空编造
- 如果某节内容中确实找不到相关信息，写"论文未明确说明"
- 只输出上述结构内容，不要加任何前缀或后缀说明
"""

# ── 摘要兜底提示词 ─────────────────────────────────────────────────────────────

_ABSTRACT_SUMMARY_PROMPT = """\
你是一名科研助手，擅长解读学术论文。
用户仅提供了论文的摘要和部分元数据（标题、期刊、年份、关键词等）。
请基于这些内容输出结构化分析。

输出格式必须严格如下：

【研究背景】
（根据摘要推断研究背景）

【研究问题】
（作者试图解决的核心问题）

【核心方法】
（摘要中提及的方法或技术）

【主要结论】
（摘要中明确给出的结论或贡献）

【应用场景】
（根据摘要推断的应用方向）

【局限性】
（摘要中提及的或显而易见的局限）

规则：
- 只能基于摘要内容，推断部分必须在末尾注明"（AI 推断，非全文依据）"
- 摘要中确实找不到的信息，写"摘要中未说明"（不要写"摘要中未明确说明"）
- 只输出上述结构，不要加任何前缀或解释
"""


def generate_paper_summary(
    abstract: str,
    pdf_text: str = "",
    title: str = "",
    venue: str = "",
    year: str = "",
    keywords: list[str] | None = None,
) -> str:
    """
    生成结构化 AI 总结。

    Args:
        abstract:  论文摘要
        pdf_text:  PDF 全文提取文本（有则走全文模式，否则走摘要模式）
        title:     论文标题
        venue:     期刊/会议
        year:      发表年份
        keywords:  关键词列表

    Returns:
        结构化总结文本（含模式标注）
    """
    use_fulltext = bool(pdf_text and pdf_text.strip() and len(pdf_text.strip()) > 300)

    if use_fulltext:
        return _generate_fulltext_summary(
            pdf_text=pdf_text,
            title=title,
            venue=venue,
            year=year,
            keywords=keywords or [],
        )
    else:
        if not abstract or not abstract.strip():
            return "暂无摘要，无法生成 AI 总结。"
        return _generate_abstract_summary(
            abstract=abstract,
            title=title,
            venue=venue,
            year=year,
            keywords=keywords or [],
        )


def _build_meta_block(title: str, venue: str, year: str, keywords: list[str]) -> str:
    parts = []
    if title:
        parts.append(f"标题：{title}")
    if venue:
        parts.append(f"期刊/会议：{venue}")
    if year:
        parts.append(f"年份：{year}")
    if keywords:
        parts.append(f"关键词：{', '.join(keywords[:8])}")
    return "\n".join(parts)


def _generate_fulltext_summary(
    pdf_text: str,
    title: str,
    venue: str,
    year: str,
    keywords: list[str],
) -> str:
    meta = _build_meta_block(title, venue, year, keywords)
    user_content = ""
    if meta:
        user_content += f"【论文基本信息】\n{meta}\n\n"
    user_content += f"【论文正文内容】\n{pdf_text.strip()}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _FULLTEXT_SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1500,
            temperature=0.3,
        )
        content = (resp.choices[0].message.content or "").strip()
        return f"> 本总结基于论文 PDF 全文生成\n\n{content}"
    except Exception:
        return "AI 总结生成失败，请稍后重试。"


def _generate_abstract_summary(
    abstract: str,
    title: str,
    venue: str,
    year: str,
    keywords: list[str],
) -> str:
    meta = _build_meta_block(title, venue, year, keywords)
    user_content = ""
    if meta:
        user_content += f"【论文基本信息】\n{meta}\n\n"
    user_content += f"【论文摘要】\n{abstract.strip()}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _ABSTRACT_SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1000,
            temperature=0.3,
        )
        content = (resp.choices[0].message.content or "").strip()
        return f"> 本总结仅基于摘要生成，非全文精读\n\n{content}"
    except Exception:
        return "AI 总结生成失败，请稍后重试。"


_TRANSLATE_PROMPT = """\
你是一名学术翻译专家。请将下面的英文论文标题翻译成中文，要求：
1. 专业术语保留或使用标准中文译名
2. 语言简洁自然
3. 只输出翻译结果，不要添加任何解释
"""


def translate_title_to_chinese(title: str) -> str:
    """
    将英文标题翻译成中文。

    Args:
        title: 英文论文标题

    Returns:
        中文标题
    """
    if not title or not title.strip():
        return ""

    # 如果已经是中文（超过 30% 汉字），直接返回
    chinese_chars = sum(1 for c in title if "\u4e00" <= c <= "\u9fff")
    if chinese_chars / max(len(title), 1) > 0.3:
        return title

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _TRANSLATE_PROMPT},
                {"role": "user", "content": title.strip()},
            ],
            max_tokens=200,
            temperature=0.1,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""
