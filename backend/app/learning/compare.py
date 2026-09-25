"""结构对比与证据化建议（§4.4）。

对齐策略：
1. 优先按任务分镜 ID（shot_ref）一一对应；
2. 没有对应 ID 时，按"叙事功能 + 相对时间"提出候选匹配，标注 certainty=candidate；
3. 允许未匹配镜头，不强制一一对应，并在反馈里显示不确定性。
"""

from __future__ import annotations

from typing import Any

from .intents import function_label, motion_label, scale_label

MAX_TIME_DISTANCE = 0.35  # 相对时间差异上限（归一化到 0—1）


def _relative_position(shot: dict[str, Any], total_ms: int) -> float:
    if total_ms <= 0:
        return 0.0
    mid = (int(shot.get("start_ms", 0)) + int(shot.get("end_ms", 0))) / 2.0
    return max(0.0, min(1.0, mid / float(total_ms)))


def align_shots(
    reference: list[dict[str, Any]], submission: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ref_total = max([int(s.get("end_ms", 0)) for s in reference] or [0])
    sub_total = max([int(s.get("end_ms", 0)) for s in submission] or [0])

    alignments: list[dict[str, Any]] = []
    ref_used: set[str] = set()
    sub_used: set[str] = set()

    ref_by_ref = {str(s.get("shot_ref")): s for s in reference if s.get("shot_ref")}
    sub_by_ref = {str(s.get("shot_ref")): s for s in submission if s.get("shot_ref")}

    for shot_ref in sorted(set(ref_by_ref) & set(sub_by_ref)):
        ref_shot = ref_by_ref[shot_ref]
        sub_shot = sub_by_ref[shot_ref]
        ref_used.add(shot_ref)
        sub_used.add(shot_ref)
        alignments.append(_pair(ref_shot, sub_shot, "shot_id", "confirmed", ref_total, sub_total))

    remaining_sub = [s for s in submission if str(s.get("shot_ref")) not in sub_used]
    remaining_ref = [s for s in reference if str(s.get("shot_ref")) not in ref_used]

    candidates: list[tuple[float, dict, dict]] = []
    for sub_shot in remaining_sub:
        sub_pos = _relative_position(sub_shot, sub_total)
        for ref_shot in remaining_ref:
            same_function = str(sub_shot.get("narrative_function") or "unknown") == str(
                ref_shot.get("narrative_function") or "unknown"
            ) and str(sub_shot.get("narrative_function") or "unknown") != "unknown"
            distance = abs(sub_pos - _relative_position(ref_shot, ref_total))
            if not same_function and distance > MAX_TIME_DISTANCE:
                continue
            score = distance + (0.0 if same_function else 0.25)
            candidates.append((score, ref_shot, sub_shot))

    candidates.sort(key=lambda item: item[0])
    for score, ref_shot, sub_shot in candidates:
        ref_key = str(ref_shot.get("shot_ref"))
        sub_key = str(sub_shot.get("shot_ref"))
        if ref_key in ref_used or sub_key in sub_used:
            continue
        ref_used.add(ref_key)
        sub_used.add(sub_key)
        method = "narrative_function_time" if str(ref_shot.get("narrative_function")) == str(
            sub_shot.get("narrative_function")
        ) else "relative_time_candidate"
        alignments.append(_pair(ref_shot, sub_shot, method, "candidate", ref_total, sub_total))

    for shot in reference:
        key = str(shot.get("shot_ref"))
        if key in ref_used:
            continue
        alignments.append(
            {
                "reference_shot_ref": key,
                "submission_shot_ref": "",
                "method": "unmatched",
                "certainty": "unmatched",
                "reference_time_ms": int(shot.get("start_ms", 0)),
                "submission_time_ms": None,
                "note": "参考片有此镜头，作业中没有对应镜头（可能是刻意省略）",
                "reference_summary": _summary(shot),
            }
        )
    for shot in submission:
        key = str(shot.get("shot_ref"))
        if key in sub_used:
            continue
        alignments.append(
            {
                "reference_shot_ref": "",
                "submission_shot_ref": key,
                "method": "unmatched",
                "certainty": "unmatched",
                "reference_time_ms": None,
                "submission_time_ms": int(shot.get("start_ms", 0)),
                "note": "作业中出现参考片没有的镜头（可能是新增表达）",
                "submission_summary": _summary(shot),
            }
        )
    return alignments


def _pair(
    ref_shot: dict[str, Any],
    sub_shot: dict[str, Any],
    method: str,
    certainty: str,
    ref_total: int,
    sub_total: int,
) -> dict[str, Any]:
    ref_duration = int(ref_shot.get("end_ms", 0)) - int(ref_shot.get("start_ms", 0))
    sub_duration = int(sub_shot.get("end_ms", 0)) - int(sub_shot.get("start_ms", 0))
    return {
        "reference_shot_ref": str(ref_shot.get("shot_ref")),
        "submission_shot_ref": str(sub_shot.get("shot_ref")),
        "method": method,
        "certainty": certainty,
        "reference_time_ms": int(ref_shot.get("start_ms", 0)),
        "submission_time_ms": int(sub_shot.get("start_ms", 0)),
        "reference_duration_ms": ref_duration,
        "submission_duration_ms": sub_duration,
        "duration_delta_ms": sub_duration - ref_duration,
        "relative_time_delta": round(
            _relative_position(sub_shot, sub_total) - _relative_position(ref_shot, ref_total), 3
        ),
        "reference_summary": _summary(ref_shot),
        "submission_summary": _summary(sub_shot),
        "note": "按任务分镜 ID 对齐"
        if certainty == "confirmed"
        else "按叙事功能与相对时间提出的候选匹配，需人工确认",
    }


def _summary(shot: dict[str, Any]) -> str:
    return (
        "景别 "
        + scale_label(str(shot.get("shot_scale") or "unknown"))
        + "／运镜 "
        + motion_label(str(shot.get("camera_motion") or "unknown"))
        + "／功能 "
        + function_label(str(shot.get("narrative_function") or "unknown"))
        + "／时长 "
        + format((int(shot.get("end_ms", 0)) - int(shot.get("start_ms", 0))) / 1000.0, ".1f")
        + "s"
    )


def build_suggestions(
    *,
    reference_metrics: dict[str, Any],
    submission_metrics: dict[str, Any],
    alignments: list[dict[str, Any]],
    constraint_results: list[dict[str, Any]],
    intent: str,
    intent_goal: str,
) -> list[dict[str, Any]]:
    """每条建议都包含：参考证据 → 作业证据 → 差异 → 与学习目标的关系 → 一个可执行动作。"""

    suggestions: list[dict[str, Any]] = []
    ref_count = int(reference_metrics.get("shot_count") or 0)
    sub_count = int(submission_metrics.get("shot_count") or 0)
    ref_mean = int(reference_metrics.get("shot_duration_mean_ms") or 0)
    sub_mean = int(submission_metrics.get("shot_duration_mean_ms") or 0)

    def add(priority: int, target: str, action: str, goal_link: str) -> None:
        suggestions.append(
            {
                "id": "sug_" + str(len(suggestions) + 1).zfill(2),
                "priority": priority,
                "target": target,
                "action": action,
                "goal_link": goal_link,
            }
        )

    if sub_count != ref_count and ref_count > 0:
        direction = "偏少" if sub_count < ref_count else "偏多"
        add(
            1,
            "shot_count",
            "把作业的 "
            + str(sub_count)
            + " 个镜头调整为接近参考片的 "
            + str(ref_count)
            + " 个："
            + ("合并两个信息重复的镜头" if sub_count > ref_count else "把信息最密的一个镜头拆成两个"),
            "参考片用 " + str(ref_count) + " 个镜头完成这段信息，你的作业是 " + str(sub_count)
            + " 个（" + direction + "）。本次学习目标关注" + intent_goal + "，镜头数量直接影响信息节奏。",
        )

    if ref_mean and abs(sub_mean - ref_mean) >= max(300, int(ref_mean * 0.25)):
        action = (
            "把平均镜头时长从 "
            + format(sub_mean / 1000.0, ".1f")
            + " 秒压到 "
            + format(ref_mean / 1000.0, ".1f")
            + " 秒左右：优先缩短没有新信息的镜头"
            if sub_mean > ref_mean
            else "把平均镜头时长从 "
            + format(sub_mean / 1000.0, ".1f")
            + " 秒放宽到 "
            + format(ref_mean / 1000.0, ".1f")
            + " 秒左右：给关键画面多留 0.5—1 秒"
        )
        add(
            2,
            "shot_duration_mean_ms",
            action,
            "参考片平均 "
            + format(ref_mean / 1000.0, ".1f")
            + " 秒，你的作业平均 "
            + format(sub_mean / 1000.0, ".1f")
            + " 秒。节奏差异会让同一段信息被感知成不同的紧迫度。",
        )

    ref_scales = {
        k: v for k, v in (reference_metrics.get("scale_distribution") or {}).items() if k != "unknown" and v
    }
    sub_scales = {
        k: v for k, v in (submission_metrics.get("scale_distribution") or {}).items() if k != "unknown" and v
    }
    if ref_scales and sub_scales and set(ref_scales) != set(sub_scales):
        missing = sorted(set(ref_scales) - set(sub_scales))
        if missing:
            add(
                3,
                "scale_distribution",
                "补一个" + "、".join(scale_label(item) for item in missing) + "镜头，把参考片的景别层次补齐",
                "参考片出现了 " + "、".join(scale_label(k) for k in sorted(ref_scales))
                + "，作业只有 " + "、".join(scale_label(k) for k in sorted(sub_scales))
                + "。景别层次是本次学习目标的核心手段之一。",
            )

    unmatched_ref = [a for a in alignments if a["certainty"] == "unmatched" and a["reference_shot_ref"]]
    if unmatched_ref:
        first = unmatched_ref[0]
        add(
            4,
            "alignment",
            "在 "
            + format((first.get("reference_time_ms") or 0) / 1000.0, ".1f")
            + " 秒附近（参考片 "
            + str(first.get("reference_shot_ref"))
            + "）补回一个对应镜头，或说明为什么刻意省略",
            "参考片在这里安排了 " + str(first.get("reference_summary")) + "，作业中找不到对应镜头。"
            + "如果是有意改变结构，请在创作说明里写清理由——有意改变结构同样可以得分。",
        )

    for result in constraint_results:
        if result.get("passed"):
            continue
        add(
            2,
            result.get("constraint", "constraint"),
            "按任务约束调整：" + str(result.get("detail")),
            "这是本次任务的明确约束，直接决定评价量表的第一项。",
        )

    if not suggestions:
        add(
            5,
            "general",
            "保持当前结构，做一次微调：挑 1 个镜头改变景别，观察观众注意力如何被重新分配",
            "作业结构与参考片已经接近，下一步是把" + intent_goal + "从复现推进到主动控制。",
        )

    suggestions.sort(key=lambda item: item["priority"])
    return suggestions


def build_evidence(
    reference_shots: list[dict[str, Any]], submission_shots: list[dict[str, Any]]
) -> dict[str, Any]:
    def collect(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for shot in shots:
            out.append(
                {
                    "shot_ref": shot.get("shot_ref"),
                    "start_ms": shot.get("start_ms"),
                    "end_ms": shot.get("end_ms"),
                    "frames": shot.get("frame_keys") or [],
                    "observation": shot.get("observation"),
                    "knowledge_ids": shot.get("knowledge_ids") or [],
                    "unknowns": shot.get("unknowns") or [],
                }
            )
        return out

    return {"reference": collect(reference_shots), "submission": collect(submission_shots)}
