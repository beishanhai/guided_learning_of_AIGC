"""请求/响应模型（OpenAPI 契约）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------- 鉴权 ----------------
class LoginRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=128, examples=["alice"])
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=128)


class UserOut(BaseModel):
    id: str
    subject: str
    display_name: str
    role: str
    created_at: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------- 项目 ----------------
class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    rights_note: str = Field(default="", max_length=2000)


class ProjectOut(BaseModel):
    id: str
    title: str
    description: str
    rights_note: str
    created_at: str
    deleted_at: str | None = None
    asset_count: int = 0
    analysis_count: int = 0


# ---------------- 上传 ----------------
class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    media_type: str = Field(default="video/mp4", max_length=64)
    sha256: str = Field(default="", max_length=64)


class UploadTicketOut(BaseModel):
    asset_id: str
    project_id: str
    object_key: str
    upload_url: str
    upload_method: str = "PUT"
    expires_in: int
    max_bytes: int
    note: str = ""


class AssetOut(BaseModel):
    id: str
    project_id: str
    status: str
    duration_ms: int
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    media_type: str
    size_bytes: int
    sha256: str
    is_vfr: bool
    rejection_code: str = ""
    rejection_reason: str = ""
    playback_url: str = ""
    created_at: str


class MediaValidationOut(BaseModel):
    asset: AssetOut
    validated: bool
    checks: list[dict[str, Any]]


# ---------------- 任务 ----------------
class JobOut(BaseModel):
    id: str
    type: str
    status: str
    stage: str
    attempt: int
    max_attempts: int
    progress: int
    partial: bool
    error_code: str
    error_message: str
    result_type: str
    result_id: str
    estimated_cost_cny: float
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)


class JobCreatedOut(BaseModel):
    job_id: str
    status: str
    stage: str
    idempotent_replay: bool = False


# ---------------- 分析 ----------------
class AnalysisCreate(BaseModel):
    asset_id: str
    intent: Literal["shot_language", "narrative_rhythm"] = "shot_language"
    generate_task: bool = False
    expected_version: int | None = None


class ShotPatch(BaseModel):
    shot_ref: str
    start_ms: int | None = None
    end_ms: int | None = None
    shot_scale: str | None = None
    camera_motion: str | None = None
    narrative_function: str | None = None
    review_status: Literal["unreviewed", "confirmed", "rejected"] | None = None
    observation: str | None = None
    interpretation: str | None = None


class ShotsPatchRequest(BaseModel):
    expected_version: int
    review_status: Literal["unreviewed", "confirmed", "rejected"] = "confirmed"
    shots: list[ShotPatch] = Field(default_factory=list)


class LearningTaskCreate(BaseModel):
    level: Literal["imitate", "variant", "original"] = "imitate"
    intent: Literal["shot_language", "narrative_rhythm"] | None = None


class LearningTaskOut(BaseModel):
    id: str
    analysis_id: str
    intent: str
    level: str
    title: str
    objective: str
    prerequisites: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    constraints: dict[str, Any]
    submission_requirements: list[str]
    rubric: list[dict[str, Any]]
    estimated_minutes: int
    tools: list[str]
    reference_metrics: dict[str, Any]
    version: int
    created_at: str


# ---------------- 作业与反馈 ----------------
class SubmissionCreate(BaseModel):
    asset_id: str
    learner_reason: str = Field(default="", max_length=4000)
    storyboard_text: str = Field(default="", max_length=20000)


class SubmissionOut(BaseModel):
    id: str
    task_id: str
    asset_id: str
    analysis_id: str
    submission_analysis_id: str
    learner_reason: str
    storyboard_text: str
    status: str
    version: int
    created_at: str


class FeedbackOut(BaseModel):
    id: str
    submission_id: str
    summary: str
    metrics: dict[str, Any]
    alignments: list[dict[str, Any]]
    suggestions: list[dict[str, Any]]
    evidence: dict[str, Any]
    storyboard_metrics: dict[str, Any]
    reference_metrics: dict[str, Any] = Field(default_factory=dict)
    submission_metrics: dict[str, Any] = Field(default_factory=dict)
    constraint_results: list[dict[str, Any]] = Field(default_factory=list)
    task_snapshot: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = ""
    review_status: str
    created_at: str


# ---------------- 分析详情 ----------------
class ShotOut(BaseModel):
    """镜头记录（含证据与知识卡片，字段与 serializers.shot_out 一致）。"""

    model_config = ConfigDict(extra="allow")

    id: str
    shot_ref: str
    index: int
    start_ms: int
    end_ms: int
    duration_ms: int
    observation: str
    shot_scale: str
    camera_motion: str
    interpretation: str
    alternative: str
    narrative_function: str
    dialogue: str
    frames: list[dict[str, Any]] = Field(default_factory=list)
    frame_keys: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    review_status: str = "unreviewed"
    source: str = "detector"


class AnalysisOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    asset_id: str
    project_id: str
    version: int
    kind: str
    intent: str
    status: str
    model_id: str = ""
    prompt_version: str = ""
    knowledge_version: str = ""
    schema_version: str = ""
    pipeline_version: str = ""
    coverage: dict[str, Any] = Field(default_factory=dict)
    transcript: dict[str, Any] = Field(default_factory=dict)
    media: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    unknowns: dict[str, Any] = Field(default_factory=dict)
    review_status: str = "unreviewed"
    edited_by_user: bool = False
    is_demo_prebuilt: bool = False
    created_at: str | None = None
    shots: list[ShotOut] = Field(default_factory=list)


class ExplanationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    shot_ref: str
    intent: str
    observation: str
    fact_lines: list[str] = Field(default_factory=list)
    intent_reading: str
    interpretation: str = ""
    alternative: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class ExplanationsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    analysis_id: str
    intent: str
    intent_label: str
    fact_timeline_unchanged: bool
    note: str
    explanations: list[ExplanationItem]


# ---------------- 系统 ----------------
class ErrorOut(BaseModel):
    code: str
    message: str
    request_id: str = ""
    details: Any | None = None


class HealthOut(BaseModel):
    status: str
    database: str
    storage: str
    ffmpeg: bool
    ffprobe: bool
    worker_backlog: int
    versions: dict[str, str]
