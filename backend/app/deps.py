"""FastAPI 依赖：鉴权与所有权校验。

无权限资源统一 404，不泄露存在性（§5.3 / F12）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import NotFound, Unauthorized
from .models import Analysis, Asset, Job, LearningTask, Project, Submission, User
from .security import TokenError, decode_token

DbSession = Annotated[Session, Depends(get_db)]


def current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("缺少 Bearer 令牌")
    token = authorization.split(" ", 1)[1].strip()
    settings = get_settings()
    try:
        payload = decode_token(token, settings.secret_key)
    except TokenError as exc:
        raise Unauthorized("令牌无效或已过期") from exc
    user = db.get(User, str(payload.get("sub") or ""))
    if user is None or not user.is_active:
        raise Unauthorized("账号不可用")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def owned_project(db: Session, project_id: str, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id or project.deleted_at is not None:
        raise NotFound("项目不存在")
    return project


def owned_asset(db: Session, asset_id: str, user: User) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.owner_id != user.id:
        raise NotFound("素材不存在")
    project = db.get(Project, asset.project_id)
    if project is None or project.deleted_at is not None:
        raise NotFound("素材不存在")
    return asset


def owned_analysis(db: Session, analysis_id: str, user: User) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.owner_id != user.id:
        raise NotFound("分析不存在")
    project = db.get(Project, analysis.project_id)
    if project is None or project.deleted_at is not None:
        raise NotFound("分析不存在")
    return analysis


def owned_job(db: Session, job_id: str, user: User) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.owner_id != user.id:
        raise NotFound("任务不存在")
    return job


def owned_task(db: Session, task_id: str, user: User) -> LearningTask:
    task = db.get(LearningTask, task_id)
    if task is None or task.owner_id != user.id:
        raise NotFound("学习任务不存在")
    return task


def owned_submission(db: Session, submission_id: str, user: User) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None or submission.owner_id != user.id:
        raise NotFound("作业不存在")
    return submission
