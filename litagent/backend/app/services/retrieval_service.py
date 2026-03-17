"""
Litagent - RAG 检索服务（DeepSeek 语义检索）

策略：用 DeepSeek chat 对所有 chunks 做语义相关度打分，选出 top-k 最相关片段。

为什么不用向量 embedding：
  DeepSeek 目前不提供 embedding 接口。
  用 LLM 做 reranker 在精度上优于简单向量检索，且对学术文本更鲁棒。

检索流程：
  1. 把所有 chunks 分批发给 DeepSeek，让模型对每个 chunk 打 0~10 的相关分
  2. 按分数排序，取 top_k
  3. 返回带分数的 chunk 列表

缓存策略：
  - chunk 列表缓存到 data/parsed/<paper_key>_chunks.json
  - 同一篇论文不重复切块
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from openai import OpenAI

from litagent.backend.app.core.config import get_deepseek_api_key
from litagent.backend.app.services.chunk_service import (
    build_chunks,
    format_chunks_for_prompt,
)

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=get_deepseek_api_key(),
    base_url="https://api.deepseek.com",
)

_PARSED_CACHE_DIR = Path(__file__).parents[5] / "data" / "parsed"
_PARSED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 每批最多传给 DeepSeek 打分的 chunk 数（避免单次 context 过长）
_SCORE_BATCH_SIZE = 10

# ── 缓存 ──────────────────────────────────────────────────────────────────────


def _chunks_cache_path(paper_key: str) -> Path:
    import hashlib

    key = hashlib.md5(paper_key.encode()).hexdigest()[:16]
    return _PARSED_CACHE_DIR / f"{key}_chunks.json"


def _load_chunks_cache(paper_key: str) -> list[dict] | None:
    p = _chunks_cache_path(paper_key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_chunks_cache(paper_key: str, chunks: list[dict]) -> None:
    try:
        _chunks_cache_path(paper_key).write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("chunks 缓存写入失败: %s", e)


# ── DeepSeek 打分检索 ─────────────────────────────────────────────────────────

_SCORE_SYSTEM_PROMPT = """\
你是一名科研文献分析专家。你将收到一批论文片段（每段有编号和章节标签），以及一个检索任务。
请对每个片段打分（0~10 整数），衡量它对完成检索任务的价值：
  10 = 非常相关，包含关键信息
  5  = 部分相关
  0  = 完全无关

只输出 JSON 格式，格式如下（不要输出任何其他内容）：
{"scores": {"0": 8, "1": 3, "2": 10, ...}}

其中 key 是片段编号（字符串），value 是分数（整数）。
"""


def _score_chunks_batch(
    chunks_batch: list[dict],
    task_description: str,
) -> dict[int, int]:
    """
    让 DeepSeek 对一批 chunks 打分。
    返回 {chunk_id: score} 字典。
    """
    # 构造片段描述
    fragment_lines = []
    for c in chunks_batch:
        cid = c["chunk_id"]
        sec = c.get("section", "").upper()
        text_preview = c["text"][:600]  # 每片段最多 600 字送给打分器
        fragment_lines.append(f"[片段 {cid} | {sec}]\n{text_preview}")

    fragments_text = "\n\n---\n\n".join(fragment_lines)
    user_content = f"检索任务：{task_description}\n\n论文片段：\n\n{fragments_text}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _SCORE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=300,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        scores_raw = data.get("scores") or {}
        return {int(k): int(v) for k, v in scores_raw.items()}
    except Exception as e:
        logger.warning("chunk 打分失败: %s", e)
        # 失败时给所有 chunk 打 5 分（中等），不影响流程
        return {c["chunk_id"]: 5 for c in chunks_batch}


def retrieve_top_chunks(
    chunks: list[dict],
    task_description: str,
    top_k: int = 8,
) -> list[dict]:
    """
    从 chunks 中检索出与 task_description 最相关的 top_k 个片段。

    Args:
        chunks:           所有 chunk 列表（来自 build_chunks）
        task_description: 检索目标描述，例如"提取该论文的核心方法和实验结论"
        top_k:            返回最相关的 chunk 数量

    Returns:
        按相关度降序排列的 chunk 列表（含 relevance_score 字段）
    """
    if not chunks:
        return []

    # 分批打分
    all_scores: dict[int, int] = {}
    for i in range(0, len(chunks), _SCORE_BATCH_SIZE):
        batch = chunks[i : i + _SCORE_BATCH_SIZE]
        batch_scores = _score_chunks_batch(batch, task_description)
        all_scores.update(batch_scores)

    # 给每个 chunk 附上分数
    scored = []
    for c in chunks:
        cid = c["chunk_id"]
        score = all_scores.get(cid, 0)
        scored.append({**c, "relevance_score": score})

    # 按分数降序，取 top_k
    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:top_k]


def get_or_build_chunks(parsed: dict, paper_key: str) -> list[dict]:
    """
    获取论文 chunks，优先读缓存。

    Args:
        parsed:    pdf_parser.parse_pdf() 的返回值
        paper_key: 论文唯一标识

    Returns:
        chunk 列表
    """
    cached = _load_chunks_cache(paper_key)
    if cached:
        logger.info("chunks 命中缓存: %s (%d 块)", paper_key[:30], len(cached))
        return cached

    chunks = build_chunks(parsed)
    _save_chunks_cache(paper_key, chunks)
    logger.info("chunks 已生成并缓存: %s (%d 块)", paper_key[:30], len(chunks))
    return chunks
