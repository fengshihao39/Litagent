"""
Litagent - FastAPI 后端服务
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.analyze import router as analyze_router
from .api.health import router as health_router
from .api.history import router as history_router
from .api.paper import router as paper_router
from .api.search import router as search_router
from .core.config import get_app_version
from .core.storage import init_db

# 启动时初始化 SQLite 数据库（建表，幂等）
init_db()

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
app.include_router(history_router)
app.include_router(paper_router)
app.include_router(analyze_router)
