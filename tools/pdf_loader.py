"""
PDF 全文解析模块
流程：PDF → Layout Analysis → Block Detection → Section Detection → Text Reconstruction

专门针对学术论文双栏布局优化
"""

import io
import re
import urllib.request
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import fitz  # pymupdf


# ── 数据结构 ─────────────────────────────────────────────


@dataclass
class TextBlock:
    """页面上的一个文字块"""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    page: int
    block_type: str = "text"  # text / formula / figure / header / footer

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Section:
    """论文章节"""

    title: str
    content: str
    level: int = 1  # 1=主章节, 2=子章节


# ── 目标章节定义 ─────────────────────────────────────────

TARGET_SECTIONS = [
    "introduction",
    "method",
    "methods",
    "methodology",
    "proposed method",
    "approach",
    "framework",
    "architecture",
    "experiment",
    "experiments",
    "experimental",
    "results",
    "evaluation",
    "conclusion",
    "conclusions",
    "summary",
]

SKIP_SECTIONS = [
    "related work",
    "background",
    "references",
    "acknowledgment",
    "acknowledgements",
    "appendix",
    "bibliography",
]

# 章节标题正则：匹配 "1. Introduction" / "II. METHOD" / "4 Why Self-Attention" 等
# 允许连字符、数字子节编号（如 3.2 / 5.1）
SECTION_HEADING_RE = re.compile(
    r"^(?:(?:[IVX]+|[0-9]+(?:\.[0-9]+)?)[\.\s]+)?([A-Z][A-Za-z0-9\s\-]{2,60})$"
)


# ── 主入口 ───────────────────────────────────────────────


def load_pdf_from_url(url: str) -> Optional[bytes]:
    """下载 PDF，返回字节流"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "StarfireAgent/1.0 (mailto:xxx@stu.xidian.edu.cn)"
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        return None


def parse_paper_pdf(pdf_bytes: bytes) -> Dict:
    """
    完整 PDF 解析流程
    返回：{"sections": {name: text}, "full_text": str, "error": str}
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return {"sections": {}, "full_text": "", "error": f"PDF打开失败: {e}"}

    # Step 1: Layout Analysis — 获取页面尺寸和所有文字块坐标
    raw_blocks = _layout_analysis(doc)

    # Step 2: Block Detection — 分类文字块（正文/公式/图表/页眉页脚）
    classified = _block_detection(raw_blocks, doc)

    # Step 3: Section Detection — 识别章节边界
    sections_raw = _section_detection(classified)

    # Step 4: Text Reconstruction — 按阅读顺序重建文本
    sections = _text_reconstruction(sections_raw)

    doc.close()

    # 只保留目标章节
    target = _filter_target_sections(sections)

    full_text = "\n\n".join(
        f"[{title}]\n{content}" for title, content in target.items()
    )

    return {
        "sections": target,
        "full_text": full_text,
        "error": "",
    }


# ── Step 1: Layout Analysis ──────────────────────────────


def _layout_analysis(doc: fitz.Document) -> List[TextBlock]:
    """
    提取每页所有文字块及其坐标
    使用 pymupdf 的 get_text("dict") 获取精确坐标
    """
    all_blocks: List[TextBlock] = []

    for page_num, page in enumerate(doc):
        page_dict = page.get_text("dict")
        page_width = page.rect.width
        page_height = page.rect.height

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # 0=文字, 1=图片
                continue

            bbox = block.get("bbox", (0, 0, 0, 0))
            x0, y0, x1, y1 = bbox

            # 跳过空块
            lines = block.get("lines", [])
            if not lines:
                continue

            # 拼接块内所有文字
            text_parts = []
            for line in lines:
                for span in line.get("spans", []):
                    text_parts.append(span.get("text", ""))
            text = " ".join(text_parts).strip()

            if not text:
                continue

            tb = TextBlock(
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                text=text,
                page=page_num,
            )
            # 标记页眉页脚（位于页面顶部5%或底部5%）
            if y1 < page_height * 0.05 or y0 > page_height * 0.95:
                tb.block_type = "header_footer"

            all_blocks.append(tb)

    return all_blocks


# ── Step 2: Block Detection ──────────────────────────────


def _block_detection(blocks: List[TextBlock], doc: fitz.Document) -> List[TextBlock]:
    """
    分类每个文字块：
    - header_footer: 页眉页脚
    - formula: 数学公式（保留文本）
    - figure_caption: 图表标题
    - section_heading: 章节标题
    - text: 普通正文

    同时处理双栏布局：
    检测页面中线，判断每个块属于左栏还是右栏
    """
    if not blocks:
        return blocks

    # 获取第一页宽度作为参考
    page_width = doc[0].rect.width
    page_mid = page_width / 2

    result = []
    for tb in blocks:
        if tb.block_type == "header_footer":
            result.append(tb)
            continue

        text = tb.text.strip()

        # 检测图表标题（以 Figure/Table/Fig. 开头）
        if re.match(r"^(Fig\.|Figure|Table)\s*\d", text, re.IGNORECASE):
            tb.block_type = "figure_caption"
            result.append(tb)
            continue

        # 检测公式块（包含大量特殊符号，或短行含等号）
        if _is_formula_block(text):
            tb.block_type = "formula"
            result.append(tb)
            continue

        # 检测章节标题
        if _is_section_heading(text):
            tb.block_type = "section_heading"
            result.append(tb)
            continue

        # 标记双栏位置（用于后续排序）
        if tb.center_x < page_mid:
            tb.block_type = "text_left"
        else:
            tb.block_type = "text_right"

        result.append(tb)

    # 双栏排序：同页内，先左栏从上到下，再右栏从上到下
    result = _sort_two_column(result)

    return result


def _is_formula_block(text: str) -> bool:
    """判断是否为公式块"""
    # 短文本且含数学符号
    math_symbols = set("∑∏∫∂∇αβγδεζηθλμνξπρστφχψω±×÷≤≥≠≈∞")
    if len(text) < 80 and any(c in math_symbols for c in text):
        return True
    # 含大量花括号/下标符号的短行
    if len(text) < 60 and text.count("_") + text.count("^") + text.count("{") > 3:
        return True
    return False


def _is_section_heading(text: str) -> bool:
    """判断是否为章节标题"""
    # 长度限制
    if len(text) > 80 or len(text) < 3:
        return False
    # 不含句号（标题一般不以句子结尾）
    if text.endswith(".") and len(text) > 20:
        return False
    return bool(SECTION_HEADING_RE.match(text.strip()))


def _sort_two_column(blocks: List[TextBlock]) -> List[TextBlock]:
    """
    双栏排序：按页码分组，每页内按阅读顺序重排。
    策略：将块分成若干"水平带"（Y 方向上相近的块视为同一行带），
    同一带内先左后右；不同带按 Y 从上到下。
    这样可以保证跨栏的章节标题（全宽）和单栏正文都能正确排序。
    """
    sorted_result = []
    blocks_by_page: Dict[int, List[TextBlock]] = {}
    for b in blocks:
        blocks_by_page.setdefault(b.page, []).append(b)

    for page_num in sorted(blocks_by_page.keys()):
        page_blocks = blocks_by_page[page_num]

        # 先按 y0 粗排
        page_blocks.sort(key=lambda b: (b.y0, b.x0))

        # 分水平带：相邻两块 y0 差值 < 阈值则视为同一带
        BAND_THRESHOLD = 5.0
        bands: List[List[TextBlock]] = []
        current_band: List[TextBlock] = []

        for b in page_blocks:
            if not current_band:
                current_band.append(b)
            else:
                # 与当前带最后一块比较
                prev_y = current_band[-1].y0
                if abs(b.y0 - prev_y) <= BAND_THRESHOLD:
                    current_band.append(b)
                else:
                    bands.append(current_band)
                    current_band = [b]
        if current_band:
            bands.append(current_band)

        # 每个带内按 x0 从左到右排序（确保左栏先于右栏）
        for band in bands:
            band.sort(key=lambda b: b.x0)
            sorted_result.extend(band)

    return sorted_result


# ── Step 3: Section Detection ────────────────────────────


def _section_detection(blocks: List[TextBlock]) -> List[Tuple[str, List[TextBlock]]]:
    """
    识别章节边界，返回 [(章节名, [块列表]), ...]
    """
    sections: List[Tuple[str, List[TextBlock]]] = []
    current_title = "preamble"
    current_blocks: List[TextBlock] = []

    for block in blocks:
        if block.block_type == "section_heading":
            # 保存上一章节
            if current_blocks:
                sections.append((current_title, current_blocks))
            current_title = block.text.strip()
            current_blocks = []
        else:
            if block.block_type not in ("header_footer",):
                current_blocks.append(block)

    # 保存最后一章节
    if current_blocks:
        sections.append((current_title, current_blocks))

    return sections


# ── Step 4: Text Reconstruction ──────────────────────────


def _text_reconstruction(
    sections_raw: List[Tuple[str, List[TextBlock]]],
) -> Dict[str, str]:
    """
    重建每个章节的连贯文本
    处理：断行合并、公式标注、图表标题跳过
    """
    result: Dict[str, str] = {}

    for title, blocks in sections_raw:
        parts = []
        for block in blocks:
            if block.block_type == "figure_caption":
                continue  # 跳过图表标题
            if block.block_type == "formula":
                parts.append(f"[FORMULA: {block.text}]")
                continue
            text = _clean_text(block.text)
            if text:
                parts.append(text)

        # 合并段落：短行（可能是断行）和下一行拼接
        merged = _merge_lines(parts)
        result[title] = merged

    return result


def _clean_text(text: str) -> str:
    """清理文本：去除多余空格、修复连字符断词"""
    # 修复 PDF 连字符断词：如 "recog- nition" → "recognition"
    text = re.sub(r"(\w+)-\s+(\w+)", r"\1\2", text)
    # 去除多余空白
    text = " ".join(text.split())
    return text.strip()


def _merge_lines(parts: List[str]) -> str:
    """合并段落，保留段落边界"""
    if not parts:
        return ""
    result = []
    buffer = ""
    for part in parts:
        # 如果上一段不以句号结尾，且这段首字母小写，认为是同一段落的断行
        if buffer and not buffer[-1] in ".!?:" and part and part[0].islower():
            buffer += " " + part
        else:
            if buffer:
                result.append(buffer)
            buffer = part
    if buffer:
        result.append(buffer)
    return "\n\n".join(result)


# ── 过滤目标章节 ─────────────────────────────────────────


def _filter_target_sections(sections: Dict[str, str]) -> Dict[str, str]:
    """
    只保留目标章节及其子章节，跳过 Related Work / References 等。
    策略：
    - 记录当前"父章节"状态（是目标还是跳过）
    - 遇到一级章节标题时更新状态
    - 子章节（含小数点编号如3.1）继承父章节状态
    """
    result = {}
    in_target = False  # 当前是否处于目标章节内

    for title, content in sections.items():
        title_lower = title.strip().lower()

        # 判断是否是一级章节（不含子章节编号，如 "3.1"）
        is_top_level = not re.search(r"\d+\.\d+", title_lower)

        if is_top_level:
            # 重新判断父章节状态
            if any(skip in title_lower for skip in SKIP_SECTIONS):
                in_target = False
            elif title_lower == "preamble" or any(
                t in title_lower for t in TARGET_SECTIONS
            ):
                in_target = True
            else:
                # 不在目标也不在跳过列表 — 保守起见跳过
                in_target = False

        # 子章节继承父状态
        if in_target and content.strip():
            result[title] = content[:3000]  # 每章节最多3000字符

    return result


# ── 便捷函数：从 arXiv ID 直接解析 ──────────────────────


def parse_arxiv_paper(arxiv_id: str) -> Dict:
    """
    给定 arXiv ID，下载并解析 PDF
    返回解析结果，失败则返回 error 字段
    """
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    pdf_bytes = load_pdf_from_url(pdf_url)

    if pdf_bytes is None:
        return {"sections": {}, "full_text": "", "error": f"PDF下载失败: {arxiv_id}"}

    return parse_paper_pdf(pdf_bytes)


# ── 测试 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 用一篇真实 arXiv 论文测试
    TEST_ID = "1706.03762"  # Attention Is All You Need
    print(f"=== 测试 PDF 解析：arXiv:{TEST_ID} ===\n")
    print("下载中...")

    result = parse_arxiv_paper(TEST_ID)

    if result["error"]:
        print(f"错误: {result['error']}")
    else:
        print(f"解析成功，找到 {len(result['sections'])} 个目标章节：\n")
        for title, content in result["sections"].items():
            print(f"── {title} ──")
            print(content[:300])
            print("...\n")
