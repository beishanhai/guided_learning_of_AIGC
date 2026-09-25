"""模型输出的 JSON Schema 与结构校验（§4.2 输出规则）。

规则：
- 模型只输出符合 schema 的 JSON；结构错误可修复 1 次，再失败返回可读错误；
- 时间戳必须落在片长内；
- 知识 ID 必须在库中存在（由学习引擎解析，模型只给标签，不能自造 ID）；
- 不采信模型自报置信度作为唯一依据。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

SHOT_SCALES = (
    "extreme_wide",
    "wide",
    "medium",
    "medium_close",
    "close_up",
    "extreme_close_up",
    "unknown",
)
CAMERA_MOTIONS = ("static", "pan", "tilt", "dolly", "zoom", "handheld", "unknown")
NARRATIVE_FUNCTIONS = (
    "establish",
    "introduce_subject",
    "develop",
    "emphasize_emotion",
    "transition",
    "unknown",
)
SHOT_SCALE_LABELS = {
    "extreme_wide": "大远景",
    "wide": "全景",
    "medium": "中景",
    "medium_close": "中近景",
    "close_up": "近景",
    "extreme_close_up": "特写",
    "unknown": "未知",
}
CAMERA_MOTION_LABELS = {
    "static": "固定",
    "pan": "横摇",
    "tilt": "纵摇",
    "dolly": "移动",
    "zoom": "变焦",
    "handheld": "手持",
    "unknown": "未知",
}
NARRATIVE_FUNCTION_LABELS = {
    "establish": "建立环境",
    "introduce_subject": "引入主体",
    "develop": "推进信息",
    "emphasize_emotion": "情绪强调",
    "transition": "转场过渡",
    "unknown": "未判定",
}


class ShotModelOutput(BaseModel):
    """单个镜头允许模型输出的字段集合。"""

    observation: str = ""
    shot_scale: str = "unknown"
    camera_motion: str = "unknown"
    interpretation: str = ""
    alternative: str = ""
    narrative_function: str = "unknown"
    knowledge_tags: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @field_validator("shot_scale")
    @classmethod
    def _scale(cls, value: str) -> str:
        return value if value in SHOT_SCALES else "unknown"

    @field_validator("camera_motion")
    @classmethod
    def _motion(cls, value: str) -> str:
        return value if value in CAMERA_MOTIONS else "unknown"

    @field_validator("narrative_function")
    @classmethod
    def _function(cls, value: str) -> str:
        return value if value in NARRATIVE_FUNCTIONS else "unknown"

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(max(number, 0.0), 1.0)


class ShotSpanModel(BaseModel):
    shot_ref: str
    start_ms: int
    end_ms: int


class AnalysisModelOutput(BaseModel):
    """整片分析结果的顶层结构。"""

    shots: list[ShotModelOutput] = Field(default_factory=list)
    summary: str = ""
    unknowns: list[str] = Field(default_factory=list)


def analysis_json_schema() -> dict:
    return AnalysisModelOutput.model_json_schema()


def check_span(span: ShotSpanModel, duration_ms: int) -> list[str]:
    """时间戳必须落在片长内（§4.2）。"""

    issues: list[str] = []
    if span.start_ms < 0:
        issues.append(span.shot_ref + "：start_ms 为负")
    if span.end_ms > duration_ms:
        issues.append(span.shot_ref + "：end_ms 超出片长")
    if span.end_ms <= span.start_ms:
        issues.append(span.shot_ref + "：时间区间非法")
    return issues


def normalize_finding(finding: Any, *, duration_ms: int, valid_tags: set[str]) -> tuple[ShotModelOutput, list[str]]:
    """把供应商返回值规整为 schema 输出，并返回被修正/丢弃的内容。"""

    issues: list[str] = []
    if hasattr(finding, "model_dump"):
        raw: dict = finding.model_dump()
    elif isinstance(finding, dict):
        raw = dict(finding)
    else:
        raw = {
            "observation": getattr(finding, "observation", ""),
            "shot_scale": getattr(finding, "shot_scale", "unknown"),
            "camera_motion": getattr(finding, "camera_motion", "unknown"),
            "interpretation": getattr(finding, "interpretation", ""),
            "alternative": getattr(finding, "alternative", ""),
            "narrative_function": getattr(finding, "narrative_function", "unknown"),
            "knowledge_tags": list(getattr(finding, "knowledge_tags", []) or []),
            "unknowns": list(getattr(finding, "unknowns", []) or []),
            "confidence": getattr(finding, "confidence", 0.0),
        }

    if not str(raw.get("observation") or "").strip():
        issues.append("模型未给出可核对的观察事实，已标记为需要人工复核")
        raw["observation"] = "（模型未给出观察事实，需人工复核）"

    tags = [str(tag) for tag in (raw.get("knowledge_tags") or [])]
    kept_tags: list[str] = []
    for tag in tags:
        if tag in valid_tags:
            kept_tags.append(tag)
        else:
            issues.append("丢弃不存在的知识标签：" + tag)
    raw["knowledge_tags"] = kept_tags

    model = ShotModelOutput(**raw)
    return model, issues
