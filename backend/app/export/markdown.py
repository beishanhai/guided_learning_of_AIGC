"""Markdown 报告导出（§1.1 导出与删除 / §5.3）。

必须与所选分析版本一致：导出内容全部来自同一条 Analysis 记录。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..learning.intents import (
    function_label,
    get_intent,
    motion_label,
    scale_label,
    build_shot_explanations,
)


def _ms(value: Any) -> str:
    try:
        return format(int(value) / 1000.0, ".2f") + "s"
    except (TypeError, ValueError):
        return "-"


def render_analysis_markdown(
    *,
    analysis: dict[str, Any],
    project: dict[str, Any] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> str:
    intent = str(analysis.get("intent") or "shot_language")
    spec = get_intent(intent)
    coverage = analysis.get("coverage") or {}
    media = analysis.get("media") or {}
    metrics = analysis.get("metrics") or {}
    shots = analysis.get("shots") or []
    lines: list[str] = []

    lines.append("# 拆镜学分析报告：" + str(project.get("title") if project else analysis.get("id")))
    lines.append("")
    lines.append("- 分析 ID：" + str(analysis.get("id")))
    lines.append("- 版本：v" + str(analysis.get("version")))
    lines.append("- 学习意图：" + spec.label)
    lines.append("- 导出时间：" + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    lines.append("- 模型 / Prompt / Schema / 知识版本："
                 + str(analysis.get("model_id"))
                 + " / " + str(analysis.get("prompt_version"))
                 + " / " + str(analysis.get("schema_version"))
                 + " / " + str(analysis.get("knowledge_version")))
    lines.append("- 生成方式：" + str(coverage.get("provider") or "unknown")
                 + "（offline 表示未接入多模态模型，仅为确定性统计结果）")
    lines.append("- 状态：" + str(analysis.get("status")) + ("（partial：部分镜头未完成）" if coverage.get("partial") else ""))
    lines.append("")
    lines.append("> 阅读约定：观察事实可以从画面或声音核对；表达假设只是可能的作用，不代表原作者陈述；")
    lines.append("> 未知项明确列出，不用推测填充。")
    lines.append("")

    lines.append("## 1. 素材信息")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|---|---|")
    lines.append("| 时长 | " + _ms(media.get("duration_ms")) + " |")
    lines.append("| 分辨率 | " + str(media.get("width")) + "×" + str(media.get("height")) + " |")
    lines.append("| 帧率 | " + str(media.get("fps")) + " fps" + ("（变帧率）" if media.get("is_vfr") else "") + " |")
    lines.append("| 容器 / 编码 | " + str(media.get("container")) + " / " + str(media.get("video_codec")) + " |")
    lines.append("| 音轨 | " + ("有" if media.get("has_audio") else "无") + " |")
    lines.append("| 镜头数 | " + str(metrics.get("shot_count")) + " |")
    lines.append("| 平均镜头时长 | " + _ms(metrics.get("shot_duration_mean_ms")) + " |")
    lines.append("")

    lines.append("## 2. 结构指标（确定性计算）")
    lines.append("")
    lines.append("- 镜头数：" + str(metrics.get("shot_count")))
    lines.append("- 平均 / 中位 / 最短 / 最长：" + _ms(metrics.get("shot_duration_mean_ms"))
                 + " / " + _ms(metrics.get("shot_duration_median_ms"))
                 + " / " + _ms(metrics.get("shot_duration_min_ms"))
                 + " / " + _ms(metrics.get("shot_duration_max_ms")))
    lines.append("- 切镜频率：" + str(metrics.get("cut_rate_per_minute")) + " 次/分钟")
    lines.append("- 景别分布：")
    for key, value in (metrics.get("scale_distribution") or {}).items():
        if value:
            lines.append("  - " + scale_label(key) + "（" + key + "）：" + str(value))
    if metrics.get("scale_unknown_count"):
        lines.append("  - 未知景别单独统计：" + str(metrics["scale_unknown_count"]) + " 个，不并入任何景别")
    lines.append("")

    lines.append("## 3. 镜头逐条拆解（" + spec.label + "）")
    lines.append("")
    explanations = {
        item["shot_ref"]: item for item in build_shot_explanations(shots, intent)
    }
    for shot in shots:
        ref = str(shot.get("shot_ref"))
        explanation = explanations.get(ref, {})
        lines.append("### " + ref + "  " + _ms(shot.get("start_ms")) + " — " + _ms(shot.get("end_ms"))
                     + "（" + _ms(int(shot.get("end_ms", 0)) - int(shot.get("start_ms", 0))) + "）")
        lines.append("")
        lines.append("- **观察事实**：" + str(shot.get("observation") or "-"))
        lines.append("- **景别**：" + scale_label(str(shot.get("shot_scale"))) + "（" + str(shot.get("shot_scale")) + "）")
        lines.append("- **运镜**：" + motion_label(str(shot.get("camera_motion"))) + "（" + str(shot.get("camera_motion")) + "）")
        lines.append("- **叙事功能**：" + function_label(str(shot.get("narrative_function"))))
        if shot.get("dialogue"):
            lines.append("- **台词/字幕**：" + str(shot["dialogue"]))
        if explanation.get("intent_reading"):
            lines.append("- **本次学习意图解读**：" + str(explanation["intent_reading"]))
        if shot.get("interpretation"):
            lines.append("- **表达假设（非作者陈述）**：" + str(shot["interpretation"]))
        if shot.get("alternative"):
            lines.append("- **可尝试的替代设计**：" + str(shot["alternative"]))
        evidence = shot.get("evidence") or []
        if evidence:
            stamps = ["@" + _ms(item.get("timestamp_ms")) + " (" + str(item.get("frame_id")) + ")" for item in evidence]
            lines.append("- **证据**：" + "、".join(stamps))
        if shot.get("knowledge_ids"):
            lines.append("- **关联知识卡片**：" + "、".join(str(k) for k in shot["knowledge_ids"]))
        if shot.get("unknowns"):
            lines.append("- **不确定性**：" + "；".join(str(u) for u in shot["unknowns"]))
        lines.append("")

    lines.append("## 4. 台词转写")
    lines.append("")
    transcript = analysis.get("transcript") or {}
    segments = transcript.get("segments") or []
    if not segments:
        lines.append("- 无可用转写（" + str(transcript.get("note") or "素材无音轨") + "）")
    else:
        for seg in segments:
            lines.append("- [" + _ms(seg.get("start_ms")) + "—" + _ms(seg.get("end_ms")) + "] " + str(seg.get("text")))
    lines.append("")

    unknowns = analysis.get("unknowns") or {}
    lines.append("## 5. 未知项与建议复核方式")
    lines.append("")
    if unknowns.get("items"):
        for item in unknowns["items"]:
            lines.append("- " + str(item))
    else:
        lines.append("- 无")
    for note in (coverage.get("notes") or []):
        lines.append("- 流水线说明：" + str(note))
    lines.append("")

    if tasks:
        lines.append("## 6. 学习任务")
        lines.append("")
        for task in tasks:
            lines.append("### " + str(task.get("title")))
            lines.append("")
            lines.append("- 级别：" + str(task.get("level")) + "，意图：" + str(task.get("intent")))
            lines.append("- 目标：" + str(task.get("objective")))
            lines.append("- 预计用时：" + str(task.get("estimated_minutes")) + " 分钟")
            lines.append("- 步骤：")
            for step in task.get("steps") or []:
                lines.append("  " + str(step.get("index")) + ". **" + str(step.get("title")) + "**：" + str(step.get("detail")))
            lines.append("- 提交要求：")
            for item in task.get("submission_requirements") or []:
                lines.append("  - " + str(item))
            lines.append("- 评价量表（每项 0—4 分）：")
            for item in task.get("rubric") or []:
                lines.append("  - " + str(item.get("criterion")) + "：" + str(item.get("scale")))
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("本报告由拆镜学原型生成。生成方式：" + str(coverage.get("provider") or "unknown") + "。")
    if str(coverage.get("provider")) == "offline":
        lines.append("注意：本次未接入多模态模型，报告中不含画面语义判断，景别与运镜保持 unknown。")
    return "\n".join(lines) + "\n"


def render_feedback_markdown(*, feedback: dict[str, Any], task: dict[str, Any] | None = None) -> str:
    lines = ["# 作业反馈报告", ""]
    lines.append("- 反馈 ID：" + str(feedback.get("id")))
    lines.append("- 生成时间：" + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(str(feedback.get("summary") or ""))
    lines.append("")
    lines.append("## 结构差异")
    lines.append("")
    metrics = feedback.get("metrics") or {}
    lines.append("| 指标 | 参考片 | 作业 | 差异 |")
    lines.append("|---|---|---|---|")
    for key, label in (
        ("shot_count", "镜头数"),
        ("shot_duration_mean_ms", "平均镜头时长(ms)"),
        ("shot_duration_max_ms", "最长镜头(ms)"),
        ("cut_rate_per_minute", "切镜频率(次/分)"),
        ("duration_ms", "总时长(ms)"),
    ):
        item = metrics.get(key) or {}
        lines.append(
            "| " + label + " | " + str(item.get("reference")) + " | "
            + str(item.get("submission")) + " | " + str(item.get("delta")) + " |"
        )
    lines.append("")
    lines.append("## 建议（参考证据 → 作业证据 → 差异 → 与目标关系 → 可执行动作）")
    lines.append("")
    for item in feedback.get("suggestions") or []:
        lines.append("### " + str(item.get("id")) + " · " + str(item.get("target")))
        lines.append("")
        lines.append("- **可执行动作**：" + str(item.get("action")))
        lines.append("- **与学习目标的关系**：" + str(item.get("goal_link")))
        lines.append("")
    lines.append("## 镜头对齐")
    lines.append("")
    lines.append("| 参考镜头 | 作业镜头 | 对齐方式 | 确定性 | 参考摘要 | 作业摘要 |")
    lines.append("|---|---|---|---|---|---|")
    for item in feedback.get("alignments") or []:
        lines.append(
            "| " + str(item.get("reference_shot_ref") or "-")
            + " | " + str(item.get("submission_shot_ref") or "-")
            + " | " + str(item.get("method"))
            + " | " + str(item.get("certainty"))
            + " | " + str(item.get("reference_summary") or "-")
            + " | " + str(item.get("submission_summary") or "-") + " |"
        )
    lines.append("")
    storyboard = feedback.get("storyboard_metrics") or {}
    if storyboard:
        lines.append("## 文字分镜评分（与成片评分分开呈现）")
        lines.append("")
        for check in storyboard.get("checks") or []:
            lines.append("- " + ("通过" if check.get("passed") else "未通过") + "：" + str(check.get("detail")))
        lines.append("")
    if task:
        lines.append("## 任务")
        lines.append("")
        lines.append("- " + str(task.get("title")))
        lines.append("- 评价重点：" + str(task.get("evaluation_focus") or ""))
    return "\n".join(lines) + "\n"
