"""MiniMax 对话接口客户端。

走 MiniMax 官方的 ``POST {base_url}/text/chatcompletion_v2``（Bearer 鉴权）。
两个必须处理的细节：

1. MiniMax 出错时**仍可能返回 HTTP 200**，真正的错误码在 ``base_resp.status_code``
   里，所以不能只看 HTTP 状态码。
2. 推理模型会返回 ``reasoning_content``；本题不采集模型私有思维链，只记录
   它是否存在及其长度，正文只用 ``content``。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.minimax.chat/v1"
DEFAULT_MODEL = "MiniMax-M1"
CHAT_PATH = "/text/chatcompletion_v2"

#: 可重试的业务错误码：限流与瞬时不可用。
#: 1039 = rate limit exceeded(TPM)，1002 = 触发限流，1042/1039 变体，1013 = 服务内部错误
RETRYABLE_CODES = {1002, 1013, 1039, 1042}


class MiniMaxError(RuntimeError):
    """调用 MiniMax 失败（网络、鉴权或业务错误码）。"""


@dataclass
class ChatResult:
    content: str
    model: str
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    reasoning_present: bool = False
    reasoning_chars: int = 0
    raw: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1


class MiniMaxClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        timeout: float = 600.0,
        max_tokens: int | None = 24_000,
        retries: int = 4,
        backoff_seconds: tuple[int, ...] = (20, 45, 90, 120, 180),
    ) -> None:
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        self.base_url = (base_url or os.environ.get("MINIMAX_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("MINIMAX_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> ChatResult:
        if not self.api_key:
            raise MiniMaxError(
                "缺少 MINIMAX_API_KEY。请在 minimax/.env 中配置后重新运行。"
            )

        effective_max_tokens = max_tokens or self.max_tokens
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if effective_max_tokens:
            payload["max_tokens"] = effective_max_tokens

        url = f"{self.base_url}{CHAT_PATH}"
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 2):
            started = time.perf_counter()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "X-Request-Id": uuid.uuid4().hex,
                        },
                    )
            except httpx.HTTPError as exc:
                last_error = MiniMaxError(f"网络错误：{type(exc).__name__}: {exc}")
                self._sleep(attempt)
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)

            if response.status_code == 401 or response.status_code == 403:
                raise MiniMaxError(
                    f"鉴权失败（HTTP {response.status_code}）：请检查 MINIMAX_API_KEY 是否有效"
                )

            try:
                body = response.json()
            except json.JSONDecodeError as exc:
                raise MiniMaxError(
                    f"响应不是 JSON（HTTP {response.status_code}）：{response.text[:400]}"
                ) from exc

            base_resp = body.get("base_resp") or {}
            status_code = int(base_resp.get("status_code", 0) or 0)
            if response.status_code >= 400 or status_code != 0:
                message = base_resp.get("status_msg") or body.get("message") or response.text[:400]
                last_error = MiniMaxError(
                    f"MiniMax 业务错误（HTTP {response.status_code} / code {status_code}）：{message}"
                )
                # TPM 限流是滑动窗口，需要等一整分钟才能恢复，用长退避
                if (
                    response.status_code in (429, 500, 502, 503, 504)
                    or status_code in RETRYABLE_CODES
                ):
                    self._sleep(attempt)
                    continue
                raise last_error

            choices = body.get("choices") or []
            if not choices:
                last_error = MiniMaxError(f"响应缺少 choices：{response.text[:400]}")
                self._sleep(attempt)
                continue

            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""

            if not content.strip():
                last_error = MiniMaxError("模型返回了空 content")
                self._sleep(attempt)
                continue

            return ChatResult(
                content=content,
                model=str(body.get("model") or self.model),
                latency_ms=latency_ms,
                usage=body.get("usage") or {},
                request_id=body.get("id"),
                reasoning_present=bool(reasoning),
                reasoning_chars=len(reasoning),
                raw=body,
                attempts=attempt,
            )

        raise last_error or MiniMaxError("未知的 MiniMax 调用失败")

    def _sleep(self, attempt: int) -> None:
        index = min(attempt - 1, len(self.backoff_seconds) - 1)
        delay = self.backoff_seconds[index]
        print(f"  [retry] 第 {attempt} 次失败，{delay}s 后重试", flush=True)
        time.sleep(delay)
