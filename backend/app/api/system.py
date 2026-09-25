"""健康检查与元信息。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from ..config import get_settings
from ..db import get_engine
from ..deps import DbSession
from ..learning.intents import intent_options
from ..learning.knowledge import get_knowledge_base
from ..learning.tasks import LEVELS
from ..media.ffmpeg import binaries_available
from ..models import Job
from ..pipeline.schema import analysis_json_schema

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="存活探针")
def healthz() -> dict:
    settings = get_settings()
    db_status = "ok"
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        db_status = "error: " + type(exc).__name__
    ffmpeg_ok, ffprobe_ok = binaries_available()
    storage_status = "ok"
    if settings.healthcheck_include_storage:
        try:
            root = settings.storage_root
            root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            storage_status = "error: " + type(exc).__name__
    backlog = 0
    try:
        from ..db import session_scope

        with session_scope() as session:
            backlog = int(
                session.execute(select(func.count()).select_from(Job).where(Job.status == "queued")).scalar() or 0
            )
    except Exception:  # noqa: BLE001
        backlog = -1
    status = "ok" if db_status == "ok" and ffmpeg_ok and ffprobe_ok else "degraded"
    return {
        "status": status,
        "database": db_status,
        "storage": storage_status,
        "ffmpeg": ffmpeg_ok,
        "ffprobe": ffprobe_ok,
        "worker_backlog": backlog,
        "versions": {
            "prompt": settings.prompt_version,
            "schema": settings.schema_version,
            "knowledge": settings.knowledge_version,
            "pipeline": settings.pipeline_version,
            "app": "0.1.0",
        },
    }


@router.get("/readyz", summary="就绪探针")
def readyz(db: DbSession) -> dict:
    settings = get_settings()
    kb = get_knowledge_base()
    return {
        "ready": True,
        "database": settings.resolved_database_url.split("://")[0],
        "storage_backend": settings.storage_backend,
        "knowledge_cards": len(kb.cards),
        "multimodal_provider": settings.multimodal_provider,
        "asr_provider": settings.asr_provider,
        "queue_backend": settings.queue_backend,
    }


@router.get("/meta", summary="学习意图、任务级别与版本元信息")
def meta() -> dict:
    settings = get_settings()
    kb = get_knowledge_base()
    return {
        "intents": intent_options(),
        "task_levels": [
            {
                "key": key,
                "label": value["label"],
                "fixed_constraint": value["fixed_constraint"],
                "learner_change": value["learner_change"],
                "evaluation_focus": value["evaluation_focus"],
            }
            for key, value in LEVELS.items()
        ],
        "versions": {
            "prompt": settings.prompt_version,
            "schema": settings.schema_version,
            "knowledge": kb.version,
            "pipeline": settings.pipeline_version,
        },
        "knowledge_card_count": len(kb.cards),
        "providers": {
            "multimodal": settings.multimodal_provider,
            "multimodal_model_id": settings.multimodal_model_id,
            "asr": settings.asr_provider,
            "storage": settings.storage_backend,
            "queue": settings.queue_backend,
        },
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "min_duration_ms": settings.min_duration_ms,
            "max_duration_ms": settings.max_duration_ms,
            "max_height": settings.max_height,
            "signed_url_ttl_seconds": settings.signed_url_ttl_seconds,
            "max_frames_per_asset": settings.max_frames_per_asset,
        },
        "disclosure": "未接入多模态模型时，分析结果标记 provider=offline，仅为可核对的确定性统计，不含画面语义判断。",
    }


@router.get("/meta/analysis-schema", summary="分析结果 JSON Schema")
def analysis_schema() -> dict:
    return analysis_json_schema()
