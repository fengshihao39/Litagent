"""
Litagent - FastAPI 后端服务
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.health import router as health_router
from .api.search import router as search_router
from .core.config import get_app_version

app = FastAPI(
    title="Litagent 文献智能助手",
    description="西安电子科技大学第 37 届星火杯参赛项目",
    version=get_app_version(),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(search_router)
