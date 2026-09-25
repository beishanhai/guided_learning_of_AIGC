"""开发用合成样片生成器。

重要说明（对应验收文档 §7.1 样本口径）：
- 这里生成的是**合成开发夹具**，不是验收样本集；
- 它们由 FFmpeg 的测试图源拼接而成，只用来验证流水线行为（硬切/长镜头/无声/竖屏/渐变转场）；
- 真正的验收需要 30 条经授权的真实短片（10 条调参 + 20 条留出），本脚本不能替代。
- 生成物目录下会写入 README.md 明确标注来源与用途。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import get_settings

README = """# 合成开发样片（不是验收样本集）

这些 MP4 由 FFmpeg 测试图源程序化生成，用途只有两个：

1. 验证拆解流水线在不同素材形态下的行为（快切、长镜头、无声、竖屏、渐变转场）；
2. 在没有授权真实素材时，让开发与自动化测试可以完整跑通闭环。

**它们不代表真实内容，也不能用于 AI 质量指标（镜头边界 F1、核心事实准确率等）的统计。**
验收需要按文档 §7.1 准备 30 条经授权的真实短片（10 条调参 + 20 条留出），并做双人标注。

| 文件 | 特征 | 用途 |
|---|---|---|
| fastcut_20s.mp4 | 10 个硬切，720p，含音轨（正弦音，无语音） | 镜头边界检测 |
| longtake_30s.mp4 | 单镜头长镜头，含音轨 | 长镜头加密采样 |
| silent_18s.mp4 | 无音轨，静态图源 | F03 无声视频不臆造台词 |
| vertical_15s.mp4 | 竖屏 608x1080，含硬切 | 横竖屏兼容 |
| dissolve_30s.mp4 | 叠化转场 | 转场单列 |
| fixtures/corrupt.mp4 | 截断的 MP4 | F02 损坏文件 |
| fixtures/fake.mp4 | 纯文本改扩展名 | F02 伪装扩展名 |
| fixtures/too_long_75s.mp4 | 75 秒，超过 60 秒上限 | F02 超时长 |
| fixtures/empty.mp4 | 0 字节 | F02 空文件 |
"""


def _run(args: list[str]) -> bool:
    settings = get_settings()
    try:
        from .media.ffmpeg import NO_WINDOW_FLAGS

        proc = subprocess.run(  # noqa: S603 - 参数数组
            [settings.ffmpeg_bin] + args,
            capture_output=True,
            timeout=600,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return proc.returncode == 0


def _encode(args: list[str], out: Path) -> bool:
    return _run(
        ["-hide_banner", "-nostats", "-loglevel", "error", "-y"]
        + args
        + [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ]
    )


def make_fastcut(out: Path) -> bool:
    # 每段同时改变色相与整体亮度，保证硬切处的画面变化量足够大（接近真实素材的切换强度）
    segments = []
    for index in range(10):
        hue = index * 36
        brightness = 0.28 if index % 2 == 0 else -0.30
        segments.append(
            "testsrc2=size=1280x720:rate=25:duration=2,"
            "hue=h=" + str(hue) + ":s=1.3,eq=brightness=" + format(brightness, ".2f")
            + "[v" + str(index) + "]"
        )
    graph = ";".join(segments) + ";" + "".join("[v" + str(i) + "]" for i in range(10)) + "concat=n=10:v=1:a=0[vout]"
    return _encode(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=320:duration=20",
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            "0:a",
        ],
        out,
    )


def make_longtake(out: Path) -> bool:
    return _encode(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=260:duration=30",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=25:duration=30",
            "-map",
            "1:v",
            "-map",
            "0:a",
        ],
        out,
    )


def make_silent(out: Path) -> bool:
    return _run(
        [
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=1280x720:rate=25:duration=18",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(out),
        ]
    )


def make_vertical(out: Path) -> bool:
    graph = (
        "[0:v]hue=h=0,eq=brightness=0.26[v0];"
        "[1:v]hue=h=130,eq=brightness=-0.30[v1];"
        "[2:v]hue=h=250,eq=brightness=0.24[v2];"
        "[v0][v1][v2]concat=n=3:v=1:a=0[vout]"
    )
    return _encode(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=608x1080:rate=25:duration=5",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=608x1080:rate=25:duration=5",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=608x1080:rate=25:duration=5",
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
        ],
        out,
    )


def make_dissolve(out: Path) -> bool:
    # 2 秒交叉叠化 + 明显的亮度落差，保证"累计变化量"可被窗口法识别
    graph = (
        "[0:v][1:v]xfade=transition=fade:duration=2:offset=9[x1];"
        "[x1][2:v]xfade=transition=fade:duration=2:offset=18[x2]"
    )
    return _encode(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=25:duration=11,eq=brightness=0.30",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=25:duration=11,hue=h=140,eq=brightness=-0.34",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=25:duration=11,hue=h=260,eq=brightness=0.28",
            "-filter_complex",
            graph,
            "-map",
            "[x2]",
        ],
        out,
    )


def make_fixtures(root: Path) -> dict[str, bool]:
    fixtures = root / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}

    results["too_long_75s.mp4"] = _run(
        [
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=25:duration=75",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(fixtures / "too_long_75s.mp4"),
        ]
    )
    results["empty.mp4"] = True
    (fixtures / "empty.mp4").write_bytes(b"")
    results["fake.mp4"] = True
    (fixtures / "fake.mp4").write_text("这不是视频文件，只是改成了 mp4 扩展名。\n" * 20, encoding="utf-8")

    good = root / "fastcut_20s.mp4"
    corrupt = fixtures / "corrupt.mp4"
    if good.exists():
        data = good.read_bytes()
        corrupt.write_bytes(data[: max(2048, len(data) // 3)])
        results["corrupt.mp4"] = True
    return results


def build_samples(target: Path | None = None, *, force: bool = False) -> dict[str, object]:
    settings = get_settings()
    root = Path(target) if target else settings.data_dir.parent.parent / "samples" / "dev"
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(README, encoding="utf-8")

    plan = {
        "fastcut_20s.mp4": make_fastcut,
        "longtake_30s.mp4": make_longtake,
        "silent_18s.mp4": make_silent,
        "vertical_15s.mp4": make_vertical,
        "dissolve_30s.mp4": make_dissolve,
    }
    results: dict[str, object] = {}
    for name, builder in plan.items():
        target_file = root / name
        if target_file.exists() and not force:
            results[name] = "exists"
            continue
        results[name] = builder(target_file)
    results["fixtures"] = make_fixtures(root)
    return results
