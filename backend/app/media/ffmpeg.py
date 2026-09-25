"""FFmpeg / ffprobe 封装。

安全约束（§11）：
- FFmpeg 一律以参数数组执行，不拼接 shell；
- 每次调用有超时，输出量受限；
- 失败信息结构化返回，不把原始命令与密钥写入日志。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..config import get_settings
from ..errors import SemanticError

# Windows：父进程没有控制台时，每次调用 ffmpeg/ffprobe 都会闪一个新控制台窗口。
# 一次分析会调用几十次（探测 + 解码校验 + 每镜头抽帧），必须显式禁止建窗。
NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

_SCORE_RE = re.compile(r"^lavfi\.scene_score=([0-9.eE+-]+)$")
_PTS_RE = re.compile(r"pts_time:([0-9.eE+-]+)")


def binaries_available() -> tuple[bool, bool]:
    settings = get_settings()
    return (
        shutil.which(settings.ffmpeg_bin) is not None,
        shutil.which(settings.ffprobe_bin) is not None,
    )


def run_ffmpeg(args: list[str], *, timeout: int, capture: bool = True) -> subprocess.CompletedProcess:
    """执行 ffmpeg/ffprobe；args 为完整参数数组（不含可执行文件）。"""

    settings = get_settings()
    executable = args[0]
    binary = settings.ffmpeg_bin if executable == "ffmpeg" else settings.ffprobe_bin
    cmd = [binary] + list(args[1:])
    try:
        return subprocess.run(  # noqa: S603 - 参数数组执行，无 shell
            cmd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SemanticError("媒体处理超时（" + str(timeout) + " 秒）") from exc
    except FileNotFoundError as exc:
        raise SemanticError("未找到 " + binary + "，请检查部署环境") from exc


def ffprobe_json(path: Path) -> dict:
    settings = get_settings()
    proc = run_ffmpeg(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=settings.probe_timeout_seconds,
    )
    if proc.returncode != 0:
        raise SemanticError("无法解析媒体文件（ffprobe 失败）")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SemanticError("ffprobe 输出不是合法 JSON") from exc


def decode_check(path: Path, *, timeout: int = 120) -> tuple[bool, str]:
    """完整解码校验：能解码但无有效视频流时同样视为失败。"""

    proc = run_ffmpeg(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        timeout=timeout,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or "").strip()[:500]
    return True, ""


def extract_scene_scores(path: Path, *, width: int | None = None, timeout: int = 300) -> list[tuple[float, float]]:
    """逐帧场景得分序列（内容变化量），用于自适应阈值镜头切分。

    返回 [(pts_time_seconds, scene_score), ...]，按时间升序。
    """

    settings = get_settings()
    scale_width = width or settings.scene_analysis_width
    vf = "scale=" + str(scale_width) + ":-2,select='gte(scene,0)',metadata=print:file=-"
    proc = run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-an",
            "-vf",
            vf,
            "-f",
            "null",
            "-",
        ],
        timeout=timeout,
    )
    scores: list[tuple[float, float]] = []
    pending_pts: float | None = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        pts_match = _PTS_RE.search(line)
        if pts_match and line.startswith("frame:"):
            try:
                pending_pts = float(pts_match.group(1))
            except ValueError:
                pending_pts = None
            continue
        score_match = _SCORE_RE.match(line)
        if score_match:
            try:
                score = float(score_match.group(1))
            except ValueError:
                continue
            if pending_pts is not None:
                scores.append((pending_pts, score))
            pending_pts = None
    return scores


def extract_frame(path: Path, timestamp_ms: int, out_path: Path, *, timeout: int = 60) -> bool:
    """按原始时间戳抽一帧 JPEG。"""

    settings = get_settings()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    vf = "scale='min(" + str(settings.frame_max_width) + ",iw)':-2"
    proc = run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(max(0, timestamp_ms) / 1000.0),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-q:v",
            str(settings.frame_jpeg_quality),
            str(out_path),
        ],
        timeout=timeout,
    )
    return proc.returncode == 0 and out_path.exists()


def extract_audio_wav(path: Path, out_path: Path, *, sample_rate: int = 16000, timeout: int = 180) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "wav",
            str(out_path),
        ],
        timeout=timeout,
    )
    return proc.returncode == 0 and out_path.exists()


def make_analysis_copy(src: Path, dst: Path, *, height: int = 720, timeout: int = 300) -> bool:
    """生成 720p 分析副本（原始文件始终保留）。"""

    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            "scale=-2:'min(" + str(height) + ",ih)'",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(dst),
        ],
        timeout=timeout,
    )
    return proc.returncode == 0 and dst.exists()
