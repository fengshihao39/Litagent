"""
Litagent - PDF 下载服务

负责把论文 PDF 下载到本地缓存目录 data/pdfs/。
支持来源：
  - arXiv（pdf_url 直接可用）
  - Semantic Scholar openAccessPdf
  - 其他任意有效 pdf_url

缓存策略：
  - 文件名 = paper_key 的 URL-safe hash + .pdf
  - 已存在则直接返回路径，不重复下载
  - 下载失败返回 None
"""

from __future__ import annotations

import hashlib
import logging
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录下的缓存目录
_PDF_CACHE_DIR = Path(__file__).parents[5] / "data" / "pdfs"
_PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 下载超时（秒）
_DOWNLOAD_TIMEOUT = 30

# arXiv 需要伪装 User-Agent，否则返回 403
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Litagent/1.0; mailto:25209100302@stu.xidian.edu.cn)"
    )
}


def _make_cache_key(paper_key: str) -> str:
    """把 paper_key 转成安全的文件名（md5 前16位）。"""
    return hashlib.md5(paper_key.encode()).hexdigest()[:16]


def _cache_path(paper_key: str) -> Path:
    return _PDF_CACHE_DIR / f"{_make_cache_key(paper_key)}.pdf"


def is_cached(paper_key: str) -> bool:
    """检查该论文 PDF 是否已缓存。"""
    return _cache_path(paper_key).exists()


def get_cache_path(paper_key: str) -> Path | None:
    """如果缓存存在则返回路径，否则返回 None。"""
    p = _cache_path(paper_key)
    return p if p.exists() else None


def download_pdf(pdf_url: str, paper_key: str) -> Path | None:
    """
    下载 PDF 到本地缓存。

    Args:
        pdf_url:   论文 PDF 的直链 URL
        paper_key: 唯一标识（DOI / abs_url / 标题截断）

    Returns:
        本地缓存路径；下载失败返回 None
    """
    if not pdf_url or not pdf_url.startswith("http"):
        logger.warning("无效的 pdf_url: %s", pdf_url)
        return None

    cache = _cache_path(paper_key)

    # 已缓存，直接复用
    if cache.exists():
        logger.info("PDF 已缓存，跳过下载: %s", cache.name)
        return cache

    logger.info("开始下载 PDF: %s -> %s", pdf_url, cache.name)

    try:
        req = urllib.request.Request(pdf_url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()

        # 简单校验：必须是 PDF 内容
        if not data.startswith(b"%PDF") and "pdf" not in content_type.lower():
            logger.warning(
                "下载内容不是 PDF (Content-Type: %s, 首字节: %s)",
                content_type,
                data[:8],
            )
            return None

        cache.write_bytes(data)
        logger.info("PDF 下载成功: %s (%.1f KB)", cache.name, len(data) / 1024)
        return cache

    except urllib.error.HTTPError as e:
        logger.warning("PDF 下载 HTTP 错误 %s: %s", e.code, pdf_url)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("PDF 下载失败: %s — %s", pdf_url, e)
        return None


def resolve_pdf_url(paper: dict) -> str:
    """
    从论文字典中提取最佳 pdf_url。

    优先级：
      1. paper["pdf_url"]（已有直链）
      2. arXiv arxiv_id 推导
      3. 其他来源没有稳定 PDF 入口 -> 返回空字符串
    """
    pdf_url = (paper.get("pdf_url") or "").strip()
    if pdf_url:
        return pdf_url

    arxiv_id = (paper.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}"

    return ""
