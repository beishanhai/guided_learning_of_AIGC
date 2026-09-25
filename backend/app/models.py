"""数据模型（对应验收文档 §5.1 主要数据表）。

约定：
- 全表 UUID 字符串主键 + created_at / updated_at；
- 项目资源通过 owner_id / project_id 关联并在 API 层校验所有权（F12）；
- 状态与阶段使用字符串枚举，便于跨 SQLite / PostgreSQL；
- JSON 列保存结构化事实、推测、证据、指标，避免过度范式化。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .security import new_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------------------
# 账号与项目
# --------------------------------------------------------------------------------------
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(String(32), default="learner")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    rights_note: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship(back_populates="projects")
    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")


# --------------------------------------------------------------------------------------
# 媒体资产
# --------------------------------------------------------------------------------------
class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    media_type: Mapped[str] = mapped_column(String(64), default="video/mp4")
    container: Mapped[str] = mapped_column(String(32), default="")
    video_codec: Mapped[str] = mapped_column(String(32), default="")
    audio_codec: Mapped[str] = mapped_column(String(32), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    is_vfr: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # pending -> uploaded -> ready | rejected
    rejection_code: Mapped[str] = mapped_column(String(64), default="")
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    rights_note: Mapped[str] = mapped_column(Text, default="")
    probe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_demo_prebuilt: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="assets")


# --------------------------------------------------------------------------------------
# 任务与阶段
# --------------------------------------------------------------------------------------
class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_job_owner_idem"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    # analyze_asset | analyze_submission | cleanup_project | generate_task
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    # queued -> preprocessing -> analyzing -> teaching -> succeeded | failed | cancelled
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(128), default="")
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_type: Mapped[str] = mapped_column(String(64), default="")
    result_id: Mapped[str] = mapped_column(String(36), default="")
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_marker: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str] = mapped_column(String(64), default="")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_cost_cny: Mapped[float] = mapped_column(Float, default=0.0)

    stages: Mapped[list["JobStage"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobStage.created_at"
    )


class JobStage(TimestampMixin, Base):
    """每阶段保存输入摘要、输出、耗时、供应商请求 ID 与版本（§3.2）。"""

    __tablename__ = "job_stages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="running")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    provider_request_id: Mapped[str] = mapped_column(String(128), default="")
    version: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="stages")


class ModelCall(TimestampMixin, Base):
    """外部模型调用账本：用量、估算成本、单价版本、时延（§9）。"""

    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    provider: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(128))
    provider_request_id: Mapped[str] = mapped_column(String(160), default="")
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    estimated_cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    price_version: Mapped[str] = mapped_column(String(64), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    error_code: Mapped[str] = mapped_column(String(64), default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)


# --------------------------------------------------------------------------------------
# 拆解结果
# --------------------------------------------------------------------------------------
class Analysis(TimestampMixin, Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("asset_id", "version", name="uq_analysis_asset_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(32), default="reference")  # reference | submission
    intent: Mapped[str] = mapped_column(String(32), default="shot_language")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    knowledge_version: Mapped[str] = mapped_column(String(32), default="")
    schema_version: Mapped[str] = mapped_column(String(32), default="")
    pipeline_version: Mapped[str] = mapped_column(String(32), default="")
    supersedes_id: Mapped[str] = mapped_column(String(36), default="")
    parent_analysis_id: Mapped[str] = mapped_column(String(36), default="")
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    transcript: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    media: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unknowns: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    is_demo_prebuilt: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)

    shots: Mapped[list["Shot"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", order_by="Shot.index"
    )


class Shot(TimestampMixin, Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    shot_ref: Mapped[str] = mapped_column(String(32), default="")  # shot_001 ...
    start_ms: Mapped[int] = mapped_column(Integer, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, default=0)
    observation: Mapped[str] = mapped_column(Text, default="")
    shot_scale: Mapped[str] = mapped_column(String(32), default="unknown")
    camera_motion: Mapped[str] = mapped_column(String(32), default="unknown")
    interpretation: Mapped[str] = mapped_column(Text, default="")
    alternative: Mapped[str] = mapped_column(Text, default="")
    narrative_function: Mapped[str] = mapped_column(String(64), default="unknown")
    dialogue: Mapped[str] = mapped_column(Text, default="")
    transcript_segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    frame_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    knowledge_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    unknowns: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    source: Mapped[str] = mapped_column(String(32), default="detector")  # detector | human

    analysis: Mapped[Analysis] = relationship(back_populates="shots")


# --------------------------------------------------------------------------------------
# 知识卡片与学习任务
# --------------------------------------------------------------------------------------
class KnowledgeCard(TimestampMixin, Base):
    __tablename__ = "knowledge_cards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 稳定可引用的 card id
    topic: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[str] = mapped_column(String(32), default="k1")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    applicable_intents: Mapped[list[str]] = mapped_column(JSON, default=list)
    examples: Mapped[list[str]] = mapped_column(JSON, default=list)
    pitfalls: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default="reviewed")


class LearningTask(TimestampMixin, Base):
    __tablename__ = "learning_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), default="")
    intent: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(32))  # imitate | variant | original
    title: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    prerequisites: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    submission_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    rubric: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=45)
    tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    reference_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    knowledge_version: Mapped[str] = mapped_column(String(32), default="k1")


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("learning_tasks.id"), index=True)
    analysis_id: Mapped[str] = mapped_column(String(36), default="")
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"), index=True)
    submission_analysis_id: Mapped[str] = mapped_column(String(36), default="")
    learner_reason: Mapped[str] = mapped_column(Text, default="")
    storyboard_text: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="submitted")


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(String(36), ForeignKey("submissions.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    alignments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    storyboard_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reference_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    submission_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    constraint_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    task_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    disclaimer: Mapped[str] = mapped_column(Text, default="")


class CleanupTask(TimestampMixin, Base):
    """删除项目后的对象清理队列（F13）。"""

    __tablename__ = "cleanup_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    object_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
