"""
Litagent - FastAPI 后端健康检查接口
"""

from fastapi import APIRouter

from litagent.backend.app.core.config import get_app_version

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """健康检查接口。

    Returns:
        dict: 返回含有版本号的健康检查结果。
    """
    return {"status": "ok", "service": "Litagent 后端", "version": get_app_version()}
