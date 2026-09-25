"""三级学习任务模板（§4.3）。

级别固定约束：模仿保留镜头数量与主要叙事功能；变体保留表达目标、修改景别或顺序并说明理由；
原创只给主题、时长与表达目标，由学习者独立设计。
每个任务包含：目标、先修知识、3—5 个步骤、提交要求、评价量表、预计用时、可用工具说明。
默认由学习者在外部工具制作后上传，系统内生成不是完成前提。
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..pipeline.schema import SHOT_SCALE_LABELS
from .intents import get_intent
from .knowledge import KnowledgeBase
from .metrics import compute_metrics

LEVELS: dict[str, dict[str, str]] = {
    "imitate": {
        "label": "模仿",
        "fixed_constraint": "保留镜头数量与主要叙事功能",
        "learner_change": "换主题、主体与素材",
        "evaluation_focus": "是否理解每个镜头的作用",
    },
    "variant": {
        "label": "变体",
        "fixed_constraint": "保留表达目标",
        "learner_change": "修改景别或镜头顺序，并说明理由",
        "evaluation_focus": "修改是否服务于表达目标",
    },
    "original": {
        "label": "原创",
        "fixed_constraint": "只给主题、时长与表达目标",
        "learner_change": "独立设计分镜并制作",
        "evaluation_focus": "能否迁移学到的方法",
    },
}

RUBRIC_TEMPLATE: list[tuple[str, str]] = [
    ("purpose_clarity", "镜头目的清晰度"),
    ("continuity", "衔接合理性"),
    ("scale_match", "景别与表达匹配"),
    ("transfer_reason", "迁移与创作理由"),
]

TOOL_NOTE = (
    "可用手机、相机或任意剪辑软件（剪映 / Premiere / DaVinci Resolve / CapCut）制作；"
    "也可以只提交文字分镜（P1 功能）。系统内自动生成不是完成任务的前提。"
)


def _scale_summary(ref_metrics: dict[str, Any]) -> str:
    distribution = ref_metrics.get("scale_distribution", {})
    known = [(k, v) for k, v in distribution.items() if k != "unknown" and v > 0]
    if not known:
        return "参考片景别多不可判定，任务只约束镜头数量与时长"
    known.sort(key=lambda item: -item[1])
    return "、".join(SHOT_SCALE_LABELS.get(k, k) + "×" + str(v) for k, v in known)


def build_task(
    *,
    analysis: dict[str, Any],
    intent: str,
    level: str,
    knowledge: KnowledgeBase,
) -> dict[str, Any]:
    settings = get_settings()
    spec = get_intent(intent)
    level_spec = LEVELS.get(level) or LEVELS["imitate"]
    shots = analysis.get("shots") or []
    duration_ms = int(analysis.get("duration_ms") or 0)
    metrics = compute_metrics(shots, duration_ms=duration_ms)

    reference_cards = knowledge.for_intent(intent, limit=6)
    if not reference_cards:
        reference_cards = list(knowledge.cards.values())[:6]

    title = spec.label + "·" + level_spec["label"] + "练习：" + str(analysis.get("title") or "参考短片")

    if level == "original":
        constraints: dict[str, Any] = {
            "duration_range_ms": [max(8000, int(duration_ms * 0.6)), int(duration_ms * 1.3)],
            "shot_count_range": [
                max(3, metrics["shot_count"] - 2),
                metrics["shot_count"] + 4,
            ],
            "must_state_objective": True,
            "level_note": level_spec["fixed_constraint"],
        }
    elif level == "variant":
        constraints = {
            "duration_range_ms": [int(duration_ms * 0.8), int(duration_ms * 1.2)],
            "shot_count_range": [max(2, metrics["shot_count"] - 1), metrics["shot_count"] + 2],
            "min_distinct_scales": 3,
            "must_explain_change": True,
            "level_note": level_spec["fixed_constraint"],
        }
    else:
        constraints = {
            "keep_shot_count": metrics["shot_count"],
            "duration_range_ms": [int(duration_ms * 0.8), int(duration_ms * 1.2)],
            "keep_narrative_function": True,
            "may_change_subject": True,
            "level_note": level_spec["fixed_constraint"],
        }
    if intent == "narrative_rhythm":
        constraints["single_shot_max_ms"] = max(4000, metrics["shot_duration_max_ms"])
    else:
        constraints["min_distinct_scales"] = constraints.get("min_distinct_scales", 2)

    steps = _steps_for(level, spec.label, metrics)

    rubric: list[dict[str, Any]] = []
    weights = {"imitate": [4, 4, 4, 4], "variant": [4, 4, 4, 4], "original": [4, 4, 4, 4]}[level]
    for (key, label), weight in zip(RUBRIC_TEMPLATE, weights):
        rubric.append(
            {
                "key": key,
                "criterion": label,
                "max_score": weight,
                "scale": "0=未体现，1/3=中间状态，2=基本合理但有明显问题，4=清晰且能解释",
            }
        )

    prerequisites = [
        {
            "knowledge_id": card.id,
            "title": card.title,
            "content": card.content,
            "source": card.source,
            "reviewer": card.reviewer,
        }
        for card in reference_cards[:4]
    ]

    submission_requirements = [
        "提交 15—60 秒的 MP4 成片（无声也可）",
        "在创作说明里用 3 句话说明：想表达什么、为什么这样安排镜头、哪一处参考了本片的做法",
        "变体与原创级别需说明修改了哪些镜头（景别或顺序）以及理由",
        "如果只在文字分镜阶段，可提交分镜文本，反馈会单独呈现",
    ]
    if level == "imitate":
        submission_requirements.append("保持与参考片相同的镜头数量：" + str(metrics["shot_count"]) + " 个")

    return {
        "title": title,
        "level": level,
        "level_label": level_spec["label"],
        "intent": intent,
        "intent_label": spec.label,
        "objective": _objective(level, spec.label, spec.goal, metrics),
        "prerequisites": prerequisites,
        "steps": steps,
        "constraints": constraints,
        "submission_requirements": submission_requirements,
        "rubric": rubric,
        "estimated_minutes": _estimate(level, settings.default_task_estimated_minutes),
        "tools": [TOOL_NOTE],
        "reference_metrics": metrics,
        "reference_scale_summary": _scale_summary(metrics),
        "evaluation_focus": level_spec["evaluation_focus"],
        "learner_change": level_spec["learner_change"],
    }


def _objective(level: str, intent_label: str, goal: str, metrics: dict[str, Any]) -> str:
    if level == "imitate":
        return (
            "用你自己的主题与素材，复现参考片的镜头结构（"
            + str(metrics["shot_count"])
            + " 个镜头，平均 "
            + str(round(metrics["shot_duration_mean_ms"] / 1000.0, 1))
            + " 秒），"
            "目标是理解每个镜头在"
            + intent_label
            + "上承担的作用："
            + goal
        )
    if level == "variant":
        return (
            "保留参考片的表达目标，主动改变景别分配或镜头顺序，并说明每处修改为什么更好地服务于"
            + intent_label
            + "目标："
            + goal
        )
    return (
        "只给定主题、时长与表达目标，独立设计分镜并制作，检验你能否把学到的"
        + intent_label
        + "方法迁移到全新题材："
        + goal
    )


def _steps_for(level: str, intent_label: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    mean_s = round(metrics["shot_duration_mean_ms"] / 1000.0, 1)
    if level == "imitate":
        return [
            {"index": 1, "title": "列结构表", "detail": "把参考片的 " + str(metrics["shot_count"]) + " 个镜头按顺序抄成一行一个镜头，写下每行只写“画面上有什么”。"},
            {"index": 2, "title": "给每个镜头写作用", "detail": "用一句话写这个镜头在" + intent_label + "上做什么，写不出来就标“不确定”。"},
            {"index": 3, "title": "换素材", "detail": "换成你自己的主题与素材，按同样的镜头数量和顺序拍一遍，平均镜头时长控制在 " + str(mean_s) + " 秒左右。"},
            {"index": 4, "title": "做对照", "detail": "把两版并排看一遍，列出 3 处“观感不同”的地方，判断是素材差异还是结构差异。"},
            {"index": 5, "title": "提交", "detail": "上传成片并写创作说明（3 句话）。"},
        ]
    if level == "variant":
        return [
            {"index": 1, "title": "选改点", "detail": "从景别与镜头顺序中选 2 处要改的地方，先写下“为什么改”。"},
            {"index": 2, "title": "改景别", "detail": "至少让 3 种可判定景别出现，并保持表达目标不变。"},
            {"index": 3, "title": "改顺序", "detail": "尝试把 1 个镜头提前或推后，说明信息释放顺序发生了什么变化。"},
            {"index": 4, "title": "自查", "detail": "对照任务约束逐条核对（镜头数 " + str(metrics["shot_count"]) + " 个左右、时长接近参考片）。"},
            {"index": 5, "title": "提交", "detail": "上传成片，逐条说明改动与理由。"},
        ]
    return [
        {"index": 1, "title": "定目标", "detail": "用一句话写清这部短片要让观众感受到什么。"},
        {"index": 2, "title": "写分镜", "detail": "在纸上或表格里写 " + str(metrics["shot_count"]) + " 个左右的镜头：内容、景别、时长。"},
        {"index": 3, "title": "查节奏", "detail": "把时长排成一列，看有没有连续 3 个镜头时长接近；如果有，主动打破。"},
        {"index": 4, "title": "拍摄与剪辑", "detail": "按分镜拍完并剪辑，允许现场调整，但要记录调整原因。"},
        {"index": 5, "title": "提交", "detail": "上传成片、分镜表与创作说明（说明哪些地方偏离了原分镜以及为什么）。"},
    ]


def _estimate(level: str, default_minutes: int) -> int:
    if level == "imitate":
        return max(25, int(default_minutes * 0.6))
    if level == "variant":
        return default_minutes
    return int(default_minutes * 1.6)
