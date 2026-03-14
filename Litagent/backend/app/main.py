"""
星火文献 Agent - FastAPI 后端服务
提供 HTTP 接口供 Streamlit 前端调用
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.health import router as health_router
from .api.search import router as search_router

app = FastAPI(
	title="Litagent 文献智能助手",
	description="西安电子科技大学 · 第 37 届星火杯参赛项目",
	version="2.0.0",
)

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_methods=["*"],
	allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(search_router)
