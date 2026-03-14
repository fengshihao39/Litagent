"""
PDF 全文解析模块
流程：PDF → Layout Analysis → Block Detection → Section Detection → Text Reconstruction

专门针对学术论文双栏布局优化
"""

import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import fitz  # pymupdf


@dataclass
class TextBlock:
	"""页面上的一个文字块"""

	x0: float
	y0: float
	x1: float
	y1: float
	text: str
	page: int
	block_type: str = "text"

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
	level: int = 1


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

SECTION_HEADING_RE = re.compile(
	r"^(?:(?:[IVX]+|[0-9]+(?:\.[0-9]+)?)[\.\s]+)?([A-Z][A-Za-z0-9\s\-]{2,60})$"
)


def load_pdf_from_url(url: str) -> Optional[bytes]:
	"""下载 PDF，返回字节流"""
	try:
		req = urllib.request.Request(
			url,
			headers={
				"User-Agent": "StarfireAgent/1.0 (mailto:25209100302@stu.xidian.edu.cn)",
			},
		)
		with urllib.request.urlopen(req, timeout=30) as resp:
			return resp.read()
	except Exception:
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

	raw_blocks = _layout_analysis(doc)
	classified = _block_detection(raw_blocks, doc)
	sections_raw = _section_detection(classified)
	sections = _text_reconstruction(sections_raw)

	doc.close()

	target = _filter_target_sections(sections)

	full_text = "\n\n".join(
		f"[{title}]\n{content}" for title, content in target.items()
	)

	return {
		"sections": target,
		"full_text": full_text,
		"error": "",
	}


def _layout_analysis(doc: fitz.Document) -> List[TextBlock]:
	"""
	提取每页所有文字块及其坐标
	使用 pymupdf 的 get_text("dict") 获取精确坐标
	"""
	all_blocks: List[TextBlock] = []

	for page_num, page in enumerate(doc):
		page_dict = page.get_text("dict")
		page_height = page.rect.height

		for block in page_dict.get("blocks", []):
			if block.get("type") != 0:
				continue

			bbox = block.get("bbox", (0, 0, 0, 0))
			x0, y0, x1, y1 = bbox

			lines = block.get("lines", [])
			if not lines:
				continue

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
			if y1 < page_height * 0.05 or y0 > page_height * 0.95:
				tb.block_type = "header_footer"

			all_blocks.append(tb)

	return all_blocks


def _block_detection(blocks: List[TextBlock], doc: fitz.Document) -> List[TextBlock]:
	"""
	分类每个文字块，并处理双栏布局。
	"""
	if not blocks:
		return blocks

	page_width = doc[0].rect.width
	page_mid = page_width / 2

	result = []
	for tb in blocks:
		if tb.block_type == "header_footer":
			result.append(tb)
			continue

		text = tb.text.strip()

		if re.match(r"^(Fig\.|Figure|Table)\s*\d", text, re.IGNORECASE):
			tb.block_type = "figure_caption"
			result.append(tb)
			continue

		if _is_formula_block(text):
			tb.block_type = "formula"
			result.append(tb)
			continue

		if _is_section_heading(text):
			tb.block_type = "section_heading"
			result.append(tb)
			continue

		if tb.center_x < page_mid:
			tb.block_type = "text_left"
		else:
			tb.block_type = "text_right"

		result.append(tb)

	result = _sort_two_column(result)
	return result


def _is_formula_block(text: str) -> bool:
	math_symbols = set("∑∏∫∂∇αβγδεζηθλμνξπρστφχψω±×÷≤≥≠≈∞")
	if len(text) < 80 and any(c in math_symbols for c in text):
		return True
	if len(text) < 60 and text.count("_") + text.count("^") + text.count("{") > 3:
		return True
	return False


def _is_section_heading(text: str) -> bool:
	if len(text) > 80 or len(text) < 3:
		return False
	if text.endswith(".") and len(text) > 20:
		return False
	return bool(SECTION_HEADING_RE.match(text.strip()))


def _sort_two_column(blocks: List[TextBlock]) -> List[TextBlock]:
	"""
	双栏排序：按页码分组，每页内按阅读顺序重排。
	"""
	sorted_result = []
	blocks_by_page: Dict[int, List[TextBlock]] = {}
	for b in blocks:
		blocks_by_page.setdefault(b.page, []).append(b)

	for page_num in sorted(blocks_by_page.keys()):
		page_blocks = blocks_by_page[page_num]
		page_blocks.sort(key=lambda b: (b.y0, b.x0))

		band_threshold = 5.0
		bands: List[List[TextBlock]] = []
		current_band: List[TextBlock] = []

		for b in page_blocks:
			if not current_band:
				current_band.append(b)
			else:
				prev_y = current_band[-1].y0
				if abs(b.y0 - prev_y) <= band_threshold:
					current_band.append(b)
				else:
					bands.append(current_band)
					current_band = [b]
		if current_band:
			bands.append(current_band)

		for band in bands:
			band.sort(key=lambda b: b.x0)
			sorted_result.extend(band)

	return sorted_result


def _section_detection(blocks: List[TextBlock]) -> List[Tuple[str, List[TextBlock]]]:
	"""识别章节边界。"""
	sections: List[Tuple[str, List[TextBlock]]] = []
	current_title = "preamble"
	current_blocks: List[TextBlock] = []

	for block in blocks:
		if block.block_type == "section_heading":
			if current_blocks:
				sections.append((current_title, current_blocks))
			current_title = block.text.strip()
			current_blocks = []
		else:
			if block.block_type not in ("header_footer",):
				current_blocks.append(block)

	if current_blocks:
		sections.append((current_title, current_blocks))

	return sections


def _text_reconstruction(
	sections_raw: List[Tuple[str, List[TextBlock]]],
) -> Dict[str, str]:
	"""重建每个章节的连贯文本。"""
	result: Dict[str, str] = {}

	for title, blocks in sections_raw:
		parts = []
		for block in blocks:
			if block.block_type == "figure_caption":
				continue
			if block.block_type == "formula":
				parts.append(f"[FORMULA: {block.text}]")
				continue
			text = _clean_text(block.text)
			if text:
				parts.append(text)

		merged = _merge_lines(parts)
		result[title] = merged

	return result


def _clean_text(text: str) -> str:
	text = re.sub(r"(\w+)-\s+(\w+)", r"\1\2", text)
	text = " ".join(text.split())
	return text.strip()


def _merge_lines(parts: List[str]) -> str:
	if not parts:
		return ""

	lines: List[str] = []
	buffer = ""
	for part in parts:
		if not buffer:
			buffer = part
			continue

		if len(buffer) < 60 or buffer.endswith("-"):
			buffer = f"{buffer} {part}".replace("- ", "")
		else:
			lines.append(buffer)
			buffer = part

	if buffer:
		lines.append(buffer)

	return "\n".join(lines)


def _filter_target_sections(sections: Dict[str, str]) -> Dict[str, str]:
	"""只保留目标章节，跳过不需要的部分。"""
	result: Dict[str, str] = {}

	for title, content in sections.items():
		title_lower = title.lower().strip()
		if any(skip in title_lower for skip in SKIP_SECTIONS):
			continue
		if any(target in title_lower for target in TARGET_SECTIONS):
			result[title] = content

	if not result:
		return sections

	return result
