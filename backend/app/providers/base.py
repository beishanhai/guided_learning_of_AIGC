"""供应商无关的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class ShotContext:
    """交给视觉分析的单个镜头上下文。"""

    index: int
    shot_ref: str
    start_ms: int
    end_ms: int
    duration_ms: int
    frames: list[Path] = field(default_factory=list)
    frame_ids: list[str] = field(default_factory=list)
    transcript: str = ""
    intent: str = "shot_language"
    neighbors: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShotFinding:
    observation: str
    shot_scale: str = "unknown"
    camera_motion: str = "unknown"
    interpretation: str = ""
    alternative: str = ""
    narrative_function: str = "unknown"
    knowledge_tags: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provider_request_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str = ""
    provider: str = "none"
    provider_request_id: str = ""
    note: str = ""


class VisionProvider(Protocol):
    name: str
    model_id: str

    def analyze_shot(self, context: ShotContext, *, job_id: str) -> ShotFinding: ...


class AsrProvider(Protocol):
    name: str
    model_id: str

    def transcribe(self, audio_path: Path, *, duration_ms: int, job_id: str) -> TranscriptResult: ...
