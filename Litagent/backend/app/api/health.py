"""
Litagent - FastAPI 后端健康检查接口
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """健康检查接口。

    Returns:
        dict: 返回含有版本号的健康检查结果。
    """
    return {"status": "ok", "service": "Litagent 后端", "version": "0.1.0"}
