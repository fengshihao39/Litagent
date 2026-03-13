"""
查询翻译模块
功能：
  1. 检测查询语言（中文 / 英文）
  2. 中文关键词 → 英文专业术语（整体翻译，不拆词）
  3. 同义词/近义词扩展，生成多个搜索变体
  4. 输出用于 multi_search 的最终查询串

特别处理：
  - 中文专业词组（如"波达估计"）作为整体翻译，不拆字
  - 电子信息 / AI / 雷达信号处理领域优化
"""

import re
import json
from typing import List, Dict, Tuple

from openai import OpenAI

# ── DeepSeek 客户端 ───────────────────────────────────────

_client = OpenAI(
    api_key="xxxx",
    base_url="https://api.deepseek.com",
)

# ── 常用领域词汇预置映射（减少 API 调用，提高准确率）────────

DOMAIN_VOCAB: Dict[str, str] = {
    # 雷达 / 信号处理
    "波达方向": "Direction of Arrival (DOA)",
    "波达估计": "DOA estimation",
    "到达角": "angle of arrival (AOA)",
    "合成孔径雷达": "synthetic aperture radar (SAR)",
    "信号处理": "signal processing",
    "阵列信号处理": "array signal processing",
    "波束形成": "beamforming",
    "空间谱估计": "spatial spectrum estimation",
    "目标检测": "target detection",
    "目标识别": "target recognition",
    "杂波": "clutter",
    "干扰抑制": "interference suppression",
    "自适应滤波": "adaptive filtering",
    "卡尔曼滤波": "Kalman filter",
    "快速傅里叶变换": "FFT",
    "功率谱密度": "power spectral density",
    "多路径": "multipath",
    "稀疏恢复": "sparse recovery",
    "压缩感知": "compressed sensing",
    "MUSIC算法": "MUSIC algorithm",
    "ESPRIT": "ESPRIT",
    # 人工智能 / 机器学习
    "深度学习": "deep learning",
    "神经网络": "neural network",
    "卷积神经网络": "convolutional neural network (CNN)",
    "循环神经网络": "recurrent neural network (RNN)",
    "注意力机制": "attention mechanism",
    "变换器": "transformer",
    "自监督学习": "self-supervised learning",
    "迁移学习": "transfer learning",
    "强化学习": "reinforcement learning",
    "生成对抗网络": "generative adversarial network (GAN)",
    "大语言模型": "large language model (LLM)",
    "知识蒸馏": "knowledge distillation",
    "目标分类": "object classification",
    "语义分割": "semantic segmentation",
    "自然语言处理": "natural language processing (NLP)",
    # 通用
    "优化": "optimization",
    "鲁棒性": "robustness",
    "实时": "real-time",
    "低复杂度": "low complexity",
    "高分辨率": "high resolution",
    "多目标": "multi-target",
    "联合": "joint",
}


# ── 语言检测 ─────────────────────────────────────────────


def is_chinese(text: str) -> bool:
    """判断文本是否主要是中文"""
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return chinese_chars > len(text) * 0.2


# ── 预置词汇替换 ─────────────────────────────────────────


def apply_domain_vocab(text: str) -> Tuple[str, List[str]]:
    """
    对中文查询应用预置词汇映射
    返回 (替换后文本, 已替换的词汇对列表)
    """
    replacements = []
    result = text
    for zh, en in DOMAIN_VOCAB.items():
        if zh in result:
            result = result.replace(zh, en)
            replacements.append(f"{zh} → {en}")
    return result, replacements


# ── DeepSeek 翻译 + 扩展 ─────────────────────────────────


def translate_and_expand(query: str) -> Dict:
    """
    主函数：翻译中文查询并扩展同义词
    返回：
    {
        "original": str,           # 原始查询
        "translated": str,         # 主翻译结果
        "variants": [str, ...],    # 搜索变体（含同义词扩展）
        "language": "zh" | "en",
        "notes": str               # 翻译说明
    }
    """
    original = query.strip()

    if not is_chinese(original):
        # 英文查询：只做同义词扩展
        variants = _expand_english_query(original)
        return {
            "original": original,
            "translated": original,
            "variants": variants,
            "language": "en",
            "notes": "英文查询，已扩展同义词变体",
        }

    # 中文查询：先做预置词汇替换，再用 DeepSeek 处理剩余部分
    pre_translated, replacements = apply_domain_vocab(original)

    prompt = f"""你是电子信息和人工智能领域的专业翻译，请完成以下任务：

原始中文查询：{original}
预处理后（已替换部分专业词汇）：{pre_translated}

任务：
1. 将整个查询翻译成英文学术搜索关键词（专业、准确，保留缩写）
2. 生成 2-3 个英文搜索变体（使用同义词或不同表达方式）
3. 简要说明关键翻译决策

重要提示：
- 专业术语应作为整体翻译，不要拆词（例如"波达方向估计"→"direction of arrival estimation"）
- 保持学术专业性
- 变体应涵盖不同缩写、全称等形式

请用 JSON 格式返回：
{{
  "translated": "主要翻译结果",
  "variants": ["变体1", "变体2", "变体3"],
  "notes": "翻译说明"
}}

只返回 JSON，不要其他内容。"""

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
        )
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)

        return {
            "original": original,
            "translated": result.get("translated", pre_translated),
            "variants": result.get("variants", [pre_translated]),
            "language": "zh",
            "notes": result.get("notes", ""),
            "domain_replacements": replacements,
        }

    except Exception as e:
        # 降级：使用预置词汇替换结果
        return {
            "original": original,
            "translated": pre_translated,
            "variants": [pre_translated],
            "language": "zh",
            "notes": f"API翻译失败，使用预置词汇替换: {e}",
            "domain_replacements": replacements,
        }


def _expand_english_query(query: str) -> List[str]:
    """对英文查询扩展同义词变体"""
    prompt = f"""Given this academic search query: "{query}"

Generate 2-3 alternative search query variants using synonyms or different phrasings.
Return a JSON array of strings. Example: ["variant 1", "variant 2"]
Only return the JSON array, nothing else."""

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        variants = json.loads(content)
        if isinstance(variants, list):
            return [query] + variants[:3]
    except Exception:
        pass
    return [query]


# ── 便捷函数：获取最佳搜索查询 ─────────────────────────


def get_search_queries(user_input: str) -> List[str]:
    """
    给定用户原始输入，返回用于搜索的查询串列表（主查询在前）
    这是对外暴露的主接口
    """
    result = translate_and_expand(user_input)
    queries = [result["translated"]] + [
        v for v in result["variants"] if v != result["translated"]
    ]
    # 去重保留顺序
    seen = set()
    unique = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


# ── 测试 ─────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        "波达方向估计",
        "深度学习目标检测",
        "MUSIC算法阵列信号处理",
        "transformer attention mechanism",
        "雷达信号杂波抑制算法",
    ]

    print("=== 测试 query_translator.py ===\n")

    for query in test_cases:
        print(f"输入: {query!r}")
        result = translate_and_expand(query)
        print(f"  语言: {result['language']}")
        print(f"  主翻译: {result['translated']}")
        print(f"  变体: {result['variants']}")
        if result.get("notes"):
            print(f"  说明: {result['notes']}")
        print()
