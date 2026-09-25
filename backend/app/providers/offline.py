"""离线确定性分析器（未接入多模态模型时的可运行路径）。

定位说明（重要，避免被误当成真实模型能力）：
- 它不是多模态大模型，输出能力有明确上限；
- 只陈述可从画面/时间轴核对的事实：时间区间、时长、代表帧数量、
  平均亮度与主色倾向、镜头内相邻代表帧的像素变化量；
- 不做人脸/物体检测，因此景别统一输出 unknown（证据不足不得强行归类）；
- 运镜不做断言，只给出"画面变化量"这一观察，并在 unknowns 里说明局限；
- 所有输出带 provider=offline 标记，报告与导出中同样标明。

它的价值：在没有模型密钥的环境下让整条闭环可运行、可测试、可审计。
"""

from __future__ import annotations

from pathlib import Path

from ..media.frames import brightness_label, color_label, frame_difference, mean_rgb
from .base import ShotContext, ShotFinding, TranscriptResult


class OfflineVisionProvider:
    name = "offline"
    model_id = "offline-deterministic-v1"

    def analyze_shot(self, context: ShotContext, *, job_id: str) -> ShotFinding:
        frames = [f for f in context.frames if Path(f).exists()]
        observations: list[str] = []
        unknowns: list[str] = [
            "本机未接入多模态模型：作者意图与表达效果无法核实",
            "未做人脸/物体检测：景别无法判定，故记为 unknown",
        ]
        tags: list[str] = []

        duration_s = context.duration_ms / 1000.0
        observations.append(
            context.shot_ref
            + "：时间区间 "
            + format(context.start_ms / 1000.0, ".2f")
            + "s—"
            + format(context.end_ms / 1000.0, ".2f")
            + "s，时长 "
            + format(duration_s, ".2f")
            + " 秒，提供 "
            + str(len(frames))
            + " 张代表帧"
        )

        if frames:
            rgb = mean_rgb(frames[0])
            if rgb is not None:
                observations.append(
                    "首帧平均色 RGB("
                    + str(rgb[0])
                    + ","
                    + str(rgb[1])
                    + ","
                    + str(rgb[2])
                    + ")，"
                    + brightness_label(rgb)
                    + "，"
                    + color_label(rgb)
                )
                tags.append("color_temperature")
            if len(frames) >= 2:
                diffs: list[float] = []
                for a, b in zip(frames, frames[1:]):
                    value = frame_difference(a, b)
                    if value is not None:
                        diffs.append(value)
                if diffs:
                    peak = max(diffs)
                    mean = sum(diffs) / len(diffs)
                    observations.append(
                        "镜头内相邻代表帧平均差异 "
                        + format(mean, ".1f")
                        + "/255，最大 "
                        + format(peak, ".1f")
                        + "/255"
                    )
                    tags.append("shot_motion_evidence")
                    if peak >= 40:
                        unknowns.append("画面变化较大，但仅凭代表帧无法区分主体运动与摄影机运动")

        movement = self._movement_hint(context)

        return ShotFinding(
            observation="；".join(observations),
            shot_scale="unknown",
            camera_motion="unknown",
            interpretation=self._structural_role(movement),
            alternative=self._alternative(context),
            narrative_function=movement,
            knowledge_tags=tags,
            unknowns=unknowns,
            confidence=0.25,
            provider_request_id="",
            raw={"provider": "offline", "movement_hint": movement},
        )

    @staticmethod
    def _movement_hint(context: ShotContext) -> str:
        duration_s = context.duration_ms / 1000.0
        if duration_s < 1.2:
            return "快速切换"
        if duration_s > 8.0:
            return "长镜头停留"
        return "常规时长"

    @staticmethod
    def _structural_role(movement: str) -> str:
        if movement == "快速切换":
            return "结构上属于快节奏段落，可能是密集切换中的一个信息点（是否承担强调作用需人工核对）"
        if movement == "长镜头停留":
            return "结构上属于停留段，画面在同一空间内持续推进（是否用于积累情绪需人工核对）"
        return "结构上为常规叙事单元，承接前后镜头的信息（具体修辞作用需人工核对）"

    @staticmethod
    def _alternative(context: ShotContext) -> str:
        if context.duration_ms > 8000:
            return "尝试把这一段拆成 2—3 个更短的镜头，对比注意力分配的变化"
        if context.duration_ms < 1200:
            return "尝试把这一处切换放慢到 2 秒以上，观察信息是否更清楚"
        return "尝试改变这一镜头的景别（更近或更远），对比信息密度与情绪强度"


class NullAsrProvider:
    """未接入语音识别时的诚实实现：返回空转写，不臆造台词（§4.1）。"""

    name = "none"
    model_id = "none"

    def transcribe(self, audio_path: Path, *, duration_ms: int, job_id: str) -> TranscriptResult:
        return TranscriptResult(
            segments=[],
            language="",
            provider="none",
            note="未接入 ASR：台词列为空，视觉流程照常执行",
        )
