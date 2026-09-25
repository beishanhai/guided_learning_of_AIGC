"""镜头边界检测（§4.1）。

方法：用 FFmpeg 逐帧内容变化量（lavfi.scene_score）建立序列，
再用自适应阈值（均值 + k·标准差，并夹在 [min, max] 区间）判定硬切。
- 单帧无法证明运镜，因此这里只产出镜头边界与变化量，不产出运镜结论；
- 转场（渐变）会被单列，因为分数呈平台状而非尖峰。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..config import get_settings


@dataclass
class ShotSpan:
    index: int
    start_ms: int
    end_ms: int
    cut_score: float = 0.0
    mean_score: float = 0.0
    peak_score: float = 0.0
    boundary_kind: str = "hard_cut"  # hard_cut | start | end
    width_transition: bool = False

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def shot_ref(self) -> str:
        return "shot_" + str(self.index + 1).zfill(3)


@dataclass
class SceneDetectionResult:
    shots: list[ShotSpan] = field(default_factory=list)
    threshold: float = 0.0
    score_count: int = 0
    mean_score: float = 0.0
    std_score: float = 0.0
    total_cuts: int = 0
    transitions: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    low_confidence: bool = False


def compute_threshold(scores: list[float]) -> tuple[float, float, float]:
    settings = get_settings()
    if not scores:
        return settings.scene_threshold_min, 0.0, 0.0
    mean = statistics.fmean(scores)
    std = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    raw = mean + settings.scene_threshold_k * std
    threshold = min(max(raw, settings.scene_threshold_min), settings.scene_threshold_max)
    return threshold, mean, std


def _windowed_change_runs(
    score_series: list[tuple[float, float]],
    *,
    window_seconds: float = 1.0,
    min_window_sum: float,
    min_duration_ms: int = 500,
) -> list[tuple[float, float, float]]:
    """用"1 秒窗口累计变化量"识别渐变转场。

    单帧阈值无法发现叠化：叠化把变化摊到几十帧上，每帧都很小。
    但同样时长窗口内的**累计**变化量比普通长镜头高一个数量级，
    因此按"窗口和 >= max(4 × 中位数窗口和, 绝对下限)"判定。
    """

    if len(score_series) < 6:
        return []
    times = [t for t, _ in score_series]
    values = [s for _, s in score_series]
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    fps = (1.0 / statistics.median(deltas)) if deltas else 25.0
    frames = max(6, int(round(fps * window_seconds)))
    if len(values) < frames * 2:
        return []

    window_sums: list[float] = []
    running = float(sum(values[:frames]))
    window_sums.append(running)
    for index in range(1, len(values) - frames + 1):
        running += values[index + frames - 1] - values[index - 1]
        window_sums.append(running)

    cutoff = max(min_window_sum, statistics.median(window_sums) * 4.0)
    runs: list[tuple[float, float, float]] = []
    start_index: int | None = None
    peak = 0.0
    for index, total in enumerate(window_sums):
        if total >= cutoff:
            if start_index is None:
                start_index = index
            peak = max(peak, total)
        else:
            if start_index is not None:
                end_index = index - 1 + frames
                if (times[min(end_index, len(times) - 1)] - times[start_index]) * 1000.0 >= min_duration_ms:
                    runs.append((times[start_index], times[min(end_index, len(times) - 1)], peak))
            start_index = None
            peak = 0.0
    if start_index is not None:
        end_index = min(len(times) - 1, len(window_sums) - 1 + frames)
        if (times[end_index] - times[start_index]) * 1000.0 >= min_duration_ms:
            runs.append((times[start_index], times[end_index], peak))
    return runs


def detect_shots(
    score_series: list[tuple[float, float]],
    *,
    duration_ms: int,
) -> SceneDetectionResult:
    settings = get_settings()
    result = SceneDetectionResult()
    result.score_count = len(score_series)
    if duration_ms <= 0:
        return result

    if not score_series:
        result.notes.append("无法获得逐帧变化量，退化为单镜头（需人工复核边界）")
        result.shots = [ShotSpan(0, 0, duration_ms, boundary_kind="start")]
        return result

    times = [t for t, _ in score_series]
    values = [s for _, s in score_series]
    threshold, mean, std = compute_threshold(values)
    result.threshold = round(threshold, 4)
    result.mean_score = round(mean, 4)
    result.std_score = round(std, 4)

    # 1) 找出超过阈值的候选切点（局部极大值优先）
    def _peaks(cutoff: float) -> list[tuple[float, float]]:
        found: list[tuple[float, float]] = []
        for i, (t, s) in enumerate(score_series):
            if s < cutoff or s <= 0:
                continue
            left = values[i - 1] if i > 0 else 0.0
            right = values[i + 1] if i + 1 < len(values) else 0.0
            if s >= left and s >= right:
                found.append((t * 1000.0, s))
        return found

    candidates = _peaks(threshold)
    if not candidates:
        # 这里**不做**统计回退：真实长镜头/持续运镜会产生大量小幅度噪声，
        # 用"均值 + kσ"回退会把它们误判成切点。宁可判为一个镜头并提示人工复核。
        result.notes.append("所有帧的内容变化量都低于阈值，判定为长镜头或静态素材（需人工复核边界）")

    # 2) 按最小镜头时长合并过密切点，保留窗口内最高分者
    merged: list[tuple[float, float]] = []
    for t_ms, score in candidates:
        if merged and (t_ms - merged[-1][0]) < settings.min_shot_ms:
            if score > merged[-1][1]:
                merged[-1] = (t_ms, score)
        else:
            merged.append((t_ms, score))

    # 3) 丢弃距开头/结尾过近的切点，边界由 0 与 duration 提供
    cuts = [(t, s) for t, s in merged if t > settings.min_shot_ms and (duration_ms - t) > settings.min_shot_ms]
    result.total_cuts = len(cuts)

    # 4) 转场识别：没有任何单帧达到切点阈值，但连续多帧持续抬升 -> 渐变转场（叠化/淡入淡出）
    #    这类变化不会被判定为镜头边界，只作为"转场单列"输出（§9：转场单列）。
    runs = _windowed_change_runs(
        score_series,
        min_window_sum=max(threshold * 0.3, settings.scene_threshold_min * 0.6),
        min_duration_ms=500,
    )
    cut_times = [int(round(t)) for t, _ in cuts]
    for start_s, end_s, peak in runs:
        start_ms = int(round(start_s * 1000))
        end_ms = int(round(end_s * 1000))
        # 窗口内包含硬切点说明这段累计变化来自那次切换，不是渐变转场
        if any(start_ms - 200 <= item <= end_ms + 200 for item in cut_times):
            continue
        result.transitions.append(
            {
                "timestamp_ms": start_ms,
                "end_ms": end_ms,
                "kind": "gradual_transition",
                "peak_window_sum": round(peak, 4),
                "overlaps_hard_cut": False,
                "note": "窗口累计变化量显著高于背景但无单帧达到切点阈值，疑似叠化/淡入淡出，需人工复核",
            }
        )

    boundaries: list[tuple[int, float, str]] = [(0, 0.0, "start")]
    for t_ms, score in cuts:
        kind = "dissolve" if any(abs(t_ms - item["timestamp_ms"]) < 1 for item in result.transitions) else "hard_cut"
        boundaries.append((int(round(t_ms)), score, kind))
    boundaries.append((int(duration_ms), 0.0, "end"))

    shots: list[ShotSpan] = []
    for i in range(len(boundaries) - 1):
        start_ms, score, kind = boundaries[i]
        end_ms = boundaries[i + 1][0]
        if end_ms <= start_ms:
            continue
        window = [s for t, s in score_series if start_ms <= t * 1000.0 < end_ms]
        shots.append(
            ShotSpan(
                index=len(shots),
                start_ms=start_ms,
                end_ms=end_ms,
                cut_score=round(score, 4),
                mean_score=round(statistics.fmean(window), 4) if window else 0.0,
                peak_score=round(max(window), 4) if window else 0.0,
                boundary_kind=kind,
                width_transition=kind == "dissolve",
            )
        )

    if len(shots) == 1:
        result.notes.append("未检测到硬切，判定为长镜头；已按长镜头加密采样")
    # 时间戳就近取整后可能出现 1 帧的空镜头，直接合并
    cleaned: list[ShotSpan] = []
    for shot in shots:
        if shot.duration_ms < 120 and cleaned:
            cleaned[-1].end_ms = shot.end_ms
            continue
        shot.index = len(cleaned)
        cleaned.append(shot)

    result.shots = cleaned
    return result
