"""Provider base interface."""

from typing import Dict, List


class ProviderBase:
    """Base provider interface for paper search."""

    name: str = "base"

    def search_papers(self, query: str, max_results: int = 8) -> List[Dict]:
        raise NotImplementedError("search_papers must be implemented by providers")
