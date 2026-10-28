"""MiniMax (OpenAI-compatible) client used for the actual code modification."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .errors import MiniMaxError


@dataclass
class MiniMaxResult:
    content: str
    model: str
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    finish_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "request_id": self.request_id,
            "finish_reason": self.finish_reason,
            "content_chars": len(self.content),
        }


class MiniMaxClient:
    """Thin client for ``POST {base_url}/chat/completions``."""

    def __init__(self, settings: Settings, *, timeout_seconds: float = 300.0) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.settings.minimax_api_key)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_completion_tokens: int = 24_000,
        reasoning_effort: str | None = None,
    ) -> MiniMaxResult:
        if not self.configured:
            raise MiniMaxError(
                "未配置 MINIMAX_API_KEY。请在 minimax/.env 中设置后重试；"
                "上下文构建与数据库检索不需要该密钥。"
            )
        payload: dict[str, Any] = {
            "model": self.settings.minimax_model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "reasoning_effort": reasoning_effort or self.settings.minimax_reasoning_effort,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.minimax_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.settings.minimax_base_url}/chat/completions"
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                response.raise_for_status()
                data = response.json()
                return self._parse(data, int((time.perf_counter() - started) * 1000))
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:800]
                last_error = MiniMaxError(
                    f"MiniMax 请求失败: HTTP {exc.response.status_code} {body}"
                )
                if exc.response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_error from exc
            except (httpx.HTTPError, ValueError) as exc:
                last_error = MiniMaxError(f"MiniMax 请求失败: {exc}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_error from exc
        raise last_error or MiniMaxError("MiniMax 请求失败")

    def _parse(self, data: dict[str, Any], latency_ms: int) -> MiniMaxResult:
        base_resp = data.get("base_resp") or {}
        status_code = base_resp.get("status_code", 0)
        if status_code not in (0, None):
            raise MiniMaxError(
                f"MiniMax 返回错误 {status_code}: {base_resp.get('status_msg', '')}"
            )
        choices = data.get("choices") or []
        if not choices:
            raise MiniMaxError(f"MiniMax 响应缺少 choices: {json.dumps(data, ensure_ascii=False)[:500]}")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not isinstance(content, str) or not content.strip():
            raise MiniMaxError("MiniMax 响应内容为空（可能被 max_completion_tokens 截断）")
        return MiniMaxResult(
            content=content,
            model=str(data.get("model") or self.settings.minimax_model),
            latency_ms=latency_ms,
            usage=data.get("usage") or {},
            request_id=str(data.get("id") or ""),
            finish_reason=str(choices[0].get("finish_reason") or ""),
        )
