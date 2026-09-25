"""API 路由汇总。统一前缀 /api/v1。"""

from __future__ import annotations

from fastapi import APIRouter

from . import analyses, assets, auth, jobs, learning, projects, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(assets.router)
api_router.include_router(analyses.router)
api_router.include_router(jobs.router)
api_router.include_router(learning.router)
