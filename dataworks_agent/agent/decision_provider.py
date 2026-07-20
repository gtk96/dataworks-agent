"""Deterministic-first decisions for the bounded Agent run loop."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.response_policy import ResponsePolicy
from dataworks_agent.agent.run_models import AgentRunRequest


@dataclass(frozen=True)
class RespondDecision:
    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ToolDecision:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarifyDecision:
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = "ambiguous_context"


@dataclass(frozen=True)
class DelegateDecision:
    """Hand an unsupported goal to the existing guarded workflow path."""


Decision = RespondDecision | ToolDecision | ClarifyDecision | DelegateDecision


class DecisionProvider:
    """Choose deterministic actions before consulting an optional LLM."""

    _GREETING_RE = re.compile(r"^(?:你好|您好|嗨|哈喽|hello|hi)[。！!？?~～]*$", re.I)
    _EXPLAIN_RE = re.compile(r"^(?:什么意思|请?解释一下|没看懂)[。！!？?]*$")
    _FIND_TABLE_RE = re.compile(
        r"(?:查找|搜索|搜|找|查一下|查)(?:[^。！？!?]{0,40})(?:数据表|表)|"
        r"(?:数据表|表)(?:[^。！？!?]{0,20})(?:查找|搜索|搜|找)",
        re.I,
    )
    _PHYSICAL_TABLE_RE = re.compile(
        r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*)"
    )

    def __init__(
        self, llm: Any | None = None, response_policy: ResponsePolicy | None = None
    ) -> None:
        self.llm = llm
        self._responses = response_policy or ResponsePolicy()

    @classmethod
    def handles_message(cls, message: str) -> bool:
        """Return whether a turn has a deterministic bounded-runtime route."""

        text = message.strip()
        return bool(
            cls._GREETING_RE.fullmatch(text)
            or cls._EXPLAIN_RE.fullmatch(text)
            or cls._FIND_TABLE_RE.search(text)
            or cls._PHYSICAL_TABLE_RE.search(text)
        )

    @classmethod
    def is_table_discovery(cls, message: str) -> bool:
        return bool(cls._FIND_TABLE_RE.search(message.strip()))

    async def decide(
        self,
        request: AgentRunRequest,
        state: dict[str, Any],
        *,
        resolved_answer: dict[str, Any] | None = None,
        interaction_purpose: str = "",
    ) -> Decision:
        text = request.message.strip()
        if resolved_answer is not None:
            return self._from_answer(resolved_answer, interaction_purpose)

        if self._GREETING_RE.fullmatch(text):
            data = self._responses.greeting(
                state,
                state_version=int(state.get("state_version") or 0) + 1,
            )
            message = (
                "你好，我们可以继续当前任务。"
                if state.get("objective")
                else "你好！我可以协助你查表、问数、建模和排障。"
            )
            return RespondDecision(message, data={"agent_mode": "greeting", **data})

        if self._EXPLAIN_RE.fullmatch(text):
            message, data = self._responses.explain(state)
            return RespondDecision(message, data={"agent_mode": "explain", **data})

        if self._FIND_TABLE_RE.search(text):
            return ToolDecision("find_table", {"keyword": text})

        physical = self._PHYSICAL_TABLE_RE.search(text)
        if physical:
            return RespondDecision(
                f"已选择数据表 {physical.group(1)}。请选择下一步。",
                data={
                    "agent_mode": "table_selected",
                    "selected_resources": {"table": physical.group(1)},
                },
            )

        if self.llm is not None:
            try:
                decision = await self.llm(
                    text,
                    {
                        "objective": state.get("objective"),
                        "action": state.get("action"),
                        "selected_resources": state.get("selected_resources"),
                    },
                )
            except Exception:
                decision = None
            if isinstance(decision, (RespondDecision, ToolDecision, ClarifyDecision)):
                return decision

        return DelegateDecision()

    @staticmethod
    def _from_answer(answer: dict[str, Any], purpose: str) -> Decision:
        params = dict(answer.get("params") or {})
        custom_text = str(answer.get("custom_text") or "").strip()
        action = str(answer.get("action") or params.get("tool_name") or "").strip()
        table_name = str(params.get("table_name") or "").strip()
        if table_name and purpose == "select_table":
            return RespondDecision(
                f"已选择数据表 {table_name}。请选择下一步。",
                data={
                    "agent_mode": "table_selected",
                    "selected_resources": {"table": table_name},
                },
            )
        if action == "inspect_table":
            return ToolDecision("inspect_table", {"table_name": table_name})
        if custom_text and purpose == "select_table":
            return ToolDecision("find_table", {"keyword": custom_text})
        if action == "find_table" or purpose in {"refine_table_search", "select_layer"}:
            return ToolDecision(
                "find_table",
                {
                    "keyword": custom_text or str(params.get("keyword") or ""),
                    "layer": str(params.get("layer") or ""),
                },
            )
        if table_name:
            return RespondDecision(
                f"已选择数据表 {table_name}。请选择下一步。",
                data={
                    "agent_mode": "table_selected",
                    "selected_resources": {"table": table_name},
                },
            )
        if custom_text and purpose == "choose_entry":
            return DelegateDecision()
        return ClarifyDecision("我没有识别出这次选择，请根据当前选项重试或补充说明。")
