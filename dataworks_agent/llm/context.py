"""LLM 上下文装配与数据边界守卫（Requirement 8）。

核心不变量（design Property 3）：发送给 LLM 的上下文永不包含生产数据行。

实现方式：上下文以带 `kind` 标签的结构化片段装配，ContextBuilder 只接受
schema / metadata / instruction / prompt 四类允许片段；RowDataGuard 在提交前
校验，若出现 data_row（或任何不在允许集内）的片段则拦截并抛
RowDataViolationError，由上层记入 Event_Log（Task 7 落地后接入）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

PartKind = Literal["schema", "metadata", "instruction", "prompt", "response", "data_row"]

# 允许出境的片段类型（不含 data_row）
_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"schema", "metadata", "instruction", "prompt", "response"}
)


class RowDataViolationError(RuntimeError):
    """检测到生产数据行内容试图发送给 LLM — 已拦截。"""


@dataclass
class ContextPart:
    """一段带类型标签的上下文片段。"""

    kind: PartKind
    content: str


@dataclass
class LLMContext:
    """结构化 LLM 上下文 — 由 ContextBuilder 装配、RowDataGuard 校验。"""

    parts: list[ContextPart] = field(default_factory=list)

    def to_messages(self) -> list[dict[str, str]]:
        """转成 OpenAI chat messages（instruction→system，最后一个 prompt→user）。"""
        messages: list[dict[str, str]] = []
        for i, p in enumerate(self.parts):
            if p.kind == "instruction":
                messages.append({"role": "system", "content": p.content})
            elif p.kind == "prompt":
                # 最后一个 prompt 作为 user 消息
                if i == len(self.parts) - 1:
                    messages.append({"role": "user", "content": p.content})
                else:
                    messages.append({"role": "system", "content": p.content})
            elif p.kind == "response":
                messages.append({"role": "assistant", "content": p.content})
            else:
                messages.append({"role": "user", "content": p.content})
        return messages


class ContextBuilder:
    """只装配 schema / metadata / instruction / prompt 片段（Requirement 8.1）。"""

    def __init__(self) -> None:
        self._parts: list[ContextPart] = []

    def add_schema(self, content: str) -> ContextBuilder:
        self._parts.append(ContextPart(kind="schema", content=content))
        return self

    def add_metadata(self, content: str) -> ContextBuilder:
        self._parts.append(ContextPart(kind="metadata", content=content))
        return self

    def add_instruction(self, content: str) -> ContextBuilder:
        self._parts.append(ContextPart(kind="instruction", content=content))
        return self

    def add_prompt(self, content: str) -> ContextBuilder:
        self._parts.append(ContextPart(kind="prompt", content=content))
        return self

    def add_response(self, content: str) -> ContextBuilder:
        """添加助手回复到上下文。"""
        self._parts.append(ContextPart(kind="response", content=content))
        return self

    def build(self) -> LLMContext:
        return LLMContext(parts=list(self._parts))


class RowDataGuard:
    """数据边界守卫 — 提交前拦截任何生产数据行片段（Requirement 8.2/8.3）。"""

    @staticmethod
    def check(context: LLMContext) -> None:
        """校验上下文只含允许片段；命中数据行则拦截。

        Raises:
            RowDataViolationError: 上下文含 data_row 或未知片段类型。
        """
        violations = [p.kind for p in context.parts if p.kind not in _ALLOWED_KINDS]
        if violations:
            logger.warning(
                "RowDataGuard 拦截：上下文含非法片段类型 %s（禁止将数据行发送给 LLM）",
                violations,
            )
            raise RowDataViolationError(f"上下文包含禁止发送给 LLM 的片段类型: {violations}")
