"""学习任务、作业提交与反馈。"""

from __future__ import annotations

from fastapi import APIRouter, Header, Query
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, owned_analysis, owned_asset, owned_submission, owned_task
from ..errors import Conflict, NotFound, SemanticError
from ..learning.knowledge import get_knowledge_base
from ..models import Analysis, Feedback, LearningTask, Submission
from ..queue import create_job, dispatch_job
from ..schemas import FeedbackOut, JobCreatedOut, SubmissionCreate, SubmissionOut, LearningTaskOut
from ..serializers import feedback_out, submission_out, task_out

router = APIRouter(tags=["learning"])


@router.get("/learning-tasks", response_model=list[LearningTaskOut], summary="学习任务列表")
def list_tasks(
    db: DbSession,
    user: CurrentUser,
    analysis_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    stmt = select(LearningTask).where(LearningTask.owner_id == user.id).order_by(
        LearningTask.created_at.desc()
    ).limit(limit)
    if analysis_id:
        owned_analysis(db, analysis_id, user)
        stmt = stmt.where(LearningTask.analysis_id == analysis_id)
    return [task_out(row) for row in db.execute(stmt).scalars().all()]


@router.get("/learning-tasks/{task_id}", response_model=LearningTaskOut, summary="学习任务详情")
def get_task(task_id: str, db: DbSession, user: CurrentUser) -> dict:
    return task_out(owned_task(db, task_id, user))


@router.post(
    "/learning-tasks/{task_id}/submissions",
    response_model=JobCreatedOut,
    status_code=202,
    summary="提交作品并请求结构反馈（复用同一条分析流水线）",
)
def create_submission(
    task_id: str,
    payload: SubmissionCreate,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    task = owned_task(db, task_id, user)
    asset = owned_asset(db, payload.asset_id, user)
    if asset.status != "ready":
        raise SemanticError("作业素材尚未通过服务端校验", code="asset_not_ready")
    if task.analysis_id:
        owned_analysis(db, task.analysis_id, user)

    submission = Submission(
        task_id=task.id,
        analysis_id=task.analysis_id,
        owner_id=user.id,
        asset_id=asset.id,
        learner_reason=payload.learner_reason,
        storyboard_text=payload.storyboard_text,
        status="submitted",
    )
    db.add(submission)
    db.flush()
    job, created = create_job(
        db,
        owner_id=user.id,
        job_type="analyze_submission",
        project_id=asset.project_id,
        payload={"submission_id": submission.id, "asset_id": asset.id},
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


@router.get("/submissions", response_model=list[SubmissionOut], summary="作业列表")
def list_submissions(
    db: DbSession,
    user: CurrentUser,
    task_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    stmt = select(Submission).where(Submission.owner_id == user.id).order_by(
        Submission.created_at.desc()
    ).limit(limit)
    if task_id:
        owned_task(db, task_id, user)
        stmt = stmt.where(Submission.task_id == task_id)
    return [submission_out(row) for row in db.execute(stmt).scalars().all()]


@router.get("/submissions/{submission_id}", response_model=SubmissionOut, summary="作业详情")
def get_submission(submission_id: str, db: DbSession, user: CurrentUser) -> dict:
    return submission_out(owned_submission(db, submission_id, user))


@router.get("/submissions/{submission_id}/feedback", response_model=FeedbackOut, summary="作业反馈")
def get_feedback(submission_id: str, db: DbSession, user: CurrentUser) -> dict:
    submission = owned_submission(db, submission_id, user)
    row = (
        db.execute(
            select(Feedback).where(Feedback.submission_id == submission.id).order_by(Feedback.created_at.desc())
        )
        .scalars()
        .first()
    )
    if row is None:
        raise NotFound("反馈尚未生成，请等待分析完成")
    return feedback_out(row)


@router.get("/feedback", response_model=list[FeedbackOut], summary="反馈列表")
def list_feedback(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    rows = (
        db.execute(
            select(Feedback).where(Feedback.owner_id == user.id).order_by(Feedback.created_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [feedback_out(row) for row in rows]


@router.get("/feedback/{feedback_id}", response_model=FeedbackOut, summary="反馈详情")
def get_feedback_by_id(feedback_id: str, db: DbSession, user: CurrentUser) -> dict:
    row = db.get(Feedback, feedback_id)
    if row is None or row.owner_id != user.id:
        raise NotFound("反馈不存在")
    return feedback_out(row)
