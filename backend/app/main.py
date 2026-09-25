"""FastAPI 应用装配。

- 统一错误体：code / message / request_id（§5.3）；
- 每个请求带 X-Request-Id，日志与错误可关联；
- 启动时建表并同步知识卡片（生产用 alembic 迁移 + 单独 seed 步骤）。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import api_router
from .config import get_settings
from .errors import AppError
from .logging_config import configure_logging

logger = logging.getLogger("chai_jing")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.env)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "拆镜学原型后端：上传参考视频 -> 拆解（镜头边界/关键帧/台词/景别/画面描述）-> 选择学习目标 -> "
            "生成可完成的学习任务 -> 提交作品 -> 结构差异与证据化反馈。"
            "所有对外部模型的调用都发生在服务端。"
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-Analysis-Version"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    def _error(status: int, code: str, message: str, request: Request, details=None) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", ""),
                "details": details,
            },
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("业务异常 %s: %s", exc.code, exc.message)
        return _error(exc.status_code, exc.code, exc.message, request, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "validation_error", "请求参数不合法", request, exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return _error(exc.status_code, code, str(exc.detail), request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常")
        return _error(500, "internal_error", "服务端内部错误", request)

    app.include_router(api_router, prefix=settings.api_prefix)

    static_dir = Path(__file__).resolve().parent / "static"

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "api_prefix": settings.api_prefix,
            "docs": "/docs",
            "demo": "/demo",
            "health": settings.api_prefix + "/healthz",
        }

    @app.get("/demo", include_in_schema=False)
    def demo_page() -> FileResponse:
        """零构建依赖的简版演示界面（与 Next.js 前端功能等价的最小子集）。"""

        return FileResponse(static_dir / "demo.html", media_type="text/html; charset=utf-8")

    @app.on_event("startup")
    def _startup() -> None:
        from .db import init_db

        try:
            init_db()
        except Exception as exc:  # noqa: BLE001 - 启动不应因迁移缺失直接崩溃
            logger.warning("数据库初始化失败：%s", exc)
        try:
            from .learning.knowledge import sync_knowledge_cards

            count = sync_knowledge_cards()
            logger.info("知识卡片已同步：%s 张", count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识卡片同步失败：%s", exc)

    return app


app = create_app()
