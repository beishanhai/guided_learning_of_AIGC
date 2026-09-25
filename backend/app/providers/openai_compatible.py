"""OpenAI 兼容的多模态接口适配器（密钥仅留在服务端配置）。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from ..config import get_settings
from ..errors import ProviderError
from .base import ShotContext, ShotFinding

SYSTEM_PROMPT = (
    "你是影视镜头拆解助手。只输出 JSON，不要输出解释文字。"
    "严格区分三类内容：观察事实（可从画面核对）、表达假设（可能的作用，不得当作作者陈述）、"
    "实践建议（可执行的替代方案）。缺少证据时把对应字段写成 unknown 并写入 unknowns 数组。"
    "禁止根据单帧断言运镜。"
)

SCHEMA_HINT = (
    "返回 JSON 对象，字段："
    '{"observation": string,'
    ' "shot_scale": "extreme_wide|wide|medium|medium_close|close_up|extreme_close_up|unknown",'
    ' "camera_motion": "static|pan|tilt|dolly|zoom|handheld|unknown",'
    ' "interpretation": string, "alternative": string,'
    ' "narrative_function": "establish|introduce_subject|develop|emphasize_emotion|transition|unknown",'
    ' "knowledge_tags": string[], "unknowns": string[], "confidence": number}'
)


class OpenAICompatibleVisionProvider:
    name = "openai_compatible"

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.model_id = settings.multimodal_model_id
        self.base_url = settings.multimodal_base_url.rstrip("/")
        self.api_key = settings.multimodal_api_key

    def analyze_shot(self, context: ShotContext, *, job_id: str) -> ShotFinding:
        if not self.api_key:
            raise ProviderError(
                "未配置多模态 API 密钥", retryable=False, code="provider_not_configured"
            )
        content: list[dict] = [{"type": "text", "text": self._prompt(context)}]
        for frame in context.frames:
            content.append({"type": "image_url", "image_url": {"url": _data_uri(frame)}})
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        try:
            response = httpx.post(
                self.base_url + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.settings.multimodal_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("多模态接口超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("多模态接口网络错误：" + type(exc).__name__, retryable=True) from exc

        if response.status_code in (401, 403):
            raise ProviderError("多模态接口鉴权失败", retryable=False, code="provider_auth")
        if response.status_code == 400:
            raise ProviderError("多模态接口参数错误", retryable=False, code="provider_bad_request")
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(
                "多模态接口返回 " + str(response.status_code),
                retryable=True,
                code="provider_retryable",
            )
        if response.status_code >= 400:
            raise ProviderError("多模态接口返回 " + str(response.status_code), retryable=False)

        body = response.json()
        parsed = _loads_json(_extract_text(body))
        request_id = response.headers.get("x-request-id") or str(body.get("id") or "")
        return ShotFinding(
            observation=str(parsed.get("observation") or "").strip(),
            shot_scale=str(parsed.get("shot_scale") or "unknown"),
            camera_motion=str(parsed.get("camera_motion") or "unknown"),
            interpretation=str(parsed.get("interpretation") or "").strip(),
            alternative=str(parsed.get("alternative") or "").strip(),
            narrative_function=str(parsed.get("narrative_function") or "unknown"),
            knowledge_tags=[str(t) for t in (parsed.get("knowledge_tags") or [])][:8],
            unknowns=[str(u) for u in (parsed.get("unknowns") or [])][:8],
            confidence=float(parsed.get("confidence") or 0.0),
            provider_request_id=request_id,
            raw={"response_id": body.get("id"), "usage": body.get("usage") or {}},
        )

    def _prompt(self, context: ShotContext) -> str:
        lines = [
            "学习目标：" + context.intent,
            "镜头编号：" + context.shot_ref,
            "时间区间："
            + format(context.start_ms / 1000.0, ".2f")
            + "s — "
            + format(context.end_ms / 1000.0, ".2f")
            + "s（时长 "
            + format(context.duration_ms / 1000.0, ".2f")
            + "s）",
            "代表帧顺序：" + ", ".join(context.frame_ids),
            "台词/字幕（可能为空）：" + (context.transcript or "无"),
            SCHEMA_HINT,
        ]
        if len(context.frames) < 2:
            lines.append("注意：本次只有 1 张代表帧，camera_motion 必须输出 unknown。")
        return "\n".join(lines)


def _data_uri(path: Path) -> str:
    data = Path(path).read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _extract_text(body: dict) -> str:
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("多模态接口返回结构异常", retryable=True) from exc


def _loads_json(text: str) -> dict:
    text = (text or "").strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text.strip(chr(96))
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "多模态接口返回不是合法 JSON", retryable=False, code="provider_bad_json"
        ) from exc
