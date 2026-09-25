"""作业反馈装配（§4.4 + P1 分镜文本评分）。

反馈结构固定为：参考证据 → 作业证据 → 差异 → 与本次学习目标的关系 → 一个可执行修改建议。
分镜文本评分与成片评分分开呈现，不混算出单一总分。
"""

from __future__ import annotations

import re
from typing import Any

from .compare import align_shots, build_evidence, build_suggestions
from .intents import get_intent
from .metrics import check_constraints, compute_metrics, metric_diff

SCALE_KEYWORDS = {
    "大远景": "extreme_wide",
    "远景": "extreme_wide",
    "全景": "wide",
    "中景": "medium",
    "中近景": "medium_close",
    "近景": "close_up",
    "特写": "extreme_close_up",
}
REASON_MARKERS = ("因为", "为了", "目的是", "理由是", "之所以", "以便")


def build_feedback(
    *,
    reference: dict[str, Any],
    submission: dict[str, Any],
    task: dict[str, Any],
    storyboard_text: str = "",
) -> dict[str, Any]:
    intent = str(task.get("intent") or reference.get("intent") or "shot_language")
    spec = get_intent(intent)
    ref_shots = reference.get("shots") or []
    sub_shots = submission.get("shots") or []
    ref_metrics = compute_metrics(ref_shots, duration_ms=int(reference.get("duration_ms") or 0))
    sub_metrics = compute_metrics(sub_shots, duration_ms=int(submission.get("duration_ms") or 0))
    constraints = task.get("constraints") or {}

    alignments = align_shots(ref_shots, sub_shots)
    constraint_results = check_constraints(sub_metrics, constraints)
    suggestions = build_suggestions(
        reference_metrics=ref_metrics,
        submission_metrics=sub_metrics,
        alignments=alignments,
        constraint_results=constraint_results,
        intent=intent,
        intent_goal=spec.practice_emphasis,
    )

    matched = [a for a in alignments if a.get("certainty") != "unmatched"]
    summary = (
        "参考片 "
        + str(ref_metrics["shot_count"])
        + " 个镜头（平均 "
        + format(ref_metrics["shot_duration_mean_ms"] / 1000.0, ".1f")
        + " 秒），你的作业 "
        + str(sub_metrics["shot_count"])
        + " 个镜头（平均 "
        + format(sub_metrics["shot_duration_mean_ms"] / 1000.0, ".1f")
        + " 秒）；可对齐 "
        + str(len(matched))
        + " 组。"
        + ("未匹配镜头已标注，不计为错误。" if any(a["certainty"] == "unmatched" for a in alignments) else "")
    )

    storyboard_metrics = score_storyboard(storyboard_text) if storyboard_text.strip() else {}

    return {
        "metrics": metric_diff(ref_metrics, sub_metrics),
        "reference_metrics": ref_metrics,
        "submission_metrics": sub_metrics,
        "alignments": alignments,
        "suggestions": suggestions,
        "evidence": build_evidence(ref_shots, sub_shots),
        "constraint_results": constraint_results,
        "summary": summary,
        "storyboard_metrics": storyboard_metrics,
        "review_status": "unreviewed",
        "disclaimer": "结构差异为客观计算；语义评价与建议基于可核对证据，允许人工修改标签。",
    }


def score_storyboard(text: str) -> dict[str, Any]:
    """P1：文字分镜评分，与成片评分分开呈现。

    只做可解释的确定性检查，不给"原创度百分比"。
    """

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    shot_lines = [line for line in lines if re.search(r"(镜头|shot|镜号|\d+\s*[\.、:：]|[①-⑳])", line)]
    if not shot_lines:
        shot_lines = lines
    scales_found: list[str] = []
    reasons = 0
    durations: list[int] = []
    for line in shot_lines:
        for keyword, code in SCALE_KEYWORDS.items():
            if keyword in line and code not in scales_found:
                scales_found.append(code)
        if any(marker in line for marker in REASON_MARKERS):
            reasons += 1
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(秒|s\b)", line):
            try:
                durations.append(int(float(match.group(1)) * 1000))
            except ValueError:
                continue

    shot_count = len(shot_lines)
    checks = [
        {
            "key": "shot_count",
            "passed": shot_count >= 3,
            "detail": "识别到 " + str(shot_count) + " 条分镜描述（建议 3 条以上）",
        },
        {
            "key": "scale_variety",
            "passed": len(scales_found) >= 2,
            "detail": "出现 " + str(len(scales_found)) + " 种可识别景别"
            + ("：" + "、".join(scales_found) if scales_found else "（未写明景别）"),
        },
        {
            "key": "reason_stated",
            "passed": reasons >= 1,
            "detail": "有 " + str(reasons) + " 条写了选择理由（因为/为了/目的是）",
        },
        {
            "key": "duration_stated",
            "passed": bool(durations),
            "detail": "写了时长的分镜有 " + str(len(durations)) + " 条",
        },
    ]
    passed = sum(1 for item in checks if item["passed"])
    return {
        "mode": "storyboard_text",
        "note": "这是文字分镜的确定性检查，与成片结构评分分开呈现，不合并为单一总分。",
        "shot_lines": shot_count,
        "scales_found": scales_found,
        "checks": checks,
        "passed_count": passed,
        "total_count": len(checks),
        "total_duration_ms": sum(durations),
        "per_criterion": {item["key"]: item["passed"] for item in checks},
    }
