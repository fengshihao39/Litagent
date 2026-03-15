"""
Litagent - FastAPI 后端入口点
"""

import uvicorn

from litagent.backend.app.core.config import get_api_host, get_api_port


def main() -> None:
    """FastAPI 后端入口点。"""
    uvicorn.run(
        "Litagent.backend.app.main:app",
        host=get_api_host(),
        port=get_api_port(),
        reload=True,
    )


if __name__ == "__main__":
    main()
