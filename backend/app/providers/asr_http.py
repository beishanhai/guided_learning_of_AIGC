"""HTTP 语音转写适配器（返回带时间戳的分段）。"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..config import get_settings
from ..errors import ProviderError
from .base import TranscriptResult, TranscriptSegment


class HttpAsrProvider:
    name = "http"

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.model_id = settings.asr_model_id or "http-asr"
        self.base_url = settings.asr_base_url.rstrip("/")
        self.api_key = settings.asr_api_key

    def transcribe(self, audio_path: Path, *, duration_ms: int, job_id: str) -> TranscriptResult:
        if not self.base_url:
            raise ProviderError(
                "未配置 ASR 服务地址", retryable=False, code="provider_not_configured"
            )
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        try:
            with open(audio_path, "rb") as fh:
                response = httpx.post(
                    self.base_url + "/transcribe",
                    files={"file": ("audio.wav", fh, "audio/wav")},
                    data={"model": self.model_id, "response_format": "verbose_json"},
                    headers=headers,
                    timeout=self.settings.asr_timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("ASR 超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("ASR 网络错误", retryable=True) from exc

        if response.status_code in (401, 403):
            raise ProviderError("ASR 鉴权失败", retryable=False, code="provider_auth")
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError("ASR 返回 " + str(response.status_code), retryable=True)
        if response.status_code >= 400:
            raise ProviderError("ASR 返回 " + str(response.status_code), retryable=False)

        body = response.json()
        segments: list[TranscriptSegment] = []
        for item in body.get("segments") or []:
            try:
                start = int(round(float(item.get("start", 0)) * 1000))
                end = int(round(float(item.get("end", 0)) * 1000))
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    start_ms=max(0, start), end_ms=min(duration_ms, max(start, end)), text=text
                )
            )
        return TranscriptResult(
            segments=segments,
            language=str(body.get("language") or ""),
            provider=self.name,
            provider_request_id=str(body.get("id") or ""),
            note="" if segments else "ASR 未返回可用分段",
        )
