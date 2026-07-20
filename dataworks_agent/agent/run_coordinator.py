"""Bounded observe/decide/act coordinator for page conversations."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from dataworks_agent.agent.context_resolver import ContextResolver, DialogueAction
from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.decision_provider import (
    ClarifyDecision,
    DecisionProvider,
    DelegateDecision,
    RespondDecision,
    ToolDecision,
)
from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionExpiredError,
    InteractionOption,
    PendingInteraction,
)
from dataworks_agent.agent.response_policy import ResponsePolicy
from dataworks_agent.agent.run_models import (
    AgentRunRequest,
    AgentRunResponse,
    RunEvent,
    new_run_id,
)
from dataworks_agent.agent.tools.base import ToolContext, ToolResult
from dataworks_agent.agent.tools.registry import ToolRegistry

EventSink = Callable[[RunEvent], Awaitable[None] | None]
LegacyDelegate = Callable[[AgentRunRequest], Awaitable[AgentRunResponse]]

logger = logging.getLogger(__name__)


class AgentRunCoordinator:
    """Run at most six decisions and persist one authoritative response."""

    def __init__(
        self,
        *,
        conversation_graph: ConversationGraph | None = None,
        tools: ToolRegistry | None = None,
        decisions: DecisionProvider | None = None,
        legacy_delegate: LegacyDelegate | None = None,
        max_decisions: int = 6,
    ) -> None:
        if max_decisions < 1:
            raise ValueError("max_decisions must be positive")
        self.conversation_graph = conversation_graph or ConversationGraph()
        self.tools = tools or ToolRegistry([])
        self.decisions = decisions or DecisionProvider()
        self._legacy_delegate = legacy_delegate
        self._responses = ResponsePolicy()
        self._max_decisions = max_decisions

    async def run(
        self,
        request: AgentRunRequest,
        *,
        emit: EventSink | None = None,
    ) -> AgentRunResponse:
        run_id = new_run_id()
        sequence = 0

        async def publish(event_type: str, **data: Any) -> None:
            nonlocal sequence
            sequence += 1
            if emit is None:
                return
            outcome = emit(RunEvent(event_type, run_id, sequence, data))
            if inspect.isawaitable(outcome):
                await outcome

        await publish("run.started", conversation_id=request.conversation_id)
        state = await self.conversation_graph.context(request.conversation_id)
        if (
            request.interaction_answer is None
            and self.decisions.is_table_discovery(request.message)
            and state.get("objective")
            and request.message.strip() != str(state.get("objective") or "").strip()
        ):
            state = await self.conversation_graph.start_goal(
                request.conversation_id, request.message.strip()
            )
        pending = dict(state.get("pending_interaction") or {})
        resolved_answer: dict[str, Any] | None = None
        answer_payload = request.interaction_answer
        if answer_payload is None and pending:
            resolved_turn = await ContextResolver().resolve(request.message, state)
            answer_payload = resolved_turn.interaction_answer
            if (
                answer_payload is None
                and pending.get("allow_custom_input")
                and pending.get("purpose")
                in {"refine_table_search", "select_layer", "select_table"}
                and resolved_turn.dialogue_action
                not in {DialogueAction.GREETING, DialogueAction.EXPLAIN}
            ):
                answer_payload = InteractionAnswer(
                    interaction_id=str(pending.get("interaction_id") or ""),
                    custom_text=request.message.strip(),
                    state_version=int(pending.get("state_version") or 0),
                )
        if answer_payload is not None:
            answer = (
                answer_payload
                if isinstance(answer_payload, InteractionAnswer)
                else InteractionAnswer.model_validate(answer_payload)
            )
            try:
                resolved_answer = await self.conversation_graph.answer(
                    request.conversation_id, answer
                )
                state = await self.conversation_graph.context(request.conversation_id)
            except InteractionExpiredError as exc:
                current = await self.conversation_graph.context(request.conversation_id)
                response = AgentRunResponse(
                    str(exc),
                    success=False,
                    data={
                        "interaction": current.get("pending_interaction") or None,
                        "conversation": self._responses.conversation_meta(
                            request.conversation_id, current
                        ),
                    },
                    error="interaction_expired",
                )
                await publish("response.completed", response=self._response_data(response))
                return response

        response: AgentRunResponse | None = None

        # Greeting bypass: handle directly without going through the decision loop,
        # so greetings work regardless of pending interactions.
        if self.decisions._GREETING_RE.fullmatch(request.message.strip()):
            data = self._responses.greeting(
                state, state_version=int(state.get("state_version") or 0) + 1
            )
            greeting_msg = (
                "你好，我们可以继续当前任务。"
                if state.get("objective")
                else "你好！我可以协助你查表、问数、建模和排障。"
            )
            response = AgentRunResponse(
                greeting_msg,
                success=True,
                data={"agent_mode": "greeting", **data},
            )

        if response is None:
            for index in range(self._max_decisions):
                await publish("decision.started", index=index + 1)
                decision = await self.decisions.decide(
                    request,
                    state,
                    resolved_answer=resolved_answer,
                    interaction_purpose=str(pending.get("purpose") or ""),
                )
                await publish("decision.completed", decision=type(decision).__name__)

                if isinstance(decision, ToolDecision):
                    await publish(
                        "tool.started", tool=decision.tool_name, arguments=decision.arguments
                    )
                    result = await self.tools.execute(
                        decision.tool_name,
                        decision.arguments,
                        ToolContext(request.conversation_id, state),
                    )
                    await publish(
                        "tool.completed",
                        tool=decision.tool_name,
                        success=result.success,
                        error_code=result.error_code,
                        uncertain_write=result.uncertain_write,
                        provider=str(result.data.get("provider") or ""),
                    )
                    response = self._tool_response(result)
                    break
                if isinstance(decision, RespondDecision):
                    response = AgentRunResponse(
                        decision.message,
                        success=decision.success,
                        data=dict(decision.data),
                        error=decision.error,
                    )
                    break
                if isinstance(decision, ClarifyDecision):
                    response = AgentRunResponse(
                        decision.message,
                        success=False,
                        data={"agent_mode": "needs_context", **dict(decision.data)},
                        error=decision.error,
                    )
                    break
                if isinstance(decision, DelegateDecision):
                    if self._legacy_delegate is not None:
                        response = await self._legacy_delegate(request)
                    else:
                        data = self._responses.clarify(
                            state_version=int(state.get("state_version") or 0) + 1
                        )
                        response = AgentRunResponse(
                            "我还不能确定你的具体目标，请选择一个入口或补充说明。",
                            success=False,
                            data={"agent_mode": "needs_context", **data},
                            error="ambiguous_context",
                        )
                    break

        if response is None:
            response = AgentRunResponse(
                "本轮决策已达到安全上限，请缩小目标后继续。",
                success=False,
                data={"agent_mode": "bounded_stop"},
                error="decision_limit_reached",
            )

        if response.data.get("agent_mode") == "table_selected":
            response.data["interaction"] = self._table_next_action(
                str((response.data.get("selected_resources") or {}).get("table") or ""),
                int(state.get("state_version") or 0) + 1,
            )

        persisted = await self._persist(request, state, response)
        response.data["conversation"] = self._responses.conversation_meta(
            request.conversation_id, persisted
        )
        # Don't overwrite greeting responses with stale pending interactions
        is_greeting = response.data.get("agent_mode") == "greeting"
        if not is_greeting and persisted.get("pending_interaction"):
            response.data["interaction"] = dict(persisted["pending_interaction"])
        await publish("state.persisted", state_version=int(persisted.get("state_version") or 0))
        await publish("response.completed", response=self._response_data(response))
        return response

    @staticmethod
    def _tool_response(result: ToolResult) -> AgentRunResponse:
        if result.uncertain_write:
            mode = "execution_unknown"
            error = "execution_unknown"
        elif result.success:
            mode = "tool_result"
            error = None
        else:
            mode = "recoverable_error" if result.recoverable else "blocked"
            error = result.error_code or "tool_failed"
        data = dict(result.data)
        if not result.success and result.recoverable and not data.get("interaction"):
            data["interaction"] = PendingInteraction(
                interaction_id=f"retry_{abs(hash((result.error_code, result.message)))}",
                type="free_text",
                purpose="refine_table_search",
                prompt=result.message,
                options=[],
                custom_input_placeholder="输入新的表关键词，或直接开始另一个目标",
                state_version=1,
            ).model_dump()
        return AgentRunResponse(
            result.message,
            success=result.success,
            data={"agent_mode": mode, **data},
            error=error,
        )

    async def _persist(
        self,
        request: AgentRunRequest,
        state: dict[str, Any],
        response: AgentRunResponse,
    ) -> dict[str, Any]:
        interaction = response.data.get("interaction")
        selected = dict(state.get("selected_resources") or {})
        selected.update(response.data.get("selected_resources") or {})
        mode = str(response.data.get("agent_mode") or "")
        if mode == "execution_unknown":
            status = "execution_unknown"
        elif mode == "recoverable_error":
            status = "recoverable_error"
        elif mode == "greeting" and not state.get("task_status"):
            status = "idle"
        else:
            status = str(state.get("task_status") or "active")
        objective = str(state.get("objective") or "")
        if not objective and mode not in {"greeting", "explain", "needs_context"}:
            objective = request.message.strip()
        return await self.conversation_graph.remember(
            request.conversation_id,
            objective,
            needs_clarification=bool(interaction),
            action=(
                "find_table"
                if mode in {"tool_result", "waiting_user", "recoverable_error"}
                else None
            ),
            pending_interaction=dict(interaction) if isinstance(interaction, dict) else {},
            selected_resources=selected,
            last_result={
                "success": response.success,
                "error": response.error,
                "agent_mode": mode,
            },
            last_assistant_turn={"content": response.message},
            task_status=status,
        )

    @staticmethod
    def _table_next_action(table_name: str, state_version: int) -> dict[str, Any]:
        interaction = PendingInteraction(
            interaction_id=f"next_{state_version}_{abs(hash(table_name))}",
            purpose="table_next_action",
            prompt=f"已选择 {table_name}，下一步要做什么？",
            options=[
                InteractionOption(
                    id="inspect_columns",
                    label="查看字段",
                    value="查看字段",
                    description="读取表结构和字段说明",
                    payload={
                        "action": "inspect_table",
                        "params": {"table_name": table_name},
                        "selected_resources": {"table": table_name},
                    },
                ),
                InteractionOption(
                    id="ask_table",
                    label="基于此表问数",
                    value="基于此表问数",
                    description="先确认口径，再生成只读查询",
                    payload={
                        "action": "ask_data",
                        "params": {"table_name": table_name},
                        "selected_resources": {"table": table_name},
                    },
                ),
            ],
            custom_input_placeholder="也可以直接描述接下来的目标",
            state_version=state_version,
        )
        return interaction.model_dump()

    @staticmethod
    def _response_data(response: AgentRunResponse) -> dict[str, Any]:
        return {
            "message": response.message,
            "success": response.success,
            "data": dict(response.data),
            "error": response.error,
        }
