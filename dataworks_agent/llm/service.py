"""LLM_Service — OpenAI 兼容薄封装（Requirement 7, 8）。

- base_url / model / api_key 全部来自配置，provider 无关；
- 不引入 langchain / llamaindex；
- 提交前经 RowDataGuard 校验数据边界；
- 缺 api_key 时抛 LLMKeyMissingError 快速失败。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from dataworks_agent.llm.context import LLMContext, RowDataGuard
from dataworks_agent.llm.router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 调用失败。"""


class LLMKeyMissingError(LLMError):
    """LLM_API_Key 缺失 — 阻止一切 LLM 调用（Requirement 7.5）。"""


@dataclass
class LLMResponse:
    """一次 LLM 调用的结构化结果（含成本信息，供 Cost_Monitor 消费）。"""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class LLMService:
    """OpenAI 兼容的 LLM 服务薄封装。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        router: LLMRouter,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._router = router
        self._client: AsyncOpenAI | None = None

    def _ensure_client(self) -> AsyncOpenAI:
        """惰性构造 AsyncOpenAI；缺 key 快速失败。"""
        if not self._api_key:
            raise LLMKeyMissingError(
                "缺少 LLM_API_KEY，无法调用 LLM。请在 .env 或环境变量中配置 LLM_API_KEY。"
            )
        if self._client is None:
            self._client = AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    async def complete(
        self,
        context: LLMContext,
        task_complexity: TaskComplexity = "normal",
    ) -> LLMResponse:
        """按复杂度路由模型并发起补全，提交前经数据边界校验。

        Raises:
            LLMKeyMissingError: api_key 缺失。
            RowDataViolationError: 上下文含生产数据行。
            LLMError: 调用失败。
        """
        # 数据边界守卫（Requirement 8）— 在任何网络调用之前
        RowDataGuard.check(context)

        client = self._ensure_client()
        model = self._router.route(task_complexity)
        messages = context.to_messages()

        started = time.monotonic()
        try:
            resp = await client.chat.completions.create(model=model, messages=messages)
        except Exception as e:
            raise LLMError(f"LLM 调用失败 (model={model}): {e}") from e
        latency_ms = int((time.monotonic() - started) * 1000)

        content = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            content=content,
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            latency_ms=latency_ms,
        )

    @classmethod
    def from_settings(cls, settings) -> LLMService:
        """从全局配置构建 LLM_Service。"""
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            router=LLMRouter.from_settings(settings),
        )
