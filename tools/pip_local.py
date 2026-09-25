"""在工作区内安装 Python 依赖。

背景：本机 DSH 文件沙箱拒绝写入 tempfile.mkdtemp() 创建的 0o700 目录，
导致 pip 的临时解包目录不可写。此包装器把 mkdtemp 替换为 0o777 目录实现，
并把所有临时目录收敛到工作区 var/pip-tmp 下，从而让 pip 正常工作。
"""

from __future__ import annotations

import os
import pathlib
import random
import string
import sys
import tempfile

WORKSPACE = pathlib.Path(__file__).resolve().parent.parent
TMP = WORKSPACE / "var" / "pip-tmp"
TMP.mkdir(parents=True, exist_ok=True)

_ALPHABET = string.ascii_lowercase + string.digits


def _mkdtemp(suffix: str = "", prefix: str = "tmp", dir: str | None = None) -> str:
    base = pathlib.Path(dir) if dir else TMP
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(100000):
        name = prefix + "".join(random.choices(_ALPHABET, k=10)) + suffix
        path = base / name
        try:
            os.mkdir(path, 0o777)
        except FileExistsError:
            continue
        except PermissionError:
            continue
        return str(path)
    raise FileExistsError("unable to create temp dir")


tempfile.mkdtemp = _mkdtemp  # type: ignore[assignment]
tempfile.tempdir = str(TMP)
os.environ["TMPDIR"] = str(TMP)
os.environ["TEMP"] = str(TMP)
os.environ["TMP"] = str(TMP)

from pip._internal.cli.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
