"""
Agent 核心层
负责：
  - 维护多轮对话历史
  - 理解用户意图，决定调用哪个工具
  - 串联搜索 → 解析 → 对比 → 输出的完整工作流
  - 将结果保存到本地 output/ 目录
"""

import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional
from openai import OpenAI

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.multi_search import (
    multi_search,
    format_papers_list as multi_format_papers_list,
)
from tools.arxiv_search import format_papers_list
from tools.paper_analyzer import analyze_paper, generate_citations, format_analysis
from tools.query_translator import get_search_queries, is_chinese
from tools.paper_understanding import deep_analyze_papers
from tools.pdf_loader import parse_arxiv_paper

# ── API Key ───────────────────────────────────────────────
API_KEY = "xxx"

# ── 系统 Prompt ───────────────────────────────────────────
SYSTEM_PROMPT = """你是「星火文献 Agent」，西安电子科技大学专属的科研文献智能助手。
你专注于电子信息、人工智能、雷达与信号处理三大领域。

## 你的核心能力
1. **文献搜索**：根据用户描述的研究方向，同时在 arXiv、Semantic Scholar、IEEE Xplore、Crossref 四大平台精准检索相关论文
2. **深度解析**：对高相关性论文进行全文深度分析（自动下载PDF解析），提取核心贡献、方法、实验结果
3. **对比分析**：横向对比多篇论文，识别研究空白（Research Gap）
4. **引用生成**：自动生成 BibTeX / APA / MLA 格式引用
5. **综述草稿**：基于检索结果，生成结构化的文献综述段落
6. **中文支持**：支持中文关键词搜索（自动翻译为英文专业术语）

## 工作原则
- 所有学术观点必须有论文依据，禁止凭空捏造研究结论
- 论文标题、作者、arXiv ID 必须来自真实检索结果
- 输出使用 Markdown 格式，支持 LaTeX 公式（用 $公式$ 包裹）

## 意图识别规则
当用户输入时，你需要判断意图并回复对应 JSON 指令：

1. 用户想**搜索论文** → 只输出：
{"action": "search", "query": "搜索词（中英文均可）", "max_results": 8, "year_from": null}

   若用户指定时间范围（如"近5年"、"2020年以后"），year_from 填对应年份整数；否则填 null。

2. 用户想**解析某篇论文**（如"分析1"、"解析第2篇"）→ 只输出：
{"action": "analyze", "target": "序号"}

3. 用户想**对比多篇论文** → 只输出：
{"action": "compare", "targets": [1, 2, 3]}

4. 用户想**生成综述** → 只输出：
{"action": "survey", "topic": "综述主题"}

5. 用户想**获取引用格式** → 只输出：
{"action": "cite", "target": "序号", "format": "all"}

6. **普通对话** → 直接用中文回答，不输出 JSON

重要：意图 1-5 只输出纯 JSON，不加任何额外文字。"""


class LiteratureAgent:
    def __init__(self):
        self.client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
        self.history: List[Dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.paper_cache: Dict[int, Dict] = {}
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def chat(self, user_input: str) -> str:
        """接收用户输入，返回 Agent 响应"""
        self.history.append({"role": "user", "content": user_input})

        # 第一步：让模型判断意图
        intent_text = self._call_llm(temperature=0.1)

        # 第二步：尝试解析为 JSON 动作
        action = self._try_parse_action(intent_text)

        if action is None:
            # 普通对话，直接返回
            self.history.append({"role": "assistant", "content": intent_text})
            return intent_text

        # 第三步：执行工具
        result = self._dispatch(action)

        # 第四步：让模型把工具结果整理成友好回复
        self.history.append({"role": "assistant", "content": intent_text})
        self.history.append(
            {
                "role": "user",
                "content": f"[工具执行结果]\n{result}\n\n请基于以上结果，用友好的中文向用户展示，保持 Markdown 格式。",
            }
        )

        final_response = self._call_llm(temperature=0.5)
        self.history.append({"role": "assistant", "content": final_response})
        self.history.pop(-2)  # 清理内部提示

        return final_response

    def _dispatch(self, action: Dict) -> str:
        act = action.get("action")
        if act == "search":
            return self._do_search(action)
        elif act == "analyze":
            return self._do_analyze(action)
        elif act == "compare":
            return self._do_compare(action)
        elif act == "survey":
            return self._do_survey(action)
        elif act == "cite":
            return self._do_cite(action)
        else:
            return f"未知动作: {act}"

    def _do_search(self, action: Dict) -> str:
        query = action.get("query", "")
        max_results = action.get("max_results", 8)
        year_from = action.get("year_from")  # None 表示不过滤

        # Step 1: 查询翻译（中文 → 英文）
        search_queries = get_search_queries(query)
        primary_query = search_queries[0]
        if is_chinese(query):
            print(f"\n  [翻译] {query!r} → {primary_query!r}")

        print(f"\n  [多源搜索中] {primary_query} ...")
        papers = multi_search(
            primary_query, max_results=max_results, year_from=year_from
        )

        # 如果主查询结果不足，用变体补充
        if len(papers) < max_results // 2 and len(search_queries) > 1:
            print(f"  [补充搜索] 使用变体查询: {search_queries[1]}")
            extra = multi_search(
                search_queries[1], max_results=max_results, year_from=year_from
            )
            # 合并去重（简单按标题去重）
            existing_titles = {p.get("title", "").lower() for p in papers}
            for p in extra:
                if p.get("title", "").lower() not in existing_titles:
                    papers.append(p)
                    existing_titles.add(p.get("title", "").lower())
            papers = papers[:max_results]

        if not papers:
            return "搜索失败或未找到结果，请检查网络连接或更换关键词。"
        if papers and "error" in papers[0]:
            return f"搜索失败: {papers[0]['error']}"

        # Step 2: 深度分析（摘要评分 + 全文解析高分论文）
        print(f"  [理解阶段] 对 {len(papers)} 篇论文进行相关性评分...")
        papers = deep_analyze_papers(
            papers, primary_query, pdf_loader_func=parse_arxiv_paper
        )

        self.paper_cache = {i + 1: p for i, p in enumerate(papers)}
        self._save_json(papers, f"search_{primary_query[:30].replace(' ', '_')}")

        # Step 3: 格式化输出（含评分和深度总结）
        output = multi_format_papers_list(papers)

        # 追加深度分析摘要（仅对高分论文）
        deep_summaries = [
            (i + 1, p) for i, p in enumerate(papers) if p.get("deep_summary")
        ]
        if deep_summaries:
            output += "\n\n---\n## 深度分析摘要\n\n"
            for idx, paper in deep_summaries:
                ds = paper["deep_summary"]
                output += f"### [{idx}] {paper.get('title', '')}\n"
                if isinstance(ds, dict):
                    if ds.get("core_contribution"):
                        output += f"- **核心贡献**: {ds['core_contribution']}\n"
                    if ds.get("method_overview"):
                        output += f"- **方法概述**: {ds['method_overview']}\n"
                    if ds.get("key_results"):
                        output += f"- **主要结果**: {ds['key_results']}\n"
                    if ds.get("relevance_to_query"):
                        output += f"- **相关性**: {ds['relevance_to_query']}\n"
                else:
                    output += f"{ds}\n"
                output += "\n"

        return output

    def _do_analyze(self, action: Dict) -> str:
        target = action.get("target", "")
        paper = self._resolve_paper(target)
        if paper is None:
            return f"未找到论文「{target}」，请先搜索或提供正确序号。"
        print(f"\n  [解析中] {paper['title'][:60]}...")
        analyzed = analyze_paper(paper)
        for k, v in self.paper_cache.items():
            if v.get("arxiv_id") == paper.get("arxiv_id"):
                self.paper_cache[k] = analyzed
        self._save_markdown(format_analysis(analyzed), f"analysis_{paper['arxiv_id']}")
        return format_analysis(analyzed)

    def _do_compare(self, action: Dict) -> str:
        targets = action.get("targets", [])
        papers = [p for t in targets if (p := self._resolve_paper(str(t))) is not None]
        if len(papers) < 2:
            return "对比分析至少需要 2 篇论文，请先搜索并指定序号。"
        print(f"\n  [对比分析] 共 {len(papers)} 篇论文...")
        papers_info = "\n\n".join(
            [
                f"论文{i + 1}：{p['title']}\n摘要：{p['summary'][:400]}"
                for i, p in enumerate(papers)
            ]
        )
        prompt = f"""请对以下 {len(papers)} 篇论文进行横向对比分析：

{papers_info}

请输出：
1. **各论文核心方法对比表格**（Markdown 表格）
2. **共同研究背景**
3. **各自创新点差异**
4. **Research Gap 识别**：这些研究共同忽视了什么？未来可以从哪里突破？
5. **综合推荐**：如果做相关研究，最值得参考的是哪篇？为什么？"""
        result = self._call_llm_direct(prompt)
        self._save_markdown(result, "compare_analysis")
        return result

    def _do_survey(self, action: Dict) -> str:
        topic = action.get("topic", "")
        if not self.paper_cache:
            return "请先搜索相关论文，再生成综述。"
        papers_summary = "\n\n".join(
            [
                f"[{i}] {p['title']} ({p['published'][:4]})\n{p['summary'][:300]}"
                for i, p in self.paper_cache.items()
            ]
        )
        prompt = f"""基于以下论文，请为「{topic}」方向撰写一段学术综述段落（约600字）：

{papers_summary}

要求：
- 按照"研究背景 → 主要方向 → 代表性工作 → 现存不足"的结构组织
- 每个观点必须引用对应论文（用[序号]标注）
- 使用学术语气，适当使用 LaTeX 公式
- 最后附上引用的论文列表"""
        result = self._call_llm_direct(prompt)
        self._save_markdown(result, f"survey_{topic[:20].replace(' ', '_')}")
        return result

    def _do_cite(self, action: Dict) -> str:
        target = action.get("target", "")
        fmt = action.get("format", "all")
        paper = self._resolve_paper(target)
        if paper is None:
            return f"未找到论文「{target}」。"
        citations = generate_citations(paper)
        if fmt == "bibtex":
            return f"```bibtex\n{citations['bibtex']}\n```"
        elif fmt == "apa":
            return f"**APA:** {citations['apa']}"
        elif fmt == "mla":
            return f"**MLA:** {citations['mla']}"
        else:
            return (
                f"**BibTeX:**\n```bibtex\n{citations['bibtex']}\n```\n\n"
                f"**APA:** {citations['apa']}\n\n"
                f"**MLA:** {citations['mla']}"
            )

    def _call_llm(self, temperature: float = 0.5) -> str:
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=self.history,  # type: ignore
            temperature=temperature,
            timeout=60,
        )
        return response.choices[0].message.content or ""

    def _call_llm_direct(self, prompt: str, temperature: float = 0.5) -> str:
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[  # type: ignore
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            timeout=60,
        )
        return response.choices[0].message.content or ""

    def _try_parse_action(self, text: str) -> Optional[Dict]:
        text = text.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return None

    def _resolve_paper(self, target) -> Optional[Dict]:
        target = str(target).strip()
        try:
            idx = int(target)
            return self.paper_cache.get(idx)
        except ValueError:
            pass
        for p in self.paper_cache.values():
            if p.get("arxiv_id") == target:
                return p
        return None

    def _save_json(self, data: object, name: str) -> str:
        ts = datetime.now().strftime("%m%d_%H%M")
        path = os.path.join(self.output_dir, f"{ts}_{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def _save_markdown(self, content: str, name: str) -> str:
        ts = datetime.now().strftime("%m%d_%H%M")
        path = os.path.join(self.output_dir, f"{ts}_{name}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def clear_history(self):
        self.history = [self.history[0]]
        self.paper_cache = {}
        print("对话历史已清除。")
