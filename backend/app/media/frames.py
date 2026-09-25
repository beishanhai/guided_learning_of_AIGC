"""从 JPEG 代表帧上做可核对的像素统计（供离线确定性分析器使用）。

这些统计是**可从画面核对的事实**，不是对作者意图的推测；
它们不用于判定景别与运镜，景别在证据不足时保持 unknown。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import get_settings
from .ffmpeg import NO_WINDOW_FLAGS


def _raw_pixels(path: Path, width: int, height: int, pix_fmt: str = "rgb24") -> bytes:
    settings = get_settings()
    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        "scale=" + str(width) + ":" + str(height),
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - 参数数组
            cmd,
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return b""
    return proc.stdout or b""


def mean_rgb(path: Path) -> tuple[int, int, int] | None:
    data = _raw_pixels(path, 1, 1)
    if len(data) < 3:
        return None
    return (data[0], data[1], data[2])


def gray_thumbnail(path: Path, size: int = 8) -> bytes:
    return _raw_pixels(path, size, size, "gray")


def frame_difference(path_a: Path, path_b: Path, *, size: int = 8) -> float | None:
    """两张代表帧的平均绝对亮度差（0—255），作为画面变化量的客观度量。"""

    a = gray_thumbnail(path_a, size)
    b = gray_thumbnail(path_b, size)
    if not a or not b or len(a) != len(b):
        return None
    total = sum(abs(x - y) for x, y in zip(a, b))
    return round(total / float(len(a)), 2)


def brightness_label(rgb: tuple[int, int, int]) -> str:
    value = (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000.0
    if value < 60:
        return "整体偏暗"
    if value < 140:
        return "中间调"
    return "整体偏亮"


def color_label(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    if max(r, g, b) - min(r, g, b) < 18:
        return "接近中性灰"
    if r >= g >= b:
        return "偏暖（红黄主导）"
    if b >= g >= r:
        return "偏冷（蓝青主导）"
    if g >= r and g >= b:
        return "偏绿"
    return "色彩构成均衡"
