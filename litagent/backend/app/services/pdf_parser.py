"""
Litagent - PDF 全文解析服务

使用 PyMuPDF (fitz) 解析 PDF，提取并按章节分段。
目标章节：Abstract / Introduction / Method / Experiment / Result / Conclusion
同时支持中文学术论文（第X章 格式）。

解析结果缓存到 data/parsed/<key>.json，避免重复解析。

返回结构：
{
    "full_text":   str,          # 全文拼接（截断到约 12000 字）
    "sections": {
        "abstract":    str,
        "introduction": str,
        "method":      str,
        "experiment":  str,
        "result":      str,
        "conclusion":  str,
    },
    "page_count":  int,
    "char_count":  int,
    "source":      "pdf" | "abstract_fallback"
}
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_PARSED_CACHE_DIR = Path(__file__).parents[5] / "data" / "parsed"
_PARSED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 喂给 LLM 的最大字符数（约 3000 tokens）
_MAX_CHARS = 12000

# 英文章节标题的正则匹配模式（不区分大小写）
_SECTION_PATTERNS: dict[str, list[str]] = {
    "abstract": [r"\babstract\b"],
    "introduction": [r"\bintroduction\b", r"\b1[\.\s]?\s*introduction\b"],
    "method": [
        r"\bmethod(ology|s)?\b",
        r"\bapproach\b",
        r"\bproposed\s+method\b",
        r"\b[23][\.\s]?\s*method",
    ],
    "experiment": [
        r"\bexperiment(s|al\s+setup)?\b",
        r"\bevaluation\b",
        r"\b[3-5][\.\s]?\s*experiment",
    ],
    "result": [
        r"\bresult(s)?\b",
        r"\bfinding(s)?\b",
        r"\b[4-6][\.\s]?\s*result",
    ],
    "conclusion": [
        r"\bconclusion(s)?\b",
        r"\bsummary\b",
        r"\b[5-8][\.\s]?\s*conclusion",
    ],
}

# 中文章节标题映射
# key: 目标章节名, value: 匹配该章节的中文关键词列表
_ZH_SECTION_KEYWORDS: dict[str, list[str]] = {
    "abstract": ["摘要"],
    "introduction": ["绪论", "引言", "研究背景", "前言"],
    "method": ["方法", "模型", "算法", "理论", "基础理论", "技术路线", "研究方法"],
    "experiment": ["实验", "仿真", "试验", "验证", "实证"],
    "result": ["结果", "结论与分析", "结果分析", "性能分析", "讨论"],
    "conclusion": ["结论", "总结", "展望", "结束语"],
}

# 中文章节标题行正则：匹配 "第X章 ..." 或 "一、..." 或纯数字 "1 引言" 等
_ZH_CHAPTER_RE = re.compile(
    r"^(第\s*[一二三四五六七八九十百\d]+\s*章\s*|"
    r"[一二三四五六七八九十]+\s*[、．.]\s*|"
    r"\d+\s+[\u4e00-\u9fff])"
)


def _cache_path(paper_key: str) -> Path:
    import hashlib

    key = hashlib.md5(paper_key.encode()).hexdigest()[:16]
    return _PARSED_CACHE_DIR / f"{key}.json"


def _load_cache(paper_key: str) -> dict | None:
    p = _cache_path(paper_key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_cache(paper_key: str, data: dict) -> None:
    try:
        _cache_path(paper_key).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("解析结果缓存写入失败: %s", e)


def _extract_sections(full_text: str) -> dict[str, str]:
    """
    按章节标题切分全文，提取各关键章节内容（英文论文）。
    每个章节最多保留 2000 字。
    """
    lines = full_text.split("\n")
    sections: dict[str, str] = {k: "" for k in _SECTION_PATTERNS}

    current_section: str | None = None
    current_buf: list[str] = []

    def _flush():
        nonlocal current_section, current_buf
        if current_section and current_buf:
            text = " ".join(current_buf).strip()
            if len(text) > len(sections[current_section]):
                sections[current_section] = text[:2000]
        current_buf = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        matched_section: str | None = None
        for sec, patterns in _SECTION_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, line_stripped, re.IGNORECASE):
                    # 标题行通常较短（< 80 字符）
                    if len(line_stripped) < 80:
                        matched_section = sec
                        break
            if matched_section:
                break

        if matched_section:
            _flush()
            current_section = matched_section
        elif current_section:
            current_buf.append(line_stripped)

    _flush()
    return sections


def _match_zh_section(line: str) -> str | None:
    """
    判断一行是否是中文章节标题，返回对应的 section key，否则返回 None。
    策略：
      1. 行匹配章节标题格式（第X章 / 数字+中文 / 中文数字+、）且含关键词，或
      2. 行本身就是纯关键词（如 "摘要"、"结论"、"绪论"）
    """
    # 纯关键词行（如 "摘要"、"结论"）
    for sec, keywords in _ZH_SECTION_KEYWORDS.items():
        for kw in keywords:
            if line.strip() == kw:
                return sec

    # 章节标题格式 + 关键词
    if not _ZH_CHAPTER_RE.match(line):
        return None
    for sec, keywords in _ZH_SECTION_KEYWORDS.items():
        for kw in keywords:
            if kw in line:
                return sec
    return None


def _merge_split_lines(lines: list[str]) -> list[str]:
    """
    合并被拆分的单字行（如 '摘\\n要' -> '摘要'，'结\\n论' -> '结论'）。
    当连续若干行每行只有1-2个字符时，合并为一行。
    """
    merged: list[str] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buf:
                merged.append("".join(buf))
                buf = []
            continue
        # 单字或双字行，可能是被拆开的标题
        if len(stripped) <= 2 and re.search(r"[\u4e00-\u9fff]", stripped):
            buf.append(stripped)
        else:
            if buf:
                merged.append("".join(buf))
                buf = []
            merged.append(stripped)
    if buf:
        merged.append("".join(buf))
    return merged


def _is_toc_line(line: str) -> bool:
    """判断是否是目录行（含省略号/虚线+页码）"""
    return bool(re.search(r"[.·…]{4,}", line) or re.search(r"\.{3,}\s*\d+\s*$", line))


def _is_header_repeated(line: str, header_counts: dict, threshold: int = 3) -> bool:
    """
    页眉去重：同一行出现超过 threshold 次，认为是重复页眉。
    第一次和第二次出现是正常的（目录+章首），超过则是每页都有的页眉。
    """
    header_counts[line] = header_counts.get(line, 0) + 1
    return header_counts[line] > threshold


def _extract_sections_zh(full_text: str) -> dict[str, str]:
    """
    中文学术论文章节提取。
    识别 "第X章 XXX" / "摘要" / "结论" 等格式的大标题，按关键词映射到6个标准章节。
    每个章节最多保留 3000 字。

    策略：
    - 跳过目录行（含省略号+页码）
    - 跳过出现超过3次的重复页眉行
    - 每切换到新章节时，允许覆盖旧内容（取最长的那份）
    """
    raw_lines = full_text.split("\n")
    lines = _merge_split_lines(raw_lines)

    sections: dict[str, str] = {k: "" for k in _ZH_SECTION_KEYWORDS}
    header_counts: dict[str, int] = {}

    current_section: str | None = None
    current_buf: list[str] = []

    def _flush():
        nonlocal current_section, current_buf
        if current_section and current_buf:
            text = "".join(current_buf).strip()
            if len(text) > len(sections[current_section]):
                sections[current_section] = text[:3000]
        current_buf = []

    for stripped in lines:
        if not stripped:
            continue

        # 跳过目录行
        if _is_toc_line(stripped):
            continue

        matched = _match_zh_section(stripped)
        if matched:
            # 页眉去重：出现次数太多的短行是页眉，不触发章节切换
            if _is_header_repeated(stripped, header_counts, threshold=2):
                continue
            _flush()
            current_section = matched
        elif current_section:
            current_buf.append(stripped)

    _flush()
    return sections


def _sliding_window_fallback(
    full_text: str, window: int = 2000, step: int = 1500
) -> str:
    """
    章节提取失败时的兜底：全文滑窗，取前 _MAX_CHARS 字符。
    直接截断全文，保证喂给 LLM 的内容连贯。
    """
    return full_text[:_MAX_CHARS]


def parse_pdf(pdf_path: Path, paper_key: str) -> dict:
    """
    解析 PDF 文件，提取全文和章节结构。
    自动检测中英文论文，选择对应的章节提取策略。

    Args:
        pdf_path:  本地 PDF 文件路径
        paper_key: 论文唯一标识（用于缓存）

    Returns:
        解析结果字典
    """
    # 命中缓存
    cached = _load_cache(paper_key)
    if cached:
        logger.info("PDF 解析命中缓存: %s", paper_key[:30])
        return cached

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF 未安装，请运行 uv add pymupdf")
        return _fallback_result("PyMuPDF 未安装")

    try:
        doc = fitz.open(str(pdf_path))
        pages_text: list[str] = []
        for page in doc:
            pages_text.append(page.get_text())  # type: ignore[attr-defined]
        doc.close()
    except Exception as e:
        logger.warning("PDF 打开/读取失败: %s — %s", pdf_path, e)
        return _fallback_result(f"PDF 读取失败: {e}")

    full_text = "\n".join(pages_text)
    char_count = len(full_text)

    if char_count < 200:
        logger.warning("PDF 提取文本过短（%d 字），可能是扫描件或加密文件", char_count)
        return _fallback_result("PDF 文本过短，可能是扫描件或加密文件")

    # 检测是否是中文论文：中文字符占比超过 20% 视为中文
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", full_text[:5000]))
    is_chinese = zh_chars / max(len(full_text[:5000]), 1) > 0.2

    if is_chinese:
        logger.info("检测到中文论文，使用中文章节提取策略")
        sections = _extract_sections_zh(full_text)
    else:
        sections = _extract_sections(full_text)

    # 全文截断：优先拼合有效章节，拼不满再滑窗兜底
    section_order = [
        "abstract",
        "introduction",
        "method",
        "experiment",
        "result",
        "conclusion",
    ]
    combined = "\n\n".join(
        f"[{sec.upper()}]\n{sections[sec]}"
        for sec in section_order
        if sections[sec].strip()
    )
    if len(combined) < 500:
        # 章节提取失败，退回全文滑窗兜底
        logger.warning("章节提取失败（combined=%d字），退回全文截断", len(combined))
        combined = _sliding_window_fallback(full_text)

    result = {
        "full_text": combined[:_MAX_CHARS],
        "sections": sections,
        "page_count": len(pages_text),
        "char_count": char_count,
        "source": "pdf",
        "is_chinese": is_chinese,
    }

    _save_cache(paper_key, result)
    logger.info(
        "PDF 解析完成: %d 页 / %d 字符 / 中文=%s / 章节 %s",
        len(pages_text),
        char_count,
        is_chinese,
        [k for k, v in sections.items() if v],
    )
    return result


def make_fallback_from_abstract(abstract: str, tldr: str = "") -> dict:
    """当没有 PDF 时，用摘要构造兜底结果。"""
    text = abstract.strip()
    if tldr:
        text = f"[TLDR]\n{tldr}\n\n[ABSTRACT]\n{text}"
    return {
        "full_text": text,
        "sections": {
            "abstract": abstract.strip(),
            "introduction": "",
            "method": "",
            "experiment": "",
            "result": "",
            "conclusion": "",
        },
        "page_count": 0,
        "char_count": len(text),
        "source": "abstract_fallback",
    }


def _fallback_result(reason: str) -> dict:
    return {
        "full_text": "",
        "sections": {k: "" for k in _SECTION_PATTERNS},
        "page_count": 0,
        "char_count": 0,
        "source": f"error: {reason}",
    }
