"""Deterministic-first resolver for contextual Agent turns."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionOption,
    PendingInteraction,
)


class DialogueAction(StrEnum):
    """Normalized action for one user turn."""

    NEW_GOAL = "new_goal"
    ANSWER = "answer"
    CONTINUE = "continue"
    EXPLAIN = "explain"
    MODIFY = "modify"
    REFER = "refer"
    CANCEL = "cancel"
    GREETING = "greeting"
    RESET = "reset"
    CLARIFY = "clarify"


class ResolvedTurn(BaseModel):
    """Context-enriched representation of one user turn."""

    dialogue_action: DialogueAction
    rewritten_message: str
    context_updates: dict[str, Any] = Field(default_factory=dict)
    resolved_references: list[str] = Field(default_factory=list)
    interaction_answer: InteractionAnswer | None = None
    resolver: str = "deterministic"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    consume_interaction: bool = False


class SemanticTurnFallback(Protocol):
    """Optional semantic classifier for unresolved substantive input."""

    async def classify(self, message: str, context: dict[str, Any]) -> ResolvedTurn | None:
        raise NotImplementedError


class LLMDialogueFallback:
    """Adapter from the existing LLM intent classifier to dialogue actions."""

    def __init__(self, classifier: Any | None = None) -> None:
        self._classifier = classifier

    async def classify(self, message: str, context: dict[str, Any]) -> ResolvedTurn | None:
        if self._classifier is None:
            try:
                from dataworks_agent.agent.llm_intent_classifier import (
                    LLMIntentClassifier,
                )

                self._classifier = LLMIntentClassifier()
            except Exception:
                return None

        compact = {
            "objective": context.get("objective"),
            "action": context.get("action"),
            "selected_resources": context.get("selected_resources"),
        }
        try:
            result = await self._classifier.classify(
                f"当前会话上下文：{json.dumps(compact, ensure_ascii=False)}\n用户输入：{message}"
            )
            params = getattr(result, "params", None)
            if not isinstance(params, dict):
                return None
            mapping = {
                "greeting": DialogueAction.GREETING,
                "clarification": DialogueAction.CLARIFY,
                "ask_data": DialogueAction.NEW_GOAL,
                "modeling": DialogueAction.NEW_GOAL,
                "diagnosis": DialogueAction.NEW_GOAL,
            }
            action = mapping.get(getattr(result, "action", None))
            if action is None:
                return None
            return ResolvedTurn(
                dialogue_action=action,
                rewritten_message=message,
                context_updates={"params": params},
                resolver="llm",
                confidence=float(getattr(result, "confidence", 0.0)),
            )
        except Exception:
            return None


class ContextResolver:
    """Resolve short contextual turns before the existing NLU pipeline."""

    _RESET_RE = re.compile(r"^(?:重新开始|重置(?:会话|对话)?|新会话|清空上下文)[。！!？?]?$")
    _CANCEL_RE = re.compile(r"^(?:(?:取消|停止|终止)(?:这个|当前)?任务|不做了|算了)[。！!？?]?$")
    _GREETING_RE = re.compile(r"^(?:你好|您好|嗨|哈喽|hello|hi)[。！!？?~～]*$", re.IGNORECASE)
    _EXPLAIN_RE = re.compile(
        r"^(?:什么意思|请?解释一下|没看懂|为什么(?:这么|这样)?(?:选|说|做)?)[。！!？?]?$"
    )
    _CONTINUE_RE = re.compile(
        r"^(?:(?:不要取消(?:这个|当前)?任务[，,]\s*)?继续(?:执行)?|下一步|"
        r"接着(?:说|做)?|往下(?:说|做)?)[。！!？?]?$"
    )
    _ORDINALS = {
        "第一个": 0,
        "第1个": 0,
        "第二个": 1,
        "第2个": 1,
        "第三个": 2,
        "第3个": 2,
    }
    _LAYER_RE = re.compile(
        r"(?:(?:换成|改成|改为|只看|选择)\s*)?(ODS|DWD|DIM|DWS|ADS)",
        re.IGNORECASE,
    )
    _DATE_RE = re.compile(r"最近\s*(\d+)\s*天")
    _TABLE_REFERENCE_RE = re.compile(r"(?:刚才|之前)?(?:那张表|这张表)|该表")
    _NODE_REFERENCE_RE = re.compile(r"(?:刚才|之前)?(?:那个节点|这个节点)|该节点")
    _TASK_REFERENCE_RE = re.compile(r"(?:刚才|之前)?(?:那个任务|这个任务)|该任务")
    _GENERIC_REFERENCE_RE = re.compile(r"(?:刚才|之前)(?:那个|这个)|用它")
    _TASK_RE = re.compile(
        r"(?:查询|查找|查一下|搜索|建模|创建|新建|修改|更新|删除|发布|部署|"
        r"血缘|字段|数据表|表结构|表(?:$|[\s，,。！!？?])|节点|数据源|调度|排查|诊断|SQL)",
        re.IGNORECASE,
    )

    def __init__(self, fallback: SemanticTurnFallback | None = None) -> None:
        self._fallback = fallback

    async def resolve(self, message: str, context: dict[str, Any]) -> ResolvedTurn:
        """Resolve a message in deterministic priority order."""

        text = message.strip()
        pending = self._pending_interaction(context)
        option_result = self._resolve_option(
            text,
            pending,
            context_state_version=context.get("state_version"),
        )
        if option_result is not None:
            return option_result
        if self._looks_like_ordinal(text):
            return self._turn(DialogueAction.CLARIFY, text)

        if self._RESET_RE.fullmatch(text):
            return self._turn(DialogueAction.RESET, text, consume_interaction=True)
        if self._CANCEL_RE.fullmatch(text):
            return self._turn(DialogueAction.CANCEL, text, consume_interaction=True)
        if self._GREETING_RE.fullmatch(text):
            return self._turn(DialogueAction.GREETING, text)
        if self._EXPLAIN_RE.fullmatch(text):
            return self._turn(DialogueAction.EXPLAIN, text)
        if self._CONTINUE_RE.fullmatch(text):
            return self._turn(DialogueAction.CONTINUE, text)

        modification = self._resolve_modification(text)
        if modification is not None:
            return modification

        reference = self._resolve_reference(text, context)
        if reference is not None:
            return reference

        if self._TASK_RE.search(text):
            return self._turn(DialogueAction.NEW_GOAL, text)

        if self._fallback is not None and len(text) >= 4:
            try:
                fallback_result = await self._fallback.classify(text, context)
            except Exception:
                fallback_result = None
            if fallback_result is not None and fallback_result.confidence >= 0.7:
                return fallback_result

        return self._turn(DialogueAction.CLARIFY, text)

    @staticmethod
    def _turn(
        action: DialogueAction,
        message: str,
        *,
        context_updates: dict[str, Any] | None = None,
        resolved_references: list[str] | None = None,
        consume_interaction: bool = False,
    ) -> ResolvedTurn:
        return ResolvedTurn(
            dialogue_action=action,
            rewritten_message=message,
            context_updates=context_updates or {},
            resolved_references=resolved_references or [],
            consume_interaction=consume_interaction,
        )

    @staticmethod
    def _pending_interaction(context: dict[str, Any]) -> PendingInteraction | None:
        raw = context.get("pending_interaction")
        if not raw:
            return None
        try:
            pending = PendingInteraction.model_validate(raw)
        except (TypeError, ValidationError):
            return None
        return pending if pending.status == "pending" else None

    def _resolve_option(
        self,
        text: str,
        pending: PendingInteraction | None,
        *,
        context_state_version: Any,
    ) -> ResolvedTurn | None:
        if pending is None:
            return None

        option_index = self._ordinal_index(text, len(pending.options))
        normalized = self._normalize_option_text(text)
        exact_matches = self._matching_options(normalized, pending, exact=True)
        substring_matches = (
            [] if exact_matches else self._matching_options(normalized, pending, exact=False)
        )
        is_option_input = option_index is not None or bool(exact_matches or substring_matches)
        if is_option_input and context_state_version != pending.state_version:
            return self._turn(DialogueAction.CLARIFY, text)

        if option_index is not None:
            if 0 <= option_index < len(pending.options):
                return self._option_answer(text, pending, pending.options[option_index])
            return self._turn(DialogueAction.CLARIFY, text)

        matches = exact_matches or substring_matches
        if len(matches) == 1:
            return self._option_answer(text, pending, matches[0])
        if len(matches) > 1:
            return self._turn(DialogueAction.CLARIFY, text)
        return None

    @classmethod
    def _matching_options(
        cls,
        normalized_message: str,
        pending: PendingInteraction,
        *,
        exact: bool,
    ) -> list[InteractionOption]:
        matches = []
        for option in pending.options:
            values = {
                cls._normalize_option_text(option.label),
                cls._normalize_option_text(str(option.value or "")),
            }
            values.discard("")
            matched = (
                normalized_message in values
                if exact
                else any(value in normalized_message for value in values)
            )
            if matched:
                matches.append(option)
        return matches

    @staticmethod
    def _option_answer(
        text: str, pending: PendingInteraction, option: InteractionOption
    ) -> ResolvedTurn:
        return ResolvedTurn(
            dialogue_action=DialogueAction.ANSWER,
            rewritten_message=text,
            context_updates=dict(option.payload),
            interaction_answer=InteractionAnswer(
                interaction_id=pending.interaction_id,
                option_id=option.id,
                state_version=pending.state_version,
            ),
            consume_interaction=True,
        )

    @classmethod
    def _ordinal_index(cls, text: str, option_count: int) -> int | None:
        compact = re.sub(r"[\s，,。！!？?]", "", text)
        if "最后一个" in compact:
            return option_count - 1 if option_count else None
        for ordinal, index in cls._ORDINALS.items():
            if ordinal in compact:
                return index
        return None

    @classmethod
    def _looks_like_ordinal(cls, text: str) -> bool:
        compact = re.sub(r"[\s，,。！!？?]", "", text)
        return "最后一个" in compact or any(ordinal in compact for ordinal in cls._ORDINALS)

    @staticmethod
    def _normalize_option_text(value: str) -> str:
        return re.sub(r"[\s，,。！!？?]", "", value).lower()

    def _resolve_modification(self, text: str) -> ResolvedTurn | None:
        layer_match = self._LAYER_RE.search(text)
        if layer_match and (
            layer_match.group(0).strip().upper() == text.strip().upper()
            or re.search(r"(?:换成|改成|改为|只看|选择)", text)
        ):
            layer = layer_match.group(1).lower()
            return self._turn(
                DialogueAction.MODIFY,
                text,
                context_updates={"params": {"layer": layer}},
            )

        if re.search(r"(?:不要执行|不执行|只生成方案|仅生成方案)", text):
            return self._turn(
                DialogueAction.MODIFY,
                text,
                context_updates={"params": {"execution_mode": "plan_only"}},
            )

        date_match = self._DATE_RE.search(text)
        if date_match:
            days = int(date_match.group(1))
            return self._turn(
                DialogueAction.MODIFY,
                text,
                context_updates={"params": {"date_range": f"last_{days}_days"}},
            )

        return None

    def _resolve_reference(self, text: str, context: dict[str, Any]) -> ResolvedTurn | None:
        resources = context.get("selected_resources")
        if not isinstance(resources, dict) or not resources:
            return None

        resource_type = None
        if self._TABLE_REFERENCE_RE.search(text):
            resource_type = "table"
        elif self._NODE_REFERENCE_RE.search(text):
            resource_type = "node"
        elif self._TASK_REFERENCE_RE.search(text):
            resource_type = "task"
        elif self._GENERIC_REFERENCE_RE.search(text) and len(resources) == 1:
            resource_type = next(iter(resources))
        if resource_type is None:
            return None

        resource = resources.get(resource_type)
        if not isinstance(resource, str) or not resource:
            return None
        selected = {resource_type: resource}
        return self._turn(
            DialogueAction.REFER,
            f"{text}\n已解析资源：{resource}",
            context_updates={"selected_resources": selected},
            resolved_references=[resource],
        )
