"""外部模型适配层（§3 / §2.2 引用边界）。

所有供应商差异封装在这里：更换模型只需改配置，
学习规则与反馈规则不感知具体供应商（前端不持有密钥，模型调用只在后端）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from ..config import get_settings
from ..errors import ProviderError

T = TypeVar("T")


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int | None = None,
    backoff: float | None = None,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """最多重试 attempts 次（含首次）；鉴权与参数错误直接失败（§3.2）。"""

    settings = get_settings()
    total = attempts if attempts is not None else settings.provider_max_retries + 1
    delay = backoff if backoff is not None else settings.provider_backoff_seconds
    last: BaseException | None = None
    for index in range(max(1, total)):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 需区分可重试与不可重试
            last = exc
            if index >= total - 1 or not is_retryable(exc):
                raise
            if on_retry is not None:
                on_retry(index + 1, exc)
            time.sleep(delay * (2**index))
    raise last if last is not None else ProviderError("unknown provider failure")


def get_vision_provider() -> Any:
    settings = get_settings()
    if settings.multimodal_provider == "openai_compatible":
        from .openai_compatible import OpenAICompatibleVisionProvider

        return OpenAICompatibleVisionProvider()
    from .offline import OfflineVisionProvider

    return OfflineVisionProvider()


def get_asr_provider() -> Any:
    settings = get_settings()
    if settings.asr_provider == "http":
        from .asr_http import HttpAsrProvider

        return HttpAsrProvider()
    from .offline import NullAsrProvider

    return NullAsrProvider()
