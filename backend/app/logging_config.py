"""日志配置：不输出密钥、口令与有效签名地址（§11）。"""

from __future__ import annotations

import logging
import re

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|authorization|token|password)\s*[=:]\s*\S+"),
    re.compile(r"token=[A-Za-z0-9_\-\.]+"),
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        redacted = message
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[redacted]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(env: str) -> None:
    level = logging.DEBUG if env in ("dev", "test") else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    if not any(isinstance(item, logging.StreamHandler) for item in root.handlers):
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("chai_jing").setLevel(level)
