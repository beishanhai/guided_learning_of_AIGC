"""确定性结构指标（§4.4）。

只做可以客观计算的事：镜头数、镜头时长、平均镜头时长、景别分布。
景别未知时单列，不强行归类。
"""

from __future__ import annotations

from statistics import fmean
from typing import Any

from ..pipeline.schema import SHOT_SCALES


def _durations(shots: list[dict[str, Any]]) -> list[int]:
    out: list[int] = []
    for shot in shots:
        try:
            value = int(shot.get("end_ms", 0)) - int(shot.get("start_ms", 0))
        except (TypeError, ValueError):
            continue
        if value > 0:
            out.append(value)
    return out


def compute_metrics(shots: list[dict[str, Any]], *, duration_ms: int = 0) -> dict[str, Any]:
    durations = _durations(shots)
    shot_count = len(shots)
    scale_distribution: dict[str, int] = {key: 0 for key in SHOT_SCALES}
    motion_distribution: dict[str, int] = {
        "static": 0,
        "pan": 0,
        "tilt": 0,
        "dolly": 0,
        "zoom": 0,
        "handheld": 0,
        "unknown": 0,
    }
    function_distribution: dict[str, int] = {}
    for shot in shots:
        scale = str(shot.get("shot_scale") or "unknown")
        scale_distribution[scale] = scale_distribution.get(scale, 0) + 1
        motion = str(shot.get("camera_motion") or "unknown")
        motion_distribution[motion] = motion_distribution.get(motion, 0) + 1
        function = str(shot.get("narrative_function") or "unknown")
        function_distribution[function] = function_distribution.get(function, 0) + 1

    known_scale_total = shot_count - scale_distribution.get("unknown", 0)
    metrics: dict[str, Any] = {
        "shot_count": shot_count,
        "duration_ms": int(duration_ms or sum(durations)),
        "shot_duration_list": durations,
        "shot_duration_mean_ms": int(round(fmean(durations))) if durations else 0,
        "shot_duration_median_ms": int(sorted(durations)[len(durations) // 2]) if durations else 0,
        "shot_duration_min_ms": min(durations) if durations else 0,
        "shot_duration_max_ms": max(durations) if durations else 0,
        "cut_rate_per_minute": round(shot_count / (duration_ms / 60000.0), 2)
        if duration_ms
        else 0.0,
        "scale_distribution": scale_distribution,
        "scale_unknown_count": scale_distribution.get("unknown", 0),
        "scale_known_count": known_scale_total,
        "scale_unknown_note": "景别未知的镜头单独统计，不并入任何景别（§4.4）",
        "motion_distribution": motion_distribution,
        "narrative_function_distribution": function_distribution,
        "has_dialogue_shots": sum(1 for shot in shots if str(shot.get("dialogue") or "").strip()),
    }
    return metrics


def pacing_curve(shots: list[dict[str, Any]], buckets: int = 8) -> list[dict[str, Any]]:
    """把时间轴等分为 buckets 段，给出每段的镜头数与平均镜头时长（节奏曲线）。"""

    if not shots:
        return []
    total_end = max(int(shot.get("end_ms", 0)) for shot in shots)
    if total_end <= 0:
        return []
    step = max(1, total_end // buckets)
    curve: list[dict[str, Any]] = []
    for index in range(buckets):
        start = index * step
        end = total_end if index == buckets - 1 else (index + 1) * step
        inside = [
            shot
            for shot in shots
            if int(shot.get("start_ms", 0)) < end and int(shot.get("end_ms", 0)) > start
        ]
        durations = _durations(inside)
        curve.append(
            {
                "bucket": index,
                "start_ms": start,
                "end_ms": end,
                "shot_count": len(inside),
                "mean_duration_ms": int(round(fmean(durations))) if durations else 0,
            }
        )
    return curve


def metric_diff(reference: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    def delta(key: str) -> dict[str, Any]:
        ref_value = reference.get(key, 0)
        sub_value = submission.get(key, 0)
        try:
            difference = sub_value - ref_value
        except TypeError:
            difference = None
        return {"reference": ref_value, "submission": sub_value, "delta": difference}

    return {
        "shot_count": delta("shot_count"),
        "shot_duration_mean_ms": delta("shot_duration_mean_ms"),
        "shot_duration_max_ms": delta("shot_duration_max_ms"),
        "cut_rate_per_minute": delta("cut_rate_per_minute"),
        "duration_ms": delta("duration_ms"),
        "scale_distribution": {
            "reference": reference.get("scale_distribution", {}),
            "submission": submission.get("scale_distribution", {}),
        },
        "motion_distribution": {
            "reference": reference.get("motion_distribution", {}),
            "submission": submission.get("motion_distribution", {}),
        },
    }


def check_constraints(
    metrics: dict[str, Any], constraints: dict[str, Any]
) -> list[dict[str, Any]]:
    """按任务约束核对作业结构，供反馈引用。"""

    results: list[dict[str, Any]] = []

    def add(key: str, passed: bool, detail: str) -> None:
        results.append({"constraint": key, "passed": bool(passed), "detail": detail})

    if "shot_count_range" in constraints:
        low, high = constraints["shot_count_range"]
        count = metrics.get("shot_count", 0)
        add("shot_count_range", low <= count <= high, "作业 " + str(count) + " 个镜头，要求 " + str(low) + "—" + str(high))
    if "max_mean_duration_ms" in constraints:
        value = metrics.get("shot_duration_mean_ms", 0)
        limit = constraints["max_mean_duration_ms"]
        add("max_mean_duration_ms", value <= limit, "平均镜头 " + str(value) + "ms，上限 " + str(limit) + "ms")
    if "min_mean_duration_ms" in constraints:
        value = metrics.get("shot_duration_mean_ms", 0)
        limit = constraints["min_mean_duration_ms"]
        add("min_mean_duration_ms", value >= limit, "平均镜头 " + str(value) + "ms，下限 " + str(limit) + "ms")
    if "min_distinct_scales" in constraints:
        distribution = metrics.get("scale_distribution", {})
        known = {k: v for k, v in distribution.items() if k != "unknown" and v > 0}
        need = constraints["min_distinct_scales"]
        add(
            "min_distinct_scales",
            len(known) >= need,
            "出现 " + str(len(known)) + " 种可判定景别，要求至少 " + str(need) + " 种",
        )
    if "duration_range_ms" in constraints:
        low, high = constraints["duration_range_ms"]
        value = metrics.get("duration_ms", 0)
        add("duration_range_ms", low <= value <= high, "成片时长 " + str(value) + "ms，要求 " + str(low) + "—" + str(high) + "ms")
    if "keep_shot_count" in constraints:
        target = constraints["keep_shot_count"]
        count = metrics.get("shot_count", 0)
        add("keep_shot_count", count == target, "作业 " + str(count) + " 个镜头，参考结构为 " + str(target))
    return results
