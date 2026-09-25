"""任务队列与幂等（§3.2 任务与故障处理）。

默认使用数据库队列表（db 后端）：Worker 可独立进程运行，
进程重启后通过持久任务记录恢复或明确失败，任务不会永久停在处理中（F14）。
配置 queue_backend=celery 时，由 Celery + Redis 消费同一张 jobs 表。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .errors import Conflict
from .models import Job, utcnow
from .security import stable_hash

RUNNING_STATUSES = ("preprocessing", "analyzing", "teaching")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def find_job_by_idempotency(session: Session, owner_id: str, idempotency_key: str) -> Job | None:
    stmt = select(Job).where(Job.owner_id == owner_id, Job.idempotency_key == idempotency_key)
    return session.execute(stmt).scalars().first()


def create_job(
    session: Session,
    *,
    owner_id: str,
    job_type: str,
    payload: dict,
    project_id: str | None = None,
    idempotency_key: str = "",
    max_attempts: int = 3,
) -> tuple[Job, bool]:
    """创建任务；相同幂等键 + 相同请求体返回既有任务，请求体不同则 409（F10）。"""

    request_hash = stable_hash({"type": job_type, "payload": payload})
    if idempotency_key:
        existing = find_job_by_idempotency(session, owner_id, idempotency_key)
        if existing is not None:
            if existing.request_hash and existing.request_hash != request_hash:
                raise Conflict(
                    "相同 Idempotency-Key 已被不同请求体使用",
                    details={"job_id": existing.id},
                )
            return existing, False

    job = Job(
        owner_id=owner_id,
        project_id=project_id,
        type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        max_attempts=max_attempts,
        status="queued",
        stage="queued",
    )
    session.add(job)
    session.flush()
    return job, True


def claim_next_job(session: Session, worker_id: str) -> Job | None:
    """原子领取一个 queued 任务（乐观更新 + rowcount 校验）。"""

    stmt = (
        select(Job)
        .where(Job.status == "queued", Job.deleted_marker.is_(False))
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    candidate = session.execute(stmt).scalars().first()
    if candidate is None:
        return None
    now = utcnow()
    result = session.execute(
        update(Job)
        .where(Job.id == candidate.id, Job.status == "queued")
        .values(
            status="preprocessing",
            stage="preprocessing",
            attempt=Job.attempt + 1,
            locked_by=worker_id,
            locked_at=now,
            heartbeat_at=now,
            started_at=candidate.started_at or now,
            progress=1,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.flush()
    session.refresh(candidate)
    return candidate


def recover_stale_jobs(session: Session) -> int:
    """Worker 重启恢复：心跳过期的运行中任务重新排队或明确失败（F14）。"""

    settings = get_settings()
    deadline = utcnow() - timedelta(seconds=settings.worker_stale_lock_seconds)
    stmt = select(Job).where(Job.status.in_(RUNNING_STATUSES))
    recovered = 0
    for job in session.execute(stmt).scalars().all():
        heartbeat = job.heartbeat_at or job.locked_at or job.created_at
        if heartbeat is not None and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=utcnow().tzinfo)
        if heartbeat is not None and heartbeat > deadline:
            continue
        if job.attempt >= job.max_attempts:
            job.status = "failed"
            job.stage = "failed"
            job.error_code = "worker_lost"
            job.error_message = "Worker 在任务执行中丢失，且已达到最大重试次数"
            job.finished_at = utcnow()
        else:
            job.status = "queued"
            job.stage = "queued"
            job.locked_by = ""
            job.locked_at = None
        recovered += 1
    return recovered


def request_cancel(session: Session, job: Job) -> Job:
    """请求取消；终态重复调用幂等（§5.3）。"""

    if job.status in TERMINAL_STATUSES:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished_at = utcnow()
    return job


def requeue_job(session: Session, job: Job, *, reset_attempt: bool = False) -> Job:
    """手动/自动重试：只重跑失败阶段，已有结果的阶段不重复调用（§3.2）。"""

    if job.status not in TERMINAL_STATUSES and job.status != "queued":
        raise Conflict("任务尚未进入终态，无法重试")
    job.status = "queued"
    job.stage = "queued"
    job.error_code = ""
    job.error_message = ""
    job.finished_at = None
    job.locked_by = ""
    job.locked_at = None
    job.cancel_requested = False
    if reset_attempt:
        job.attempt = 0
    return job


def dispatch_job(job_id: str) -> str:
    """任务投递策略。

    - queue_backend=celery：投递到 Redis，由 Celery Worker 消费；
    - CJX_INLINE_JOBS=true：在当前进程后台线程内执行（仅用于单机演示/测试）；
    - 默认：留在 jobs 表，由独立 Worker 进程领取（生产路径）。
    """

    settings = get_settings()
    if settings.queue_backend == "celery" and publish_to_celery(job_id):
        return "celery"
    if settings.inline_jobs:
        import threading

        from .db import session_scope
        from .models import Job as JobModel
        from .pipeline.runner import process_job

        def _run() -> None:
            try:
                with session_scope() as session:
                    job = session.get(JobModel, job_id)
                    if job is not None and job.status == "queued":
                        from .queue import claim_next_job  # noqa: PLC0415

                        job.status = "preprocessing"
                        job.stage = "preprocessing"
                        job.attempt = (job.attempt or 0) + 1
                        job.locked_by = "inline"
                        job.locked_at = utcnow()
                        job.heartbeat_at = utcnow()
                        session.add(job)
                        session.flush()
                        process_job(session, job, worker_id="inline")
            except Exception:  # noqa: BLE001 - 内联执行失败由任务状态记录
                pass

        threading.Thread(target=_run, name="inline-worker", daemon=True).start()
        return "inline"
    return "db"


def publish_to_celery(job_id: str) -> bool:  # pragma: no cover - 需要 Redis
    """queue_backend=celery 时把任务投递到 Redis。"""

    settings = get_settings()
    if settings.queue_backend != "celery":
        return False
    try:
        from celery import Celery  # noqa: PLC0415
    except ImportError:
        return False
    app = Celery("chai_jing", broker=settings.redis_url, backend=settings.redis_url)
    app.send_task("app.worker.process_job", args=[job_id])
    return True
