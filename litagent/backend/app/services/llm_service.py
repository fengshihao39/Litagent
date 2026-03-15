"""
Litagent - LLM 对接服务
"""

from openai import OpenAI

from litagent.backend.app.core.config import get_deepseek_api_key

_client = OpenAI(
    api_key=get_deepseek_api_key(),
    base_url="https://api.deepseek.com",
)


def _call_deepseek(query: str) -> str:
    prompt = """你的任务是，将用户的输入转换为可在搜索引擎中输入的关键词列表。

你的返回必须是英文。如果用户输入了中文或其他语言，你也必须以英文回复。确保专有名词的翻译正确。
你必须返回且仅返回关键词列表，不要在前面或后面追加额外信息。不要加入 emoji 等无关内容。
确保返回的关键词列表是专业、准确的学术搜索关键词。
使用英文半角逗号 `,` 分隔关键词内容。
"""
    messages = []
    if prompt:
        messages.append({"role": "user", "content": prompt})
    messages.append({"role": "user", "content": query})

    resp = _client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        max_tokens=400,
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


def get_search_queries(user_input: str) -> list[str]:
    """使用 DeepSeek 生成查询条目。

    Args:
        user_input (str): 用户输入的内容。

    Returns:
        List[str]: 查询条目。
    """

    raw = user_input.strip()
    if not raw:
        return []
    try:
        response = _call_deepseek(raw)
        return [response or raw]
    except (ValueError, TypeError, RuntimeError):
        return [raw]
