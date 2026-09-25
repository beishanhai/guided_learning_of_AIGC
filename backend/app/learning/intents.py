"""学习意图映射（§1.1：镜头语言 / 叙事节奏；§4 复用底层事实，改变解释与练习）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..pipeline.schema import (
    CAMERA_MOTION_LABELS,
    NARRATIVE_FUNCTION_LABELS,
    SHOT_SCALE_LABELS,
)


@dataclass
class IntentSpec:
    key: str
    label: str
    goal: str
    focus: list[str]
    explanation_lead: str
    practice_emphasis: str
    knowledge_topics: list[str] = field(default_factory=list)
    metrics_of_interest: list[str] = field(default_factory=list)


INTENTS: dict[str, IntentSpec] = {
    "shot_language": IntentSpec(
        key="shot_language",
        label="镜头语言",
        goal="看懂每个镜头用什么手段传递信息，并能在自己的作品里复用这些手段",
        focus=["景别选择", "构图与视角", "摄影机运动", "镜头之间的衔接"],
        explanation_lead="这个镜头在画面上做了什么选择",
        practice_emphasis="景别的选择是否服务于信息与情绪",
        knowledge_topics=["shot_scale", "camera_motion", "composition", "shot_relation", "color_temperature"],
        metrics_of_interest=["shot_scale_distribution", "camera_motion_distribution", "shot_count"],
    ),
    "narrative_rhythm": IntentSpec(
        key="narrative_rhythm",
        label="叙事节奏",
        goal="看懂镜头长短与顺序如何安排信息与情绪，并迁移到自己的短片结构里",
        focus=["镜头时长分布", "节奏曲线", "段落功能", "信息释放顺序"],
        explanation_lead="这个镜头在时间结构上承担什么任务",
        practice_emphasis="节奏变化是否服务于表达目标",
        knowledge_topics=["rhythm", "shot_duration", "narrative_function", "pacing_curve", "transition"],
        metrics_of_interest=["shot_duration_mean", "shot_duration_list", "cut_rate", "narrative_function_distribution"],
    ),
}


def get_intent(key: str) -> IntentSpec:
    return INTENTS.get(key) or INTENTS["shot_language"]


def intent_options() -> list[dict[str, str]]:
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "goal": spec.goal,
            "practice_emphasis": spec.practice_emphasis,
        }
        for spec in INTENTS.values()
    ]


def scale_label(value: str) -> str:
    return SHOT_SCALE_LABELS.get(value, "未知")


def motion_label(value: str) -> str:
    return CAMERA_MOTION_LABELS.get(value, "未知")


def function_label(value: str) -> str:
    return NARRATIVE_FUNCTION_LABELS.get(value, "未判定")


def build_shot_explanations(shots: list[dict[str, Any]], intent: str) -> list[dict[str, Any]]:
    """按学习意图改写镜头解释，但事实时间线保持不变（F05）。"""

    spec = get_intent(intent)
    out: list[dict[str, Any]] = []
    for shot in shots:
        facts = [
            str(shot.get("observation") or "").strip(),
            "景别：" + scale_label(str(shot.get("shot_scale") or "unknown")),
            "运镜：" + motion_label(str(shot.get("camera_motion") or "unknown")),
        ]
        if shot.get("dialogue"):
            facts.append("台词：" + str(shot["dialogue"]))
        lean = ""
        if intent == "narrative_rhythm":
            duration_s = (int(shot.get("end_ms", 0)) - int(shot.get("start_ms", 0))) / 1000.0
            lean = (
                "本镜头时长 "
                + format(duration_s, ".2f")
                + " 秒，在整段节奏中属于"
                + ("快切单元" if duration_s < 1.2 else ("停留单元" if duration_s > 8 else "常规单元"))
            )
            if shot.get("narrative_function"):
                lean += "；叙事功能判定为" + function_label(str(shot["narrative_function"]))
        else:
            lean = spec.explanation_lead + "，本次观察到的关键选择是" + scale_label(
                str(shot.get("shot_scale") or "unknown")
            )
        out.append(
            {
                "shot_ref": shot.get("shot_ref"),
                "intent": intent,
                "observation": "；".join([f for f in facts if f and not f.endswith("未知")]) or "（无可用观察）",
                "fact_lines": facts,
                "intent_reading": lean,
                "interpretation": shot.get("interpretation") or "",
                "alternative": shot.get("alternative") or "",
                "evidence": shot.get("evidence") or [],
                "knowledge_ids": shot.get("knowledge_ids") or [],
                "unknowns": shot.get("unknowns") or [],
            }
        )
    return out
