"""
论文深度解析模块
调用 DeepSeek API 对论文摘要进行：
  - 中文精读解析
  - 核心贡献提取
  - 研究方法识别
  - 局限性分析
  - BibTeX / APA / MLA 引用生成
"""

import json
from typing import Dict, List

from openai import OpenAI

from Litagent.config.settings import get_deepseek_api_key


def _get_client() -> OpenAI:
    return OpenAI(api_key=get_deepseek_api_key(), base_url="https://api.deepseek.com")


# ── 单篇论文精读 ──────────────────────────────────────────
def analyze_paper(paper: Dict) -> Dict:
    """
    对单篇论文进行深度解析，返回结构化中文分析结果
    """
    client = _get_client()

    system_prompt = """你是一位顶尖的学术论文分析专家，专注于电子信息、人工智能和雷达信号处理领域。
你的任务是对论文进行严谨、深入的中文解析。

输出必须严格遵循以下 JSON 格式，不要输出任何 JSON 以外的内容：
{
  "contribution": ["贡献1", "贡献2", "贡献3"],
  "method": "研究方法的简洁描述（1-2句）",
  "innovation": "最核心的创新点（1句话）",
  "limitation": "主要局限性或不足（1-2句）",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "analysis": "面向研究生的完整中文解析（300字左右），包含：研究背景、核心思路、实验结论"
}"""

    user_prompt = f"""请解析以下论文：

标题：{paper["title"]}
作者：{", ".join(paper["authors"][:5])}
发表时间：{paper["published"]}
分类：{", ".join(paper["categories"][:3])}

摘要（英文原文）：
{paper["summary"]}"""

    raw = ""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            timeout=60,
        )

        raw = response.choices[0].message.content or ""

        # 清理可能的 markdown 代码块包装
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        result = json.loads(cleaned)
        result.update(paper)
        return result

    except json.JSONDecodeError as e:
        paper["analysis"] = raw
        paper["parse_error"] = str(e)
        return paper
    except Exception as e:
        paper["error"] = f"解析失败: {e}"
        return paper


# ── 引用格式生成 ──────────────────────────────────────────
def generate_citations(paper: Dict) -> Dict[str, str]:
    """
    为论文生成三种标准引用格式
    返回: {"bibtex": "...", "apa": "...", "mla": "..."}
    """
    arxiv_id = paper.get("arxiv_id", "unknown")
    title = paper.get("title", "Unknown Title")
    authors = paper.get("authors", ["Unknown"])
    year = paper.get("published", "0000")[:4]

    # BibTeX key：第一作者姓 + 年份 + 标题首词
    first_author_last = authors[0].split()[-1].lower() if authors else "unknown"
    title_first_word = title.split()[0].lower().strip(".,;:")
    cite_key = f"{first_author_last}{year}{title_first_word}"

    bibtex_authors = " and ".join(authors[:6])
    if len(authors) > 6:
        bibtex_authors += " and others"

    bibtex = (
        f"@article{{{cite_key},\n"
        f"  title   = {{{title}}},\n"
        f"  author  = {{{bibtex_authors}}},\n"
        f"  journal = {{arXiv preprint arXiv:{arxiv_id}}},\n"
        f"  year    = {{{year}}},\n"
        f"  url     = {{https://arxiv.org/abs/{arxiv_id}}}\n"
        f"}}"
    )

    # APA 7th
    if len(authors) == 1:
        apa_author = _apa_name(authors[0])
    elif len(authors) <= 20:
        apa_author = ", ".join(_apa_name(a) for a in authors[:-1])
        apa_author += f", & {_apa_name(authors[-1])}"
    else:
        apa_author = ", ".join(_apa_name(a) for a in authors[:19])
        apa_author += f", ... {_apa_name(authors[-1])}"

    apa = (
        f"{apa_author} ({year}). {title}. "
        f"*arXiv preprint arXiv:{arxiv_id}*. "
        f"https://arxiv.org/abs/{arxiv_id}"
    )

    # MLA 9th
    if len(authors) == 1:
        mla_author = _mla_name(authors[0])
    elif len(authors) == 2:
        mla_author = f"{_mla_name(authors[0])}, and {authors[1]}"
    else:
        mla_author = f"{_mla_name(authors[0])}, et al."

    mla = (
        f'{mla_author}. "{title}." '
        f"*arXiv*, {arxiv_id}, {year}, "
        f"arxiv.org/abs/{arxiv_id}."
    )

    return {"bibtex": bibtex, "apa": apa, "mla": mla}


def _apa_name(full_name: str) -> str:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    initials = ". ".join(p[0].upper() for p in parts[:-1]) + "."
    return f"{last}, {initials}"


def _mla_name(full_name: str) -> str:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    first = " ".join(parts[:-1])
    return f"{last}, {first}"


# ── 格式化输出 ────────────────────────────────────────────
def format_analysis(paper: Dict) -> str:
    """将解析结果格式化为 Markdown 字符串"""
    lines = []
    lines.append(f"## {paper.get('title', 'N/A')}")
    lines.append(
        f"**arXiv ID**: {paper.get('arxiv_id', 'N/A')}  |  "
        f"**发表**: {paper.get('published', 'N/A')}"
    )
    lines.append(f"**链接**: {paper.get('abs_url', 'N/A')}\n")

    if "error" in paper:
        lines.append(f"> 解析出错: {paper['error']}")
        return "\n".join(lines)

    if "innovation" in paper:
        lines.append(f"### 核心创新点\n{paper['innovation']}\n")

    if "contribution" in paper:
        lines.append("### 主要贡献")
        for c in paper["contribution"]:
            lines.append(f"- {c}")
        lines.append("")

    if "method" in paper:
        lines.append(f"### 研究方法\n{paper['method']}\n")

    if "limitation" in paper:
        lines.append(f"### 局限性\n{paper['limitation']}\n")

    if "keywords" in paper:
        lines.append(f"### 关键词\n`{'` `'.join(paper['keywords'])}`\n")

    if "analysis" in paper:
        lines.append(f"### 详细解析\n{paper['analysis']}\n")

    citations = generate_citations(paper)
    lines.append("### 引用格式")
    lines.append("**BibTeX:**")
    lines.append(f"```bibtex\n{citations['bibtex']}\n```")
    lines.append(f"**APA:** {citations['apa']}\n")
    lines.append(f"**MLA:** {citations['mla']}\n")

    return "\n".join(lines)
