"""任务状态查询、取消与重试。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, owned_job
from ..models import Job
from ..queue import request_cancel, requeue_job
from ..schemas import JobCreatedOut, JobOut
from ..serializers import job_out

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut], summary="任务列表")
def list_jobs(
    db: DbSession,
    user: CurrentUser,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    stmt = select(Job).where(Job.owner_id == user.id).order_by(Job.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Job.status == status)
    rows = db.execute(stmt).scalars().all()
    return [job_out(job, with_stages=False) for job in rows]


@router.get("/jobs/{job_id}", response_model=JobOut, summary="任务状态与阶段记录")
def get_job(job_id: str, db: DbSession, user: CurrentUser) -> dict:
    return job_out(owned_job(db, job_id, user))


@router.post("/jobs/{job_id}/cancel", response_model=JobCreatedOut, summary="请求取消（终态幂等）")
def cancel_job(job_id: str, db: DbSession, user: CurrentUser) -> dict:
    job = owned_job(db, job_id, user)
    request_cancel(db, job)
    db.commit()
    return {"job_id": job.id, "status": job.status, "stage": job.stage}


@router.post("/jobs/{job_id}/retry", response_model=JobCreatedOut, summary="重试失败任务（只重跑失败阶段）")
def retry_job(job_id: str, db: DbSession, user: CurrentUser) -> dict:
    job = owned_job(db, job_id, user)
    requeue_job(db, job, reset_attempt=True)
    db.commit()
    return {"job_id": job.id, "status": job.status, "stage": job.stage}
