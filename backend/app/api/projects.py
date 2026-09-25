"""项目：创建、列表、详情、删除（含任务取消与对象清理）。"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from ..deps import CurrentUser, DbSession, owned_project
from ..models import Analysis, Asset, CleanupTask, Job, Project, utcnow
from ..queue import RUNNING_STATUSES
from ..schemas import ProjectCreate, ProjectOut
from ..serializers import project_out

router = APIRouter(tags=["projects"])


@router.post("/projects", response_model=ProjectOut, status_code=201, summary="创建项目")
def create_project(payload: ProjectCreate, db: DbSession, user: CurrentUser) -> dict:
    project = Project(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        rights_note=payload.rights_note,
    )
    db.add(project)
    db.commit()
    return project_out(project)


@router.get("/projects", response_model=list[ProjectOut], summary="项目列表")
def list_projects(db: DbSession, user: CurrentUser) -> list[dict]:
    rows = (
        db.execute(
            select(Project)
            .where(Project.owner_id == user.id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc())
        )
        .scalars()
        .all()
    )
    out = []
    for project in rows:
        asset_count = int(
            db.execute(select(func.count()).select_from(Asset).where(Asset.project_id == project.id)).scalar() or 0
        )
        analysis_count = int(
            db.execute(select(func.count()).select_from(Analysis).where(Analysis.project_id == project.id)).scalar() or 0
        )
        out.append(project_out(project, asset_count=asset_count, analysis_count=analysis_count))
    return out


@router.get("/projects/{project_id}", response_model=ProjectOut, summary="项目详情")
def get_project(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    project = owned_project(db, project_id, user)
    asset_count = int(
        db.execute(select(func.count()).select_from(Asset).where(Asset.project_id == project.id)).scalar() or 0
    )
    analysis_count = int(
        db.execute(select(func.count()).select_from(Analysis).where(Analysis.project_id == project.id)).scalar() or 0
    )
    return project_out(project, asset_count=asset_count, analysis_count=analysis_count)


@router.delete("/projects/{project_id}", status_code=204, summary="删除项目（软删除 + 立即撤销访问 + 安排对象清理）")
def delete_project(project_id: str, db: DbSession, user: CurrentUser) -> Response:
    project = owned_project(db, project_id, user)
    project.deleted_at = utcnow()
    assets = db.execute(select(Asset).where(Asset.project_id == project.id)).scalars().all()
    jobs = (
        db.execute(select(Job).where(Job.project_id == project.id, Job.status.in_(RUNNING_STATUSES + ("queued",))))
        .scalars()
        .all()
    )
    for job in jobs:
        job.cancel_requested = True
        job.deleted_marker = True
        if job.status == "queued":
            job.status = "cancelled"
            job.stage = "cancelled"
            job.finished_at = utcnow()
        db.add(job)
    for asset in assets:
        db.add(CleanupTask(project_id=project.id, object_key=asset.object_key))
        asset.status = "deleted"
        db.add(asset)
    db.add(project)
    db.commit()
    return Response(status_code=204)
