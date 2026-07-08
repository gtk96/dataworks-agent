"""LLM_Service 单元测试 — 路由、缺 key、数据边界、complete（Requirement 7, 8）。"""

from __future__ import annotations

from typing import ClassVar

import pytest

from dataworks_agent.llm import (
    ContextBuilder,
    ContextPart,
    LLMContext,
    LLMKeyMissingError,
    LLMRouter,
    LLMService,
    RowDataGuard,
    RowDataViolationError,
)
from dataworks_agent.llm import service as svc_mod


# ── LLMRouter ──
class TestRouter:
    def test_routes_to_tier_when_configured(self):
        router = LLMRouter("default-m", {"light": "l-m", "complex": "c-m"})
        assert router.route("light") == "l-m"
        assert router.route("complex") == "c-m"

    def test_falls_back_to_default_for_missing_tier(self):
        router = LLMRouter("default-m", {"light": "l-m"})
        assert router.route("normal") == "default-m"
        assert router.route("complex") == "default-m"

    def test_single_model_routes_all(self):
        router = LLMRouter("only-m", {})
        assert router.route("light") == "only-m"
        assert router.route("normal") == "only-m"
        assert router.route("complex") == "only-m"

    def test_empty_tier_values_ignored(self):
        router = LLMRouter("default-m", {"light": "", "normal": ""})
        assert router.route("light") == "default-m"

    def test_empty_default_rejected(self):
        with pytest.raises(ValueError):
            LLMRouter("", {})


# ── RowDataGuard / ContextBuilder ──
class TestDataBoundary:
    def test_builder_assembles_allowed_kinds(self):
        ctx = (
            ContextBuilder()
            .add_instruction("你是建模助手")
            .add_schema("CREATE TABLE t (id bigint)")
            .add_metadata("owner=team_a")
            .build()
        )
        RowDataGuard.check(ctx)  # 不抛
        assert len(ctx.parts) == 3

    def test_guard_blocks_data_row(self):
        ctx = LLMContext(parts=[ContextPart(kind="data_row", content="1,alice,900")])
        with pytest.raises(RowDataViolationError):
            RowDataGuard.check(ctx)

    def test_guard_blocks_mixed_with_data_row(self):
        ctx = LLMContext(
            parts=[
                ContextPart(kind="schema", content="id bigint"),
                ContextPart(kind="data_row", content="1,alice"),
            ]
        )
        with pytest.raises(RowDataViolationError):
            RowDataGuard.check(ctx)

    def test_to_messages_role_mapping(self):
        ctx = ContextBuilder().add_instruction("sys").add_schema("user-schema").build()
        msgs = ctx.to_messages()
        assert msgs[0] == {"role": "system", "content": "sys"}
        assert msgs[1] == {"role": "user", "content": "user-schema"}


# ── LLMService ──
class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self):
        self.prompt_tokens = 10
        self.completion_tokens = 5
        self.total_tokens = 15


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, holder):
        self._holder = holder

    async def create(self, model, messages):
        self._holder["model"] = model
        self._holder["messages"] = messages
        return _FakeResponse("生成的内容")


class _FakeChat:
    def __init__(self, holder):
        self.completions = _FakeCompletions(holder)


class _FakeAsyncOpenAI:
    last_init: ClassVar[dict] = {}

    def __init__(self, base_url, api_key):
        type(self).last_init = {"base_url": base_url, "api_key": api_key}
        _FakeAsyncOpenAI.last_init = {"base_url": base_url, "api_key": api_key}
        self.chat = _FakeChat(_holder)


_holder: dict = {}


@pytest.fixture
def patch_openai(monkeypatch):
    _holder.clear()
    monkeypatch.setattr(svc_mod, "AsyncOpenAI", _FakeAsyncOpenAI)
    return _holder


def _service(api_key="sk-test") -> LLMService:
    return LLMService(
        base_url="https://opencode.ai/zen/v1",
        api_key=api_key,
        router=LLMRouter("default-m", {"complex": "c-m"}),
    )


class TestComplete:
    async def test_missing_key_fast_fail(self, patch_openai):
        service = _service(api_key="")
        ctx = ContextBuilder().add_prompt("hi").build()
        with pytest.raises(LLMKeyMissingError):
            await service.complete(ctx)

    async def test_complete_success_and_usage(self, patch_openai):
        service = _service()
        ctx = ContextBuilder().add_schema("id bigint").build()
        resp = await service.complete(ctx, task_complexity="complex")
        assert resp.content == "生成的内容"
        assert resp.model == "c-m"
        assert resp.prompt_tokens == 10
        assert resp.total_tokens == 15
        assert resp.latency_ms >= 0
        assert patch_openai["model"] == "c-m"

    async def test_uses_akssk_free_base_url(self, patch_openai):
        service = _service()
        ctx = ContextBuilder().add_schema("x").build()
        await service.complete(ctx)
        assert _FakeAsyncOpenAI.last_init["base_url"] == "https://opencode.ai/zen/v1"
        assert _FakeAsyncOpenAI.last_init["api_key"] == "sk-test"

    async def test_data_boundary_blocks_before_network(self, patch_openai):
        service = _service()
        ctx = LLMContext(parts=[ContextPart(kind="data_row", content="1,alice")])
        with pytest.raises(RowDataViolationError):
            await service.complete(ctx)
        # 未发生网络调用
        assert "model" not in patch_openai
