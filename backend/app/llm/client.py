"""薄的 LLM 网关，只负责无状态的 JSON 调用。

为什么不复用 SimpleAgent 的对话历史？
    - Day 3 的规划是无状态的：一次请求 -> 一个 prompt -> 一份 JSON 计划。
    - 编排归 DAG 管，LLM 不该自己留跨请求的记忆。
    - 这层还顺手记下 usage / latency，供 Trace 用。
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

# 配置缺失
class LLMConfigError(RuntimeError):
    """LLM 的 key 或模型没配好时抛这个，API 层会映射成 503。"""



class LLMResult(BaseModel):
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = ""

# 仅支持JSON的LLM网关 只能做静态类型标注
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
    """兼容 OpenAI 协议的客户端（OpenAI / DeepSeek / Qwen / 本地部署都能接）。"""

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
    # 组装请求 发请求+降级处理
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
            # 有些兼容 OpenAI 的服务不认 response_format，去掉再发一次，
            # 改由 prompt 和后面的解析来保证 JSON。
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

# 根据环境变量创建LLM客户端，工厂
def create_llm_client() -> OpenAICompatibleClient:
    """按 LLM_* / OPENAI_* 环境变量造一个客户端。"""
    # 函数内 import 是为了避开循环依赖；调 get_settings() 只是为了触发 .env 加载。
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
