"""代表帧采样计划（§4.1）。

- 每个镜头先取首、中、尾三帧；
- 长镜头按固定间隔补采样；
- 全片最多 60 帧，超限时均匀抽样并显式标记覆盖不足。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from .scenes import ShotSpan


@dataclass
class FramePlan:
    shot_index: int
    position: str  # head | mid | tail | sample
    timestamp_ms: int
    frame_id: str


@dataclass
class FramePlanResult:
    frames: list[FramePlan]
    truncated: bool = False
    requested: int = 0
    notes: list[str] | None = None


def plan_frames(shots: list[ShotSpan], *, duration_ms: int) -> FramePlanResult:
    settings = get_settings()
    notes: list[str] = []
    requested: list[FramePlan] = []

    for shot in shots:
        start = max(0, shot.start_ms)
        end = min(duration_ms, shot.end_ms)
        span = max(1, end - start)
        positions: list[tuple[str, int]] = []
        head = start + min(200, span // 10)
        mid = start + span // 2
        tail = end - min(200, span // 10)
        positions.append(("head", min(head, end - 1)))
        positions.append(("mid", min(max(mid, start), end - 1)))
        positions.append(("tail", max(tail, start)))
        if span > settings.long_shot_sample_ms:
            step = settings.long_shot_sample_ms
            cursor = start + step
            while cursor < end - 300:
                positions.append(("sample", cursor))
                cursor += step
        seen: set[int] = set()
        for position, ts in positions:
            if ts in seen:
                continue
            seen.add(ts)
            requested.append(
                FramePlan(
                    shot_index=shot.index,
                    position=position,
                    timestamp_ms=int(ts),
                    frame_id="frame_" + str(shot.index + 1).zfill(3) + "_" + position,
                )
            )

    result = FramePlanResult(frames=requested, requested=len(requested), notes=notes)
    limit = settings.max_frames_per_asset
    if len(requested) > limit:
        stride = len(requested) / float(limit)
        kept: list[FramePlan] = []
        cursor = 0.0
        while len(kept) < limit and int(cursor) < len(requested):
            kept.append(requested[int(cursor)])
            cursor += stride
        result.frames = kept
        result.truncated = True
        result.notes = (
            notes
            + [
                "镜头/采样点过多，已均匀抽取 "
                + str(len(kept))
                + " 帧（上限 "
                + str(limit)
                + " 帧），部分镜头代表帧覆盖不足"
            ]
        )
    return result
