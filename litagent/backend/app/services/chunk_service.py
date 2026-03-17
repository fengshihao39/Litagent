"""
Litagent - 论文 Chunk 切分服务

把 PDF 解析后的全文按段落 + 滑窗策略切成 chunks，供 RAG 检索使用。

Chunk 结构：
  {
    "chunk_id":   int,          # 顺序编号（0 起）
    "text":       str,          # chunk 正文
    "section":    str,          # 所属章节（abstract / introduction / method 等）
    "char_start": int,          # 在全文中的字符起始位置
    "char_end":   int,          # 在全文中的字符结束位置
    "order":      int,          # 在本 section 内的顺序
  }
"""

from __future__ import annotations

import re

# 每个 chunk 的目标字符数
_CHUNK_SIZE = 1000

# 相邻 chunk 的重叠字符数（保证语义连续）
_CHUNK_OVERLAP = 150

# 最短有效 chunk 字符数（过短的直接丢弃）
_MIN_CHUNK_CHARS = 80

# 章节名称到规范 key 的映射
_SECTION_LABELS = {
    "abstract": "abstract",
    "introduction": "introduction",
    "method": "method",
    "experiment": "experiment",
    "result": "result",
    "conclusion": "conclusion",
}


def _split_to_paragraphs(text: str) -> list[str]:
    """把文本按空行或句子边界切成段落列表。"""
    # 先按连续空行切分
    blocks = re.split(r"\n{2,}", text.strip())
    paragraphs = []
    for block in blocks:
        block = block.strip()
        if len(block) < _MIN_CHUNK_CHARS:
            continue
        paragraphs.append(block)
    return paragraphs


def _sliding_window(text: str, section: str, base_order: int) -> list[dict]:
    """
    对一段较长文本做滑窗切分。
    返回该段产生的所有 chunk（尚未赋全局 chunk_id）。
    """
    chunks = []
    start = 0
    order = base_order
    text_len = len(text)

    while start < text_len:
        end = min(start + _CHUNK_SIZE, text_len)
        # 尽量在句子边界截断（找最后一个句号/换行）
        if end < text_len:
            for sep in ("。", ". ", "\n", "! ", "? ", "！", "？"):
                pos = text.rfind(sep, start + _CHUNK_SIZE // 2, end)
                if pos != -1:
                    end = pos + len(sep)
                    break

        chunk_text = text[start:end].strip()
        if len(chunk_text) >= _MIN_CHUNK_CHARS:
            chunks.append(
                {
                    "text": chunk_text,
                    "section": section,
                    "char_start": start,
                    "char_end": end,
                    "order": order,
                }
            )
            order += 1

        # 下一个窗口从 (end - overlap) 开始
        next_start = end - _CHUNK_OVERLAP
        if next_start <= start:
            next_start = start + max(1, _CHUNK_SIZE - _CHUNK_OVERLAP)
        start = next_start

    return chunks


def build_chunks(parsed: dict) -> list[dict]:
    """
    把 parse_pdf() 的输出切成 chunks。

    Args:
        parsed: pdf_parser.parse_pdf() 的返回值，含 full_text 和 sections

    Returns:
        chunk 列表，每条包含 chunk_id / text / section / char_start / char_end / order
    """
    sections: dict[str, str] = parsed.get("sections") or {}
    full_text: str = parsed.get("full_text") or ""

    raw_chunks: list[dict] = []

    # 优先按章节切分（保留 section 语义）
    section_order = [
        "abstract",
        "introduction",
        "method",
        "experiment",
        "result",
        "conclusion",
    ]
    used_sections = set()

    for sec in section_order:
        sec_text = (sections.get(sec) or "").strip()
        if not sec_text:
            continue
        used_sections.add(sec)
        paragraphs = _split_to_paragraphs(sec_text)
        order = 0
        for para in paragraphs:
            if len(para) <= _CHUNK_SIZE:
                if len(para) >= _MIN_CHUNK_CHARS:
                    raw_chunks.append(
                        {
                            "text": para,
                            "section": sec,
                            "char_start": 0,
                            "char_end": len(para),
                            "order": order,
                        }
                    )
                    order += 1
            else:
                sub = _sliding_window(para, sec, order)
                raw_chunks.extend(sub)
                order += len(sub)

    # 如果章节提取不够（< 3 个有效 chunk），退回对 full_text 做滑窗
    if len(raw_chunks) < 3 and full_text:
        raw_chunks = _sliding_window(full_text, "full_text", 0)

    # 赋 chunk_id
    for i, chunk in enumerate(raw_chunks):
        chunk["chunk_id"] = i

    return raw_chunks


def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """
    把 chunks 列表格式化成适合喂给 LLM 的文本。
    每条 chunk 带编号和章节标签。
    """
    lines = []
    for c in chunks:
        sec = c.get("section", "").upper()
        cid = c.get("chunk_id", "?")
        lines.append(f"[片段 {cid} | {sec}]\n{c['text']}")
    return "\n\n---\n\n".join(lines)
