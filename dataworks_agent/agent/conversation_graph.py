"""LangGraph-backed conversational context for clarification follow-ups."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class ConversationState(TypedDict, total=False):
    incoming_message: str
    resolved_message: str
    pending_objective: str
    objective: str
    action: str
    params: dict[str, Any]
    workflow_state: dict[str, Any]
    context_updates: dict[str, Any]


class ConversationGraph:
    """Keep structured workflow context in LangGraph checkpoints keyed by conversation id."""

    def __init__(self) -> None:
        builder = StateGraph(ConversationState)
        builder.add_node("resolve_context", self._resolve_context)
        builder.add_edge(START, "resolve_context")
        builder.add_edge("resolve_context", END)
        self._checkpointer = InMemorySaver()
        self._graph = builder.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _resolve_context(state: ConversationState) -> dict[str, Any]:
        incoming = str(state.get("incoming_message") or "")
        pending = str(state.get("pending_objective") or "")
        updates = dict(state.get("context_updates") or {})
        if any(
            word in incoming.lower() for word in ("取消", "重新开始", "新任务", "cancel", "reset")
        ):
            return {
                "resolved_message": incoming,
                "pending_objective": "",
                "objective": incoming,
                "action": "",
                "params": {},
                "workflow_state": {},
            }
        objective = str(state.get("objective") or pending or incoming)
        resolved = (
            f"{objective}\n补充信息：{incoming}" if pending and incoming != objective else incoming
        )
        current_params = dict(state.get("params") or {})
        current_params.update(updates.get("params") or {})
        result: dict[str, Any] = {"resolved_message": resolved}
        if current_params:
            result["params"] = current_params
        if updates.get("workflow_state"):
            result["workflow_state"] = dict(updates["workflow_state"])
        if updates.get("action"):
            result["action"] = str(updates["action"])
        return result

    @staticmethod
    def _config(conversation_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": conversation_id}}

    async def resolve(
        self,
        message: str,
        conversation_id: str | None,
        *,
        context_updates: dict[str, Any] | None = None,
    ) -> str:
        if not conversation_id:
            return message
        state = await self._graph.ainvoke(
            {"incoming_message": message, "context_updates": context_updates or {}},
            config=self._config(conversation_id),
        )
        return str(state.get("resolved_message") or message)

    async def context(self, conversation_id: str | None) -> dict[str, Any]:
        if not conversation_id:
            return {}
        snapshot = await self._graph.aget_state(self._config(conversation_id))
        values = dict(snapshot.values or {})
        return {
            "objective": values.get("objective") or values.get("pending_objective") or "",
            "action": values.get("action") or "",
            "params": dict(values.get("params") or {}),
            "workflow_state": dict(values.get("workflow_state") or {}),
            "pending_objective": values.get("pending_objective") or "",
        }

    async def remember(
        self,
        conversation_id: str | None,
        objective: str,
        *,
        needs_clarification: bool,
        action: str | None = None,
        params: dict[str, Any] | None = None,
        workflow_state: dict[str, Any] | None = None,
    ) -> None:
        if not conversation_id:
            return
        current = await self.context(conversation_id)
        root_objective = str(current.get("objective") or objective)
        await self._graph.aupdate_state(
            self._config(conversation_id),
            {
                "objective": root_objective,
                "pending_objective": root_objective if needs_clarification else "",
                "action": action or current.get("action") or "",
                "params": dict(params or current.get("params") or {}),
                "workflow_state": dict(workflow_state or current.get("workflow_state") or {}),
            },
        )

    async def pending_objective(self, conversation_id: str) -> str:
        return str((await self.context(conversation_id)).get("pending_objective") or "")
