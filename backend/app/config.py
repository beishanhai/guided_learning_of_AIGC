"""应用配置。

依据《拆镜学：技术开发路线与验收文档 V1.0》：
- §3：前端不持有模型密钥，模型调用只在后端执行；模型服务名/模型 ID/价格版本作为配置。
- §4/§9：镜头检测、抽帧、成本与超时阈值全部可配置，便于第 1 周基准试验后冻结。
"""

from __future__ import annotations

import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = BACKEND_DIR.parent


def _default_data_dir() -> Path:
    return BACKEND_DIR / "var"


class Settings(BaseSettings):
    """全局配置。环境变量前缀 CJX_，例如 CJX_DATABASE_URL。"""

    model_config = SettingsConfigDict(
        env_file=(WORKSPACE_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="CJX_",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 基础 ----
    app_name: str = "拆镜学 API"
    env: str = "dev"
    api_prefix: str = "/api/v1"
    data_dir: Path = Field(default_factory=_default_data_dir)
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"

    # ---- 数据库 / 队列 ----
    database_url: str = ""
    queue_backend: str = "db"  # db | celery
    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_poll_interval_seconds: float = 1.0
    worker_stale_lock_seconds: int = 600
    worker_max_parallel: int = 1
    # 仅单机演示/自动化测试使用：API 进程内后台线程直接执行任务。
    # 生产必须保持 false，由独立 Worker 进程消费（§3 架构要求 API 与 Worker 分进程）。
    inline_jobs: bool = False

    # ---- 存储 ----
    storage_backend: str = "local"  # local | s3
    storage_root: Path = Field(default_factory=lambda: _default_data_dir() / "storage")
    s3_bucket: str = "chai-jing-private"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    signed_url_ttl_seconds: int = 300

    # ---- 鉴权 ----
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    token_ttl_seconds: int = 12 * 3600
    allow_self_registration: bool = True
    bootstrap_users: str = "alice:alice-pass-123:learner,bob:bob-pass-123:learner"

    # ---- 媒体准入（§1.1 / F02）----
    max_upload_bytes: int = 100 * 1024 * 1024
    min_duration_ms: int = 15_000
    max_duration_ms: int = 60_000
    max_height: int = 1080
    allowed_containers: tuple[str, ...] = ("mp4", "mov", "m4v")
    allowed_video_codecs: tuple[str, ...] = ("h264",)
    probe_timeout_seconds: int = 60
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # ---- 镜头检测与抽帧（§4.1）----
    scene_analysis_width: int = 160
    scene_threshold_k: float = 3.0
    scene_threshold_min: float = 0.08
    scene_threshold_max: float = 0.60
    min_shot_ms: int = 400
    max_frames_per_asset: int = 60
    long_shot_sample_ms: int = 6000
    frame_max_width: int = 640
    frame_jpeg_quality: int = 5

    # ---- 外部模型（§3 / §9）----
    multimodal_provider: str = "offline"  # offline | openai_compatible
    multimodal_base_url: str = "https://example.invalid/v1"
    multimodal_api_key: str = ""
    multimodal_model_id: str = "offline-deterministic-v1"
    multimodal_price_version: str = "unpriced-dev"
    multimodal_timeout_seconds: float = 90.0
    multimodal_input_price_per_mtok: float = 0.0
    multimodal_output_price_per_mtok: float = 0.0

    asr_provider: str = "none"  # none | http
    asr_model_id: str = "none"
    asr_base_url: str = ""
    asr_api_key: str = ""
    asr_timeout_seconds: float = 120.0

    provider_max_retries: int = 2
    provider_backoff_seconds: float = 1.5
    analysis_max_runtime_seconds: int = 900
    schema_repair_attempts: int = 1

    # ---- 成本控制（§9）----
    cost_per_analysis_limit_cny: float = 1.0
    cost_per_learning_loop_limit_cny: float = 3.0
    daily_user_cost_limit_cny: float = 20.0
    allow_paid_calls: bool = False

    # ---- 版本（每次分析落库，便于追溯）----
    prompt_version: str = "p1"
    schema_version: str = "s1"
    knowledge_version: str = "k1"
    pipeline_version: str = "pipe1"

    # ---- 学习引擎 ----
    knowledge_path: Path = Field(default_factory=lambda: BACKEND_DIR / "knowledge" / "cards.yaml")
    default_task_estimated_minutes: int = 45

    # ---- 部署/运维 ----
    healthcheck_include_storage: bool = True

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.data_dir / "chai_jing.db"
        return "sqlite:///" + db_path.as_posix()

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """测试用：丢弃缓存的配置对象。"""

    global _settings
    _settings = None
