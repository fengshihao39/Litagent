"""
Litagent - FastAPI 后端搜索接口基类
"""


class ProviderBase:
    """搜索接口基类。"""

    name: str = "base"

    def search_papers(self, query: str, max_results: int = 8) -> list[dict]:
        """搜索文献的接口。

        这是一个基类，需要各个子接口的实现。

        Args:
            query (str): 搜索关键词。
            max_results (int, optional): 最大返回数量. Defaults to 8.

        Raises:
            NotImplementedError: 接口未实现。

        Returns:
            List[Dict]: 搜索结果。
        """
        raise NotImplementedError("search_papers must be implemented by providers")
