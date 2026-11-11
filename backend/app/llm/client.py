"""Thin LLM gateway for stateless JSON calls.

Why not reuse SimpleAgent's history here?
    - Day 3 planning is stateless: one request -> one prompt -> one JSON plan.
    - The DAG owns orchestration; the LLM should not keep cross-request memory.
    - This wrapper also captures usage/latency for Trace.
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from openai import BadRequestError, OpenAI
from pydantic import BaseModel


class LLMConfigError(RuntimeError):
    """Raised when LLM credentials/model are not configured."""


class LLMResult(BaseModel):
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = ""


class LLMClient(Protocol):
    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: float = 60.0,
    ) -> LLMResult:
        ...


class OpenAICompatibleClient:
    """OpenAI-compatible client (OpenAI / DeepSeek / Qwen / local...)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: float = 60.0,
    ) -> LLMResult:
        request_model = model or self.model
        kwargs: dict[str, Any] = {
            "model": request_model,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
            "response_format": {"type": "json_object"},
        }

        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except BadRequestError:
            # Some OpenAI-compatible providers reject response_format; retry
            # without it and let the prompt/parser enforce JSON.
            kwargs.pop("response_format", None)
            response = self._client.chat.completions.create(**kwargs)
        latency_ms = (time.perf_counter() - started) * 1000

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        content = choice.message.content or ""
        return LLMResult(
            content=content,
            model=request_model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            latency_ms=round(latency_ms, 2),
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        )


def create_llm_client() -> OpenAICompatibleClient:
    """Build a client from LLM_* / OPENAI_* environment variables."""
    # Importing config triggers the project's .env / .env.local loading.
    from ..config import get_settings

    get_settings()

    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1"
    model = os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL")
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if not api_key:
        raise LLMConfigError("LLM_API_KEY / OPENAI_API_KEY 未配置")
    if not model:
        raise LLMConfigError("LLM_MODEL_ID / OPENAI_MODEL 未配置")

    return OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )
