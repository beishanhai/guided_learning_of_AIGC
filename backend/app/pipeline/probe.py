"""媒体探测与准入校验（§1.1 上传边界 / F02）。

服务端以真实解码结果为准，不信扩展名。
"""

from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ..errors import PayloadTooLarge, SemanticError, UnsupportedMedia
from ..media.ffmpeg import decode_check, ffprobe_json


def _fraction(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def probe_file(path: Path) -> dict:
    """返回规范化探测结果。"""

    info = ffprobe_json(path)
    fmt = info.get("format") or {}
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration_s = 0.0
    for candidate in (fmt.get("duration"), (video or {}).get("duration")):
        try:
            duration_s = float(candidate)
            break
        except (TypeError, ValueError):
            continue

    avg_fps = _fraction((video or {}).get("avg_frame_rate"))
    raw_fps = _fraction((video or {}).get("r_frame_rate"))
    n_frames = 0
    try:
        n_frames = int((video or {}).get("nb_frames") or 0)
    except (TypeError, ValueError):
        n_frames = 0
    is_vfr = bool(avg_fps and raw_fps and abs(avg_fps - raw_fps) > 0.01)

    containers = [item.strip() for item in str(fmt.get("format_name") or "").split(",") if item.strip()]

    return {
        "format_name": fmt.get("format_name") or "",
        "containers": containers,
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "duration_ms": int(round(duration_s * 1000)),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video_codec": (video or {}).get("codec_name") or "",
        "video_profile": (video or {}).get("profile") or "",
        "pix_fmt": (video or {}).get("pix_fmt") or "",
        "audio_codec": (audio or {}).get("codec_name") or "",
        "width": int((video or {}).get("width") or 0),
        "height": int((video or {}).get("height") or 0),
        "avg_fps": round(avg_fps, 3),
        "raw_fps": round(raw_fps, 3),
        "nb_frames": n_frames,
        "is_vfr": is_vfr,
        "rotation": _rotation(video or {}),
    }


def _rotation(stream: dict) -> int:
    tags = stream.get("tags") or {}
    try:
        return int(tags.get("rotate") or 0)
    except (TypeError, ValueError):
        return 0


def validate_probe(probe: dict) -> None:
    """准入校验；不通过即抛出带错误码的异常（F02）。"""

    settings = get_settings()
    size = int(probe.get("size_bytes") or 0)
    if size <= 0:
        raise UnsupportedMedia("文件为空或无法读取", code="empty_file")
    if size > settings.max_upload_bytes:
        raise PayloadTooLarge(
            "文件超过上限 " + str(settings.max_upload_bytes // (1024 * 1024)) + "MB",
            code="file_too_large",
        )
    if not probe.get("has_video"):
        raise UnsupportedMedia("未检测到视频流", code="no_video_stream")

    containers = set(probe.get("containers") or [])
    if containers and not containers.intersection(settings.allowed_containers):
        raise UnsupportedMedia(
            "不支持的容器格式：" + (probe.get("format_name") or "unknown"),
            code="unsupported_container",
        )
    codec = (probe.get("video_codec") or "").lower()
    if codec not in settings.allowed_video_codecs:
        raise UnsupportedMedia("不支持的视频编码：" + (codec or "unknown"), code="unsupported_codec")

    duration = int(probe.get("duration_ms") or 0)
    if duration <= 0:
        raise UnsupportedMedia("无法读取时长，文件可能损坏", code="broken_file")
    if duration < settings.min_duration_ms or duration > settings.max_duration_ms:
        raise SemanticError(
            "时长需在 "
            + str(settings.min_duration_ms // 1000)
            + "—"
            + str(settings.max_duration_ms // 1000)
            + " 秒之间，实际 "
            + str(round(duration / 1000, 1))
            + " 秒",
            code="duration_out_of_range",
        )
    height = int(probe.get("height") or 0)
    if height > settings.max_height:
        raise SemanticError(
            "分辨率超过 " + str(settings.max_height) + "p",
            code="resolution_too_large",
        )


def validate_decodable(path: Path) -> None:
    ok, detail = decode_check(path, timeout=get_settings().probe_timeout_seconds * 4)
    if not ok:
        raise UnsupportedMedia(
            "文件无法完整解码，可能已损坏或编码不受支持",
            code="decode_failed",
            details={"stderr": detail},
        )
