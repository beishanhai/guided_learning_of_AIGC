"""分析：提交拆解任务、读取结果、人工修正边界、生成学习任务、导出。"""

from __future__ import annotations

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import select

from ..config import get_settings
from ..deps import CurrentUser, DbSession, owned_analysis, owned_asset, owned_project
from ..errors import Conflict, NotFound, SemanticError
from ..export.markdown import render_analysis_markdown
from ..learning.intents import build_shot_explanations, get_intent, intent_options
from ..learning.knowledge import get_knowledge_base
from ..learning.tasks import build_task
from ..models import Analysis, Asset, LearningTask, Project, Shot
from ..pipeline.schema import SHOT_SCALES
from ..queue import create_job, dispatch_job
from ..schemas import (
    AnalysisCreate,
    AnalysisOut,
    ExplanationsOut,
    JobCreatedOut,
    LearningTaskCreate,
    LearningTaskOut,
    ShotsPatchRequest,
)
from ..serializers import analysis_out, task_out

router = APIRouter(tags=["analyses"])


def _knowledge_index() -> dict:
    kb = get_knowledge_base()
    return {
        card.id: {"title": card.title, "topic": card.topic, "content": card.content, "source": card.source}
        for card in kb.cards.values()
    }


@router.post(
    "/projects/{project_id}/analyses",
    response_model=JobCreatedOut,
    status_code=202,
    summary="提交拆解任务（幂等：Idempotency-Key）",
)
def create_analysis(
    project_id: str,
    payload: AnalysisCreate,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    project = owned_project(db, project_id, user)
    asset = owned_asset(db, payload.asset_id, user)
    if asset.project_id != project.id:
        raise NotFound("素材不属于该项目")
    if asset.status != "ready":
        raise SemanticError("素材尚未通过服务端校验，不能提交分析", code="asset_not_ready")

    job, created = create_job(
        db,
        owner_id=user.id,
        job_type="analyze_asset",
        project_id=project.id,
        payload={
            "asset_id": asset.id,
            "intent": payload.intent,
            "kind": "reference",
            "generate_task": payload.generate_task,
        },
        idempotency_key=idempotency_key or "",
    )
    db.commit()
    if created:
        dispatch_job(job.id)
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "idempotent_replay": not created,
    }


@router.get("/analyses", summary="分析列表（按项目或状态过滤）")
def list_analyses(
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    stmt = select(Analysis).where(Analysis.owner_id == user.id).order_by(Analysis.created_at.desc()).limit(limit)
    if project_id:
        owned_project(db, project_id, user)
        stmt = stmt.where(Analysis.project_id == project_id)
    if kind:
        stmt = stmt.where(Analysis.kind == kind)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "asset_id": row.asset_id,
            "version": row.version,
            "kind": row.kind,
            "intent": row.intent,
            "status": row.status,
            "shot_count": len(row.shots),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut, summary="分析详情（分镜、解释、证据、版本）")
def get_analysis(analysis_id: str, db: DbSession, user: CurrentUser) -> dict:
    analysis = owned_analysis(db, analysis_id, user)
    return analysis_out(analysis, knowledge=_knowledge_index())


@router.get(
    "/analyses/{analysis_id}/explanations",
    response_model=ExplanationsOut,
    summary="按学习意图生成解释（事实时间线不变）",
)
def get_explanations(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
    intent: str = Query(default=""),
) -> dict:
    analysis = owned_analysis(db, analysis_id, user)
    chosen = intent or analysis.intent
    if chosen not in {item["key"] for item in intent_options()}:
        raise SemanticError("未知学习意图：" + chosen, code="unknown_intent")
    shots = [
        {
            "shot_ref": shot.shot_ref,
            "start_ms": shot.start_ms,
            "end_ms": shot.end_ms,
            "observation": shot.observation,
            "shot_scale": shot.shot_scale,
            "camera_motion": shot.camera_motion,
            "narrative_function": shot.narrative_function,
            "interpretation": shot.interpretation,
            "alternative": shot.alternative,
            "dialogue": shot.dialogue,
            "evidence": shot.evidence,
            "knowledge_ids": shot.knowledge_ids,
            "unknowns": shot.unknowns,
        }
        for shot in analysis.shots
    ]
    spec = get_intent(chosen)
    return {
        "analysis_id": analysis.id,
        "intent": chosen,
        "intent_label": spec.label,
        "fact_timeline_unchanged": True,
        "note": "同一份底层事实，切换意图只改变解释与练习（§1.1 / F05）",
        "explanations": build_shot_explanations(shots, chosen),
    }


@router.patch(
    "/analyses/{analysis_id}/shots",
    response_model=AnalysisOut,
    summary="人工修正镜头边界与标签（生成新版本）",
)
def patch_shots(analysis_id: str, payload: ShotsPatchRequest, db: DbSession, user: CurrentUser) -> dict:
    analysis = owned_analysis(db, analysis_id, user)
    # 乐观并发控制的对象是"该素材的分析谱系"，不是被请求的那一版本身：
    # 否则在 v2 上修正两次都会算出 v3，第二次会撞唯一键。
    latest = (
        db.execute(
            select(Analysis)
            .where(Analysis.asset_id == analysis.asset_id, Analysis.owner_id == user.id)
            .order_by(Analysis.version.desc())
        )
        .scalars()
        .first()
    )
    current_version = latest.version if latest is not None else analysis.version
    if payload.expected_version != current_version:
        raise Conflict(
            "分析版本已变化，请重新读取",
            details={"expected": payload.expected_version, "actual": current_version},
        )
    asset = db.get(Asset, analysis.asset_id)
    duration_ms = int(asset.duration_ms if asset else analysis.metrics.get("duration_ms") or 0)

    new_analysis = Analysis(
        asset_id=analysis.asset_id,
        project_id=analysis.project_id,
        owner_id=analysis.owner_id,
        version=current_version + 1,
        kind=analysis.kind,
        intent=analysis.intent,
        status="ready",
        model_id=analysis.model_id,
        prompt_version=analysis.prompt_version,
        knowledge_version=analysis.knowledge_version,
        schema_version=analysis.schema_version,
        pipeline_version=analysis.pipeline_version,
        supersedes_id=(latest.id if latest is not None else analysis.id),
        coverage={**(analysis.coverage or {}), "human_edited": True, "supersedes": analysis.id},
        transcript=analysis.transcript or {},
        media=analysis.media or {},
        metrics=analysis.metrics or {},
        unknowns=analysis.unknowns or {},
        review_status=payload.review_status,
        edited_by_user=True,
    )
    db.add(new_analysis)
    db.flush()

    patch_map = {item.shot_ref: item for item in payload.shots}
    for shot in analysis.shots:
        patch = patch_map.get(shot.shot_ref)
        start_ms = shot.start_ms
        end_ms = shot.end_ms
        if patch is not None:
            start_ms = patch.start_ms if patch.start_ms is not None else start_ms
            end_ms = patch.end_ms if patch.end_ms is not None else end_ms
        if end_ms <= start_ms or start_ms < 0 or (duration_ms and end_ms > duration_ms):
            raise SemanticError(
                "镜头 " + shot.shot_ref + " 的时间区间非法（必须在片长内且 end>start）",
                code="invalid_span",
            )
        scale = shot.shot_scale
        if patch is not None and patch.shot_scale:
            if patch.shot_scale not in SHOT_SCALES:
                raise SemanticError("未知景别枚举：" + patch.shot_scale, code="invalid_scale")
            scale = patch.shot_scale
        db.add(
            Shot(
                analysis_id=new_analysis.id,
                index=shot.index,
                shot_ref=shot.shot_ref,
                start_ms=int(start_ms),
                end_ms=int(end_ms),
                observation=(patch.observation if patch and patch.observation else shot.observation),
                shot_scale=scale,
                camera_motion=(patch.camera_motion if patch and patch.camera_motion else shot.camera_motion),
                interpretation=(patch.interpretation if patch and patch.interpretation else shot.interpretation),
                alternative=shot.alternative,
                narrative_function=(
                    patch.narrative_function if patch and patch.narrative_function else shot.narrative_function
                ),
                dialogue=shot.dialogue,
                transcript_segments=shot.transcript_segments or [],
                frame_keys=shot.frame_keys or [],
                evidence=shot.evidence or [],
                knowledge_ids=shot.knowledge_ids or [],
                unknowns=shot.unknowns or [],
                confidence=shot.confidence,
                review_status=(
                    patch.review_status if patch is not None and patch.review_status else payload.review_status
                ),
                source="human",
            )
        )
    db.commit()
    db.refresh(new_analysis)
    return analysis_out(new_analysis, knowledge=_knowledge_index())


@router.get("/analyses/{analysis_id}/versions", summary="版本历史（下游任务仍引用旧版本）")
def list_versions(analysis_id: str, db: DbSession, user: CurrentUser) -> dict:
    analysis = owned_analysis(db, analysis_id, user)
    rows = (
        db.execute(
            select(Analysis)
            .where(Analysis.asset_id == analysis.asset_id, Analysis.owner_id == user.id)
            .order_by(Analysis.version.asc())
        )
        .scalars()
        .all()
    )
    tasks = (
        db.execute(select(LearningTask).where(LearningTask.analysis_id.in_([row.id for row in rows])))
        .scalars()
        .all()
    )
    return {
        "analysis_id": analysis.id,
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "edited_by_user": row.edited_by_user,
                "supersedes_id": row.supersedes_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "learning_task_ids": [task.id for task in tasks if task.analysis_id == row.id],
            }
            for row in rows
        ],
    }


@router.post(
    "/analyses/{analysis_id}/learning-tasks",
    response_model=LearningTaskOut,
    status_code=201,
    summary="生成学习任务（模仿 / 变体 / 原创）",
)
def create_learning_task(
    analysis_id: str,
    payload: LearningTaskCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    analysis = owned_analysis(db, analysis_id, user)
    if analysis.status not in ("ready", "partial"):
        raise SemanticError("分析尚未完成", code="analysis_not_ready")
    kb = get_knowledge_base()
    intent = payload.intent or analysis.intent
    shots = [
        {
            "shot_ref": shot.shot_ref,
            "start_ms": shot.start_ms,
            "end_ms": shot.end_ms,
            "observation": shot.observation,
            "shot_scale": shot.shot_scale,
            "camera_motion": shot.camera_motion,
            "interpretation": shot.interpretation,
            "alternative": shot.alternative,
            "narrative_function": shot.narrative_function,
            "dialogue": shot.dialogue,
            "frame_keys": shot.frame_keys,
            "evidence": shot.evidence,
            "knowledge_ids": shot.knowledge_ids,
            "unknowns": shot.unknowns,
        }
        for shot in analysis.shots
    ]
    asset = db.get(Asset, analysis.asset_id)
    built = build_task(
        analysis={
            "title": asset.original_filename if asset else "",
            "duration_ms": int(asset.duration_ms) if asset else analysis.metrics.get("duration_ms") or 0,
            "shots": shots,
        },
        intent=intent,
        level=payload.level,
        knowledge=kb,
    )
    row = LearningTask(
        analysis_id=analysis.id,
        owner_id=user.id,
        project_id=analysis.project_id,
        intent=built["intent"],
        level=built["level"],
        title=built["title"],
        objective=built["objective"],
        prerequisites=built["prerequisites"],
        steps=built["steps"],
        constraints=built["constraints"],
        submission_requirements=built["submission_requirements"],
        rubric=built["rubric"],
        estimated_minutes=built["estimated_minutes"],
        tools=built["tools"],
        reference_metrics=built["reference_metrics"],
        knowledge_version=kb.version,
    )
    db.add(row)
    db.commit()
    return task_out(row)


@router.get("/analyses/{analysis_id}/export", summary="导出 Markdown 报告（与所选版本一致）")
def export_analysis(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
    format: str = Query(default="md"),
) -> Response:
    analysis = owned_analysis(db, analysis_id, user)
    if format not in ("md", "markdown"):
        raise SemanticError("仅支持 format=md", code="unsupported_format")
    project = db.get(Project, analysis.project_id) if analysis.project_id else None
    tasks = (
        db.execute(select(LearningTask).where(LearningTask.analysis_id == analysis.id)).scalars().all()
    )
    markdown = render_analysis_markdown(
        analysis=analysis_out(analysis, with_urls=False, knowledge=_knowledge_index()),
        project={"title": project.title} if project else None,
        tasks=[task_out(task) for task in tasks],
    )
    filename = "chai-jing-analysis-v" + str(analysis.version) + ".md"
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="' + filename + '"',
            "X-Analysis-Version": str(analysis.version),
        },
    )
