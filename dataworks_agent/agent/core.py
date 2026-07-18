"""Chat-oriented DataWorks Agent core."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakValueDictionary

from sqlalchemy import select

from dataworks_agent.agent.context_resolver import (
    ContextResolver,
    DialogueAction,
    LLMDialogueFallback,
)
from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.executor.task_executor import ExecutionResult, TaskExecutor
from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionExpiredError,
)
from dataworks_agent.agent.nlu.intent_parser import Intent, IntentParser
from dataworks_agent.agent.planner.task_planner import TaskPlan, TaskPlanner
from dataworks_agent.agent.response_policy import ResponsePolicy
from dataworks_agent.agent.workflow_service import AgentWorkflowService
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ConversationHistoryModel
from dataworks_agent.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_CONTEXT_SUMMARY_MARKERS = (
    "\u603b\u7ed3",
    "\u6458\u8981",
    "\u5f53\u524d\u4f1a\u8bdd",
    "\u5df2\u5b8c\u6210",
    "\u5efa\u6a21\u7ed3\u679c",
    "\u8fdb\u5c55",
    "\u72b6\u6001",
    "summary",
    "summarize",
)
_CONTEXT_NO_EXECUTION_MARKERS = (
    "\u4e0d\u8981\u91cd\u590d\u6267\u884c",
    "\u4e0d\u8981\u6267\u884c",
    "\u53ea\u8bf4\u660e",
    "\u4ec5\u8bf4\u660e",
    "\u4e0d\u91cd\u590d",
    "without executing",
    "do not execute",
)
_CONTEXT_READ_ONLY_MARKERS = (
    "sql",
    "ddl",
    "dml",
    "\u8c03\u5ea6",
    "schedule",
    "cron",
    "publish gate",
    "\u5ba1\u6279",
    "\u53d1\u5e03",
    "\u4ea7\u7269",
)
_CONTEXT_WRITE_MARKERS = (
    "\u5efa\u6a21",
    "\u521b\u5efa",
    "\u5efa\u8868",
    "\u5efa\u8282\u70b9",
    "\u6267\u884c",
    "\u91cd\u5efa",
    "\u4fee\u6539",
    "create",
    "execute",
)


_TURN_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_TURN_LOCKS_GUARD = threading.Lock()


def _turn_lock(conversation_id: str) -> asyncio.Lock:
    with _TURN_LOCKS_GUARD:
        lock = _TURN_LOCKS.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            _TURN_LOCKS[conversation_id] = lock
        return lock


@dataclass
class ChatResponse:
    """Chat response."""

    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ChatAgent:
    """Chat-oriented DataWorks Agent."""

    def __init__(self) -> None:
        self._intent_parser = IntentParser()
        self._task_planner = TaskPlanner()
        self._task_executor = TaskExecutor()
        self._workflow_service = AgentWorkflowService()
        self._skill_registry = SkillRegistry()
        self._conversation_graph = ConversationGraph()
        self._context_resolver = ContextResolver(LLMDialogueFallback())
        self._response_policy = ResponsePolicy()
        self._last_task_id: str | None = None

    async def chat(
        self,
        message: str,
        request_type: str | None = None,
        *,
        execution_mode: str | None = None,
        initialize_data: bool = True,
        publish: bool = False,
        client_ip: str = "127.0.0.1",
        conversation_id: str | None = None,
        context_updates: dict[str, Any] | None = None,
        interaction_answer: InteractionAnswer | dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Serialize a full conversation turn before any workflow side effect."""
        kwargs = {
            "execution_mode": execution_mode,
            "initialize_data": initialize_data,
            "publish": publish,
            "client_ip": client_ip,
            "conversation_id": conversation_id,
            "context_updates": context_updates,
            "interaction_answer": interaction_answer,
        }
        if not conversation_id:
            return await self._chat_locked(message, request_type, **kwargs)
        async with _turn_lock(conversation_id):
            return await self._chat_locked(message, request_type, **kwargs)

    async def _chat_locked(
        self,
        message: str,
        request_type: str | None = None,
        *,
        execution_mode: str | None = None,
        initialize_data: bool = True,
        publish: bool = False,
        client_ip: str = "127.0.0.1",
        conversation_id: str | None = None,
        context_updates: dict[str, Any] | None = None,
        interaction_answer: InteractionAnswer | dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Process one context-aware user turn."""
        if not message or not message.strip():
            return ChatResponse(
                message="请输入你希望 Agent 达成的业务或数据目标。我会先理解目标、拆解计划，再生成可审计的 dry-run 方案。",
                success=False,
                error="empty message",
            )

        previous_context: dict[str, Any] = {}
        consumed_interaction: dict[str, Any] | None = None
        workflow_started = False
        try:
            incoming_message = message.strip()
            answer = (
                interaction_answer
                if isinstance(interaction_answer, InteractionAnswer)
                else InteractionAnswer.model_validate(interaction_answer)
                if interaction_answer is not None
                else None
            )
            self._save_conversation_message(
                conversation_id,
                "user",
                incoming_message,
                payload={"interaction_answer": answer.model_dump(exclude_none=True)}
                if answer is not None
                else None,
            )
            previous_context = await self._conversation_graph.context(conversation_id)
            resolved_turn = await self._context_resolver.resolve(incoming_message, previous_context)
            answer = answer or resolved_turn.interaction_answer
            merged_context_updates = self._merge_context_updates(
                dict(context_updates or {}), resolved_turn.context_updates
            )

            if answer is None and resolved_turn.dialogue_action is DialogueAction.NEW_GOAL:
                previous_context = await self._conversation_graph.start_goal(
                    conversation_id, incoming_message
                )

            if answer is None and resolved_turn.dialogue_action is DialogueAction.CANCEL:
                context = await self._conversation_graph.cancel(conversation_id)
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    ChatResponse(
                        message="已取消当前任务。",
                        success=True,
                        data={"agent_mode": "cancelled"},
                    ),
                    context=context,
                )

            if answer is None and resolved_turn.dialogue_action is DialogueAction.RESET:
                await self._conversation_graph.resolve(incoming_message, conversation_id)
                context = await self._conversation_graph.context(conversation_id)
                data = self._response_policy.greeting(
                    {}, state_version=int(context.get("state_version") or 0) + 1
                )
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    ChatResponse(
                        message="已重置当前会话，请选择下一步或直接描述新目标。",
                        success=True,
                        data={"agent_mode": "reset", **data},
                    ),
                    context=context,
                )

            if answer is None and resolved_turn.dialogue_action is DialogueAction.GREETING:
                data = self._response_policy.greeting(
                    previous_context,
                    state_version=int(previous_context.get("state_version") or 0) + 1,
                )
                greeting = (
                    "你好，我们可以继续当前任务。"
                    if previous_context.get("objective")
                    else "你好！我可以协助你查表、问数、建模和排障。"
                )
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    ChatResponse(
                        message=greeting,
                        success=True,
                        data={"agent_mode": "greeting", **data},
                    ),
                    context=previous_context,
                )

            if answer is None and resolved_turn.dialogue_action is DialogueAction.EXPLAIN:
                explanation, data = self._response_policy.explain(previous_context)
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    ChatResponse(
                        message=explanation,
                        success=True,
                        data={"agent_mode": "explain", **data},
                    ),
                    context=previous_context,
                )

            if previous_context.get(
                "task_status"
            ) == "execution_unknown" and resolved_turn.dialogue_action not in {
                DialogueAction.CANCEL,
                DialogueAction.RESET,
                DialogueAction.NEW_GOAL,
                DialogueAction.GREETING,
                DialogueAction.EXPLAIN,
            }:
                is_status_query = self._is_execution_status_query(incoming_message)
                blocked_message = (
                    "当前执行结果仍待确认，不能继续或重复提交原写操作。"
                    if not is_status_query
                    else "当前执行结果仍待确认；请先通过任务或节点状态确认结果，再决定是否继续。"
                )
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    ChatResponse(
                        message=blocked_message,
                        success=False,
                        data={
                            "agent_mode": "execution_unknown",
                            "execution_result": "unknown",
                            "status_query": is_status_query,
                        },
                        error="execution_unknown",
                    ),
                    context=previous_context,
                )

            pending_interaction = previous_context.get("pending_interaction") or {}
            if (
                answer is None
                and pending_interaction
                and pending_interaction.get("allow_custom_input")
                and resolved_turn.dialogue_action
                not in {
                    DialogueAction.CONTINUE,
                    DialogueAction.MODIFY,
                    DialogueAction.REFER,
                    DialogueAction.NEW_GOAL,
                }
            ):
                answer = InteractionAnswer(
                    interaction_id=str(pending_interaction.get("interaction_id") or ""),
                    custom_text=incoming_message,
                    state_version=int(pending_interaction.get("state_version") or 0),
                )

            if answer is None and resolved_turn.dialogue_action is DialogueAction.CLARIFY:
                data = self._response_policy.clarify(
                    state_version=int(previous_context.get("state_version") or 0) + 1
                )
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    ChatResponse(
                        message="我还不能确定你的具体目标，请选择一个入口或补充说明。",
                        success=False,
                        data={"agent_mode": "needs_context", **data},
                        error="ambiguous_context",
                    ),
                    context=previous_context,
                )

            resolved_answer: dict[str, Any] = {}
            workflow_message = resolved_turn.rewritten_message
            if answer is not None:
                try:
                    resolved_answer = await self._conversation_graph.answer(conversation_id, answer)
                except InteractionExpiredError as exc:
                    current = (
                        exc.current.model_dump()
                        if exc.current is not None
                        else previous_context.get("pending_interaction") or None
                    )
                    return ChatResponse(
                        message=str(exc),
                        success=False,
                        data={"interaction": current},
                        error="interaction_expired",
                    )
                consumed_interaction = dict(pending_interaction)
                merged_context_updates = self._merge_context_updates(
                    merged_context_updates, resolved_answer
                )
                custom_text = str(resolved_answer.get("custom_text") or "").strip()
                if custom_text:
                    params_update = dict(merged_context_updates.get("params") or {})
                    params_update["custom_text"] = custom_text
                    merged_context_updates["params"] = params_update
                objective = str(
                    previous_context.get("pending_objective")
                    or previous_context.get("objective")
                    or ""
                ).strip()
                selected_layer = str(
                    (resolved_answer.get("params") or {}).get("layer") or ""
                ).strip()
                follow_up_action = str(
                    (resolved_answer.get("params") or {}).get("follow_up_action")
                    or resolved_answer.get("value")
                    or ""
                ).strip()
                workflow_message = (
                    f"{objective}\n补充信息：只要 {selected_layer}"
                    if selected_layer and objective
                    else f"{objective}\n补充信息：{custom_text}"
                    if custom_text and objective and custom_text != objective
                    else f"{objective}\n补充信息：{follow_up_action}"
                    if follow_up_action and objective
                    else custom_text or follow_up_action or objective or incoming_message
                )
            elif resolved_turn.dialogue_action is DialogueAction.CONTINUE and previous_context.get(
                "objective"
            ):
                workflow_message = str(previous_context["objective"])

            workflow_message = await self._conversation_graph.resolve(
                workflow_message,
                conversation_id,
                context_updates=merged_context_updates,
            )
            current_context = await self._conversation_graph.context(conversation_id)
            intent = self._intent_parser.parse(workflow_message)
            intent.params = self._merge_conversation_params(
                current_context.get("params") or previous_context.get("params") or {},
                intent.params,
                merged_context_updates.get("params") or {},
            )
            intent.params.setdefault("conversation_id", conversation_id)
            if answer is not None and pending_interaction.get("purpose"):
                intent.params["interaction_purpose"] = str(pending_interaction["purpose"])
            intent.params["goal"] = (
                intent.params.get("goal")
                or current_context.get("objective")
                or previous_context.get("objective")
                or incoming_message
            )

            if self._is_context_summary_request(incoming_message, current_context):
                response = self._build_context_summary_response(current_context, incoming_message)
                self._normalize_response_data(
                    response,
                    action=str(current_context.get("action") or "summary"),
                    state_version=int(current_context.get("state_version") or 0) + 1,
                )
                return await self._complete_turn(
                    conversation_id, incoming_message, response, context=current_context
                )
            if self._is_context_read_only_request(incoming_message, current_context):
                response = self._build_context_read_only_response(current_context, incoming_message)
                self._normalize_response_data(
                    response,
                    action=str(current_context.get("action") or "read_only"),
                    state_version=int(current_context.get("state_version") or 0) + 1,
                )
                return await self._complete_turn(
                    conversation_id, incoming_message, response, context=current_context
                )

            previous_action = str(current_context.get("action") or "")
            if previous_action and (answer is not None or intent.action == "unknown"):
                intent.action = previous_action
                intent.confidence = max(intent.confidence, 0.75)
            business_query = self._resolve_business_query(workflow_message, current_context)
            if business_query is not None and (not request_type or request_type == "auto"):
                intent.action = "ask_data"
                intent.params["business_query"] = business_query
                intent.confidence = 1.0
            if request_type and request_type != "auto":
                intent.action = request_type
            logger.info("NLU parsed: action=%s, confidence=%.2f", intent.action, intent.confidence)

            workflow_actions = {
                "agent_workflow",
                "ods_dwd_modeling",
                "forward_modeling",
                "any_ods_modeling",
                "reverse_modeling",
                "diagnose_issue",
                "cookie_manage",
                "ask_data",
            }
            if intent.action == "ask_data" and execution_mode is None:
                execution_mode = "auto"
            if intent.action in workflow_actions and (
                execution_mode is not None
                or intent.action in {"ods_dwd_modeling", "forward_modeling", "any_ods_modeling"}
            ):
                workflow_started = True
                workflow = await self._workflow_service.execute(
                    message=workflow_message,
                    action=intent.action,
                    params=dict(intent.params or {}, conversation_id=conversation_id),
                    execution_mode=execution_mode,
                    initialize_data=initialize_data,
                    publish=publish,
                    client_ip=client_ip,
                )
                data = workflow.to_data()
                data.update(
                    {
                        "intent": self._intent_to_dict(intent),
                        "plan": {"summary": workflow.message, "steps": workflow.steps},
                        "agent_mode": (
                            "needs_context"
                            if data.get("needs_clarification")
                            else "approval_required"
                            if data.get("publish_request")
                            else "executed"
                            if workflow.mode == "dev_execute" and workflow.success
                            else "blocked"
                            if not workflow.success
                            else "proposal"
                        ),
                    }
                )
                data = self._response_policy.normalize_workflow_data(
                    {**data, "message": workflow.message},
                    purpose=self._interaction_purpose(data, intent.action),
                    state_version=int(current_context.get("state_version") or 0) + 1,
                )
                data["needs_clarification"] = bool(data.get("interaction"))
                response = ChatResponse(
                    message=workflow.message,
                    success=workflow.success,
                    data=data,
                    error=workflow.errors[0] if workflow.errors else None,
                )
                turn_context = {
                    **current_context,
                    "action": intent.action,
                    "params": intent.params,
                    "workflow_state": {
                        "current_step": data.get("next_step"),
                        "missing_context": data.get("missing_context") or [],
                        "completed_steps": data.get("completed_steps") or [],
                        "result_data": self._conversation_result_snapshot(data),
                        "message": workflow.message,
                    },
                    "query_frame": self._query_frame_from_data(data)
                    or current_context.get("query_frame")
                    or {},
                }
                return await self._complete_turn(
                    conversation_id,
                    incoming_message,
                    response,
                    context=turn_context,
                )

            plan = self._task_planner.plan(intent)
            logger.info("Task planned: task_id=%s, steps=%d", plan.task_id, len(plan.steps))
            if not plan.steps:
                response = self._build_no_plan_response(intent, plan)
            else:
                result = self._task_executor.execute(plan)
                self._last_task_id = result.task_id
                response = self._build_response(intent, plan, result)
            self._normalize_response_data(
                response,
                action=intent.action,
                state_version=int(current_context.get("state_version") or 0) + 1,
            )
            turn_context = {
                **current_context,
                "action": intent.action,
                "params": intent.params,
            }
            return await self._complete_turn(
                conversation_id,
                incoming_message,
                response,
                context=turn_context,
            )
        except Exception as exc:
            logger.exception("ChatAgent failed: %s", exc)
            if conversation_id and workflow_started:
                return await self._mark_execution_unknown(conversation_id, incoming_message, exc)
            if consumed_interaction and conversation_id:
                return await self._recover_consumed_interaction(
                    conversation_id,
                    incoming_message,
                    previous_context,
                    consumed_interaction,
                    exc,
                )
            return ChatResponse(message=f"处理失败：{exc}", success=False, error=str(exc))

    @staticmethod
    def _is_conversation_reset(message: str) -> bool:
        text = message.lower()
        return any(marker in text for marker in ("取消", "重新开始", "新任务", "cancel", "reset"))

    @staticmethod
    def _is_context_summary_request(message: str, context: dict[str, Any]) -> bool:
        """Handle read-only follow-ups without re-running the previous workflow."""
        if not message or not context.get("workflow_state"):
            return False
        text = message.lower()
        has_summary_marker = any(marker in text for marker in _CONTEXT_SUMMARY_MARKERS)
        explicitly_no_execution = any(marker in text for marker in _CONTEXT_NO_EXECUTION_MARKERS)
        return has_summary_marker or explicitly_no_execution

    @staticmethod
    def _is_context_read_only_request(message: str, context: dict[str, Any]) -> bool:
        """Answer artifact/schedule/review follow-ups without rerunning writes."""
        if not message or not context.get("workflow_state"):
            return False
        text = message.lower()
        if any(marker in text for marker in _CONTEXT_WRITE_MARKERS):
            return False
        return any(marker in text for marker in _CONTEXT_READ_ONLY_MARKERS)

    @classmethod
    def _build_context_read_only_response(
        cls, context: dict[str, Any], incoming_message: str
    ) -> ChatResponse:
        """Expose persisted workflow evidence for a conversational read-only follow-up."""
        state = dict(context.get("workflow_state") or {})
        snapshot = dict(state.get("result_data") or {})
        text = incoming_message.lower()
        artifacts = snapshot.get("artifacts") or {}
        ods = artifacts.get("ods") if isinstance(artifacts, dict) else {}
        dwd = artifacts.get("dwd") if isinstance(artifacts, dict) else {}
        read_only_artifacts: dict[str, Any] = {}
        if any(marker in text for marker in ("sql", "ddl", "dml", "\u4ea7\u7269")):
            read_only_artifacts = {
                "ods_sql": ods.get("sql") if isinstance(ods, dict) else None,
                "dwd_sql": dwd.get("sql") if isinstance(dwd, dict) else None,
                "ods_ddl": ods.get("ddl") if isinstance(ods, dict) else None,
                "dwd_ddl": dwd.get("ddl") if isinstance(dwd, dict) else None,
            }
            message = "\u5df2\u8bfb\u53d6\u5f53\u524d\u4f1a\u8bdd\u7684 ODS/DWD SQL \u4ea7\u7269\uff0c\u672a\u91cd\u590d\u5efa\u6a21\u6216\u5199\u5165 DataWorks\u3002"
        elif any(marker in text for marker in ("\u8c03\u5ea6", "schedule", "cron")):
            schedule = snapshot.get("schedule") or {}
            read_only_artifacts = {
                "schedule": schedule,
                "ods_schedule": (snapshot.get("ods_pipeline") or {}).get("cron"),
                "dwd_schedule": (snapshot.get("dwd_pipeline") or {}).get("cron"),
            }
            message = "\u5df2\u8bfb\u53d6\u5f53\u524d\u4f1a\u8bdd\u7684 ODS/DWD \u8c03\u5ea6\u4fe1\u606f\uff0c\u672a\u91cd\u590d\u914d\u7f6e\u8c03\u5ea6\u6216\u5199\u5165 DataWorks\u3002"
        elif any(marker in text for marker in ("publish gate", "\u5ba1\u6279", "\u53d1\u5e03")):
            read_only_artifacts = {
                "prod_tables": snapshot.get("prod_tables") or {},
                "publish_gate": snapshot.get("publish_gate") or "not_requested",
            }
            message = "\u5df2\u8bfb\u53d6\u751f\u4ea7 DDL \u4e0e Publish Gate \u72b6\u6001\uff0c\u672a\u91cd\u590d\u53d1\u5e03\u6216\u63d0\u4ea4\u5ba1\u6279\u3002"
        else:
            message = "\u5df2\u8bfb\u53d6\u5f53\u524d\u4f1a\u8bdd\u7684\u5de5\u4f5c\u6d41\u4ea7\u7269\uff0c\u672a\u91cd\u590d\u6267\u884c\u5199\u64cd\u4f5c\u3002"

        data = {
            **snapshot,
            "read_only_follow_up": True,
            "conversation_follow_up": True,
            "read_only_artifacts": read_only_artifacts,
            "next_actions": snapshot.get("next_actions") or [],
            "allow_custom_input": True,
            "custom_input_hint": snapshot.get("custom_input_hint")
            or "\u53ef\u4ee5\u8f93\u5165 SQL\u3001\u8c03\u5ea6\u3001Publish Gate \u5ba1\u67e5\u6216\u5176\u4ed6\u540e\u7eed\u8981\u6c42\u3002",
            "agent_mode": "read_only",
            "plan": {"summary": message, "steps": snapshot.get("steps") or []},
            "conversation_context": {
                "objective": context.get("objective") or "",
                "action": context.get("action") or "",
                "last_request": incoming_message,
                "publish_gate": snapshot.get("publish_gate") or "not_requested",
            },
        }
        return ChatResponse(message=message, success=True, data=data)

    @staticmethod
    def _conversation_result_snapshot(data: dict[str, Any]) -> dict[str, Any]:
        """Keep enough result evidence for deterministic conversational summaries."""
        keys = (
            "standard",
            "workflow_type",
            "execution_mode",
            "steps",
            "artifacts",
            "dev_tables",
            "prod_tables",
            "ods_pipeline",
            "dwd_pipeline",
            "schedule",
            "dependency_plan",
            "template_task_id",
            "checker",
            "publish_gate",
            "next_actions",
            "allow_custom_input",
            "custom_input_hint",
        )
        return {key: data[key] for key in keys if key in data}

    @classmethod
    def _build_context_summary_response(
        cls, context: dict[str, Any], incoming_message: str
    ) -> ChatResponse:
        """Return the current workflow state and candidates without another write."""
        state = dict(context.get("workflow_state") or {})
        snapshot = dict(state.get("result_data") or {})
        completed_steps = [
            item.get("step")
            for item in (snapshot.get("steps") or state.get("completed_steps") or [])
            if isinstance(item, dict) and item.get("status") == "completed" and item.get("step")
        ]
        dev_tables = snapshot.get("dev_tables") or {}
        table_names: list[str] = []
        if isinstance(dev_tables, dict):
            for value in dev_tables.values():
                if isinstance(value, dict):
                    table = value.get("table") or value.get("table_name")
                    schema = value.get("schema")
                    if table:
                        table_names.append(f"{schema}.{table}" if schema else str(table))
                elif value:
                    table_names.append(str(value))
        if not table_names:
            for pipeline_key in ("ods_pipeline", "dwd_pipeline"):
                pipeline = snapshot.get(pipeline_key) or {}
                if isinstance(pipeline, dict) and pipeline.get("node_path"):
                    table_names.append(str(pipeline["node_path"]))

        standard = snapshot.get("standard") or "\u6807\u51c6 OSS \u5efa\u6a21"
        publish_gate = snapshot.get("publish_gate") or "not_requested"
        production_pending = any(
            isinstance(value, dict) and value.get("status") == "approval_required"
            for value in (snapshot.get("prod_tables") or {}).values()
        )
        if production_pending:
            production_text = (
                "\u751f\u4ea7 DDL \u5df2\u751f\u6210\uff0c\u7b49\u5f85 Publish Gate \u5ba1\u6279"
            )
        else:
            production_text = "\u751f\u4ea7\u4ea7\u7269\u5df2\u51c6\u5907"
        completed_text = (
            f"\u5df2\u5b8c\u6210 {len(completed_steps)} \u4e2a\u6b65\u9aa4"
            if completed_steps
            else "\u5c1a\u672a\u5b8c\u6210\u6b65\u9aa4"
        )
        tables_text = (
            "\u3001".join(table_names[:6])
            or "\u6682\u65e0\u5f00\u53d1\u8868\u6216\u8282\u70b9\u4fe1\u606f"
        )
        message = (
            f"\u5f53\u524d\u4f1a\u8bdd\u4e0a\u4e0b\u6587\uff1a{standard}\uff1b{completed_text}\uff1b"
            f"\u5f00\u53d1\u8868\u6216\u8282\u70b9\uff1a{tables_text}\uff1b{production_text}"
        )
        next_actions = snapshot.get("next_actions") or [
            {
                "id": "inspect_current_model",
                "label": "\u68c0\u67e5 ODS/DWD SQL \u4ea7\u7269",
            },
            {
                "id": "check_current_schedule",
                "label": "\u67e5\u770b\u5f53\u524d ODS/DWD \u8c03\u5ea6",
            },
            {
                "id": "prepare_publish_review",
                "label": "\u51c6\u5907 Publish Gate \u5ba1\u67e5",
            },
        ]
        data = {
            **snapshot,
            "conversation_follow_up": True,
            "conversation_context": {
                "objective": context.get("objective") or "",
                "action": context.get("action") or "",
                "last_request": incoming_message,
                "publish_gate": publish_gate,
            },
            "next_actions": next_actions,
            "allow_custom_input": True,
            "custom_input_hint": "\u53ef\u4ee5\u8f93\u5165\u81ea\u5b9a\u4e49\u540e\u7eed\u8981\u6c42\uff0c\u4f8b\u5982\uff1a\u67e5\u770b SQL\u3001\u67e5\u770b\u8c03\u5ea6\u3001\u51c6\u5907 Publish Gate \u5ba1\u67e5\u3002",
            "agent_mode": "executed",
            "plan": {"summary": message, "steps": snapshot.get("steps") or []},
        }
        return ChatResponse(message=message, success=True, data=data)

    @staticmethod
    def _merge_conversation_params(
        previous: dict[str, Any],
        current: dict[str, Any],
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge structured follow-up answers without losing the original goal."""
        merged = dict(previous)
        for source in (current, updates):
            for key, value in source.items():
                if value is None or value == "" or value == []:
                    continue
                if key == "goal" and merged.get("goal"):
                    continue
                merged[key] = value
        return merged

    @staticmethod
    def _is_execution_status_query(message: str) -> bool:
        text = message.lower()
        return any(
            marker in text
            for marker in (
                "状态",
                "结果",
                "是否成功",
                "查询任务",
                "查询节点",
                "status",
                "result",
            )
        )

    async def _mark_execution_unknown(
        self,
        conversation_id: str,
        incoming_message: str,
        error: Exception,
    ) -> ChatResponse:
        """Do not reissue an executable card after a risky workflow has started."""
        try:
            current = await self._conversation_graph.context(conversation_id)
            remembered = await self._conversation_graph.remember(
                conversation_id,
                str(current.get("objective") or incoming_message),
                needs_clarification=False,
                action=str(current.get("action") or ""),
                params=dict(current.get("params") or {}),
                workflow_state=dict(current.get("workflow_state") or {}),
                pending_interaction=None,
                selected_resources=dict(current.get("selected_resources") or {}),
                last_result={
                    "execution_result": "unknown",
                    "error": str(error),
                },
                last_assistant_turn={
                    "content": "执行已启动，但结果尚未确认。",
                    "payload": {"execution_result": "unknown"},
                },
                conversation_summary=str(current.get("conversation_summary") or ""),
                query_frame=dict(current.get("query_frame") or {}),
                task_status="execution_unknown",
                expected_version=int(current.get("state_version") or 0),
            )
            response = ChatResponse(
                message=(
                    "执行请求已经启动，但返回结果无法确认。为避免重复写入，请不要重复提交；"
                    "请先查询任务或节点状态。"
                ),
                success=False,
                data={
                    "agent_mode": "execution_unknown",
                    "execution_result": "unknown",
                    "conversation": self._response_policy.conversation_meta(
                        conversation_id, remembered
                    ),
                },
                error=str(error),
            )
            self._save_conversation_message(
                conversation_id,
                "assistant",
                response.message,
                payload=response.data,
            )
            return response
        except Exception:
            logger.exception("Failed to persist unknown execution state")
            return ChatResponse(
                message=(
                    "执行请求可能已经启动，但结果无法确认。请不要重复提交，先查询任务或节点状态。"
                ),
                success=False,
                data={"agent_mode": "execution_unknown"},
                error=str(error),
            )

    async def _recover_consumed_interaction(
        self,
        conversation_id: str,
        incoming_message: str,
        previous_context: dict[str, Any],
        consumed_interaction: dict[str, Any],
        error: Exception,
    ) -> ChatResponse:
        """Reissue a consumed card when downstream processing fails."""
        try:
            current = await self._conversation_graph.context(conversation_id)
            restored = await self._conversation_graph.remember(
                conversation_id,
                str(previous_context.get("objective") or incoming_message),
                needs_clarification=True,
                action=str(previous_context.get("action") or ""),
                params=dict(previous_context.get("params") or {}),
                workflow_state=dict(previous_context.get("workflow_state") or {}),
                pending_interaction=dict(consumed_interaction),
                selected_resources=dict(previous_context.get("selected_resources") or {}),
                last_result=dict(previous_context.get("last_result") or {}),
                last_assistant_turn=dict(previous_context.get("last_assistant_turn") or {}),
                conversation_summary=str(previous_context.get("conversation_summary") or ""),
                query_frame=dict(previous_context.get("query_frame") or {}),
                task_status="waiting_user",
                expected_version=int(current.get("state_version") or 0),
            )
            response = ChatResponse(
                message=f"执行当前选择时失败：{error}。候选卡片已恢复，你可以重试或补充说明。",
                success=False,
                data={
                    "agent_mode": "retryable_error",
                    "interaction": dict(restored.get("pending_interaction") or {}),
                    "conversation": self._response_policy.conversation_meta(
                        conversation_id, restored
                    ),
                },
                error=str(error),
            )
            self._save_conversation_message(
                conversation_id,
                "assistant",
                response.message,
                payload=response.data,
            )
            return response
        except Exception:
            logger.exception("Failed to restore consumed interaction")
            return ChatResponse(
                message=f"处理失败：{error}",
                success=False,
                error=str(error),
            )

    def _resolve_business_query(
        self, message: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        direct = self._workflow_service.understand_business_query(message)
        if direct is not None:
            return direct
        previous = context.get("query_frame")
        if not isinstance(previous, dict) or not previous:
            return None
        return self._workflow_service.refine_business_query(message, previous)

    @staticmethod
    def _query_frame_from_data(data: dict[str, Any]) -> dict[str, Any]:
        semantic_plan = data.get("semantic_plan") or {}
        query_frame = semantic_plan.get("business_query")
        if not isinstance(query_frame, dict) or not query_frame.get("metric_id"):
            return {}
        return dict(query_frame)

    def _normalize_response_data(
        self,
        response: ChatResponse,
        *,
        action: str,
        state_version: int,
    ) -> None:
        response.data = self._response_policy.normalize_workflow_data(
            response.data,
            purpose=self._interaction_purpose(response.data, action),
            state_version=state_version,
        )

    async def _complete_turn(
        self,
        conversation_id: str | None,
        incoming_message: str,
        response: ChatResponse,
        *,
        context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        if not conversation_id:
            return response
        persisted = await self._conversation_graph.context(conversation_id)
        current = {**persisted, **dict(context or {})}
        interaction = response.data.get("interaction") if isinstance(response.data, dict) else None
        agent_mode = str(response.data.get("agent_mode") or "")
        has_active_goal = bool(current.get("objective"))
        objective = str(current.get("objective") or incoming_message)
        if not has_active_goal and agent_mode in {
            "greeting",
            "explain",
            "cancelled",
            "reset",
            "needs_context",
        }:
            objective = ""
        task_status = (
            "cancelled"
            if agent_mode == "cancelled"
            else "execution_unknown"
            if agent_mode == "execution_unknown"
            else "idle"
            if agent_mode == "reset"
            else "waiting_user"
            if interaction
            else "active"
        )
        remembered = await self._conversation_graph.remember(
            conversation_id,
            objective,
            needs_clarification=bool(interaction),
            action=str(current.get("action") or ""),
            params=dict(current.get("params") or {}),
            workflow_state=dict(current.get("workflow_state") or {}),
            pending_interaction=dict(interaction or {}) if interaction is not None else None,
            selected_resources=dict(current.get("selected_resources") or {}),
            last_result=dict(response.data or {}),
            last_assistant_turn={
                "content": response.message,
                "payload": dict(response.data or {}),
            },
            conversation_summary=str(current.get("conversation_summary") or ""),
            query_frame=dict(current.get("query_frame") or {}),
            task_status=task_status,
            expected_version=int(persisted.get("state_version") or 0),
        )
        if not isinstance(remembered, dict):
            remembered = await self._conversation_graph.context(conversation_id)
        if interaction is not None:
            response.data["interaction"] = dict(
                remembered.get("pending_interaction") or interaction
            )
        response.data["conversation"] = self._response_policy.conversation_meta(
            conversation_id, remembered
        )
        self._save_conversation_message(
            conversation_id,
            "assistant",
            response.message,
            payload=response.data,
        )
        return response

    def _save_conversation_message(
        self,
        conversation_id: str | None,
        role: str,
        content: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """保存对话消息到数据库。"""
        if not conversation_id or not content:
            logger.debug(
                "跳过保存消息: conversation_id=%s, content_len=%d",
                conversation_id,
                len(content) if content else 0,
            )
            return
        try:
            session = SessionLocal()
            try:
                msg = ConversationHistoryModel(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    payload_json=json.dumps(payload or {}, ensure_ascii=False),
                )
                session.add(msg)
                session.commit()
                logger.debug("保存消息成功: conversation_id=%s, role=%s", conversation_id, role)
            finally:
                session.close()
        except Exception as e:
            logger.warning("保存对话消息失败: %s", e)

    def get_conversation_history(
        self, conversation_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """获取对话历史消息。"""
        if not conversation_id:
            return []
        try:
            session = SessionLocal()
            try:
                stmt = (
                    select(ConversationHistoryModel)
                    .where(ConversationHistoryModel.conversation_id == conversation_id)
                    .order_by(ConversationHistoryModel.id.desc())
                    .limit(limit)
                )
                result = session.execute(stmt)
                messages = result.scalars().all()
                history: list[dict[str, Any]] = []
                for msg in reversed(messages):
                    item: dict[str, Any] = {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.created_at,
                    }
                    try:
                        payload = json.loads(getattr(msg, "payload_json", "{}") or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        payload = {}
                    if isinstance(payload, dict) and payload:
                        item["payload"] = payload
                    history.append(item)
                return history
            finally:
                session.close()
        except Exception as e:
            logger.warning("获取对话历史失败: %s", e)
            return []

    async def get_conversation_context(self, conversation_id: str) -> dict[str, Any]:
        """Return live checkpoint state for restoring the actionable interaction."""
        return await self._conversation_graph.context(conversation_id)

    @staticmethod
    def _merge_context_updates(current: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        for key in ("params", "selected_resources", "workflow_state"):
            values = dict(merged.get(key) or {})
            values.update(resolved.get(key) or {})
            if values:
                merged[key] = values
        if resolved.get("action"):
            merged["action"] = resolved["action"]
        return merged

    @staticmethod
    def _interaction_purpose(data: dict[str, Any], action: str) -> str:
        existing = data.get("interaction")
        if isinstance(existing, dict) and existing.get("purpose"):
            return str(existing["purpose"])
        if data.get("interaction_purpose"):
            return str(data["interaction_purpose"])
        for option in data.get("option_chips") or []:
            if isinstance(option, dict) and option.get("type") == "pick_table":
                return "select_table"
        return "clarify_" + (action or "request")

    def capability_status(self) -> dict[str, Any]:
        """Return the live AK/SK, Cookie/CDP and official MCP capability matrix."""
        return self._workflow_service.capability_status()

    def get_status(self, task_id: str | None = None) -> dict[str, Any] | None:
        """Get task status."""
        target = task_id or self._last_task_id
        if not target:
            return None
        status = self._task_executor.monitor.get_status(target)
        return status.to_dict() if status else None

    def _build_no_plan_response(self, intent: Intent, plan: TaskPlan) -> ChatResponse:
        questions = [
            "你希望我处理哪张源表或目标表？",
            "目标是建模、血缘分析、任务诊断、指标归因，还是发布前检查？",
            "是否只生成 dry-run 方案，不执行线上写入？",
        ]
        return ChatResponse(
            message=(
                f"我还不能把“{intent.raw_text}”映射成可靠的 DataWorks Agent 工作流。"
                "请补充目标表、源表或任务类型，我会继续拆解计划。"
            ),
            success=False,
            data={
                "intent": self._intent_to_dict(intent),
                "plan": plan.to_dict(),
                "clarifying_questions": questions,
                "next_actions": questions,
                "agent_mode": "needs_context",
                "verification": {
                    "status": "failed",
                    "summary": "No executable intent recognized",
                    "checks": [
                        {
                            "name": "intent_recognized",
                            "passed": False,
                            "severity": "error",
                            "message": "The request was not mapped to an executable workflow",
                        }
                    ],
                },
            },
            error="unsupported intent",
        )

    def _build_response(
        self, intent: Intent, plan: TaskPlan, result: ExecutionResult
    ) -> ChatResponse:
        artifacts = self._collect_artifacts(result)
        approvals = self._collect_approvals(intent, plan, result)
        next_actions = self._next_actions(intent, plan, result)
        agent_mode = self._agent_mode(intent, plan, result, approvals)
        clarifying_questions = self._clarifying_questions(intent, result)

        data = {
            "task_id": result.task_id,
            "steps_completed": len([s for s in result.step_results if s.success]),
            "intent": self._intent_to_dict(intent),
            "plan": plan.to_dict(),
            "execution": result.to_dict(),
            "status": result.status.to_dict() if result.status else None,
            "artifacts": artifacts,
            "approvals": approvals,
            "clarifying_questions": clarifying_questions,
            "next_actions": next_actions,
            "agent_mode": agent_mode,
        }
        if result.success:
            return ChatResponse(
                message=self._format_success_message(intent, plan, result, agent_mode),
                success=True,
                data=data,
            )
        return ChatResponse(
            message=self._format_error_message(intent, result),
            success=False,
            data=data,
            error=result.errors[0] if result.errors else "unknown error",
        )

    def _intent_to_dict(self, intent: Intent) -> dict[str, Any]:
        return {
            "action": intent.action,
            "params": intent.params,
            "confidence": intent.confidence,
            "raw_text": intent.raw_text,
            "is_negated": intent.is_negated,
        }

    def _format_success_message(
        self,
        intent: Intent,
        plan: TaskPlan,
        result: ExecutionResult,
        agent_mode: str,
    ) -> str:
        table_name = intent.params.get("table_name", "")
        lines = [
            f"已按 Agent 工作流完成一轮安全规划：{plan.summary}。",
            f"任务 ID：`{result.task_id}`，完成步骤：{len(result.step_results)}/{len(plan.steps)}。",
        ]
        if table_name:
            lines.append(f"目标表：`{table_name}`。")
        if agent_mode == "approval_required":
            lines.append(
                "已到真实写入/发布边界：后续必须进入 Publish Gate 审批，不会直接操作线上 DataWorks。"
            )
        elif plan.needs_confirmation:
            lines.append("该请求置信度较低或包含否定表达，后续写操作前需要确认。")
        lines.append("当前结果是可审计的 dry-run/proposal，不会伪装成已在线上发布。")
        return "\n".join(lines)

    def _format_error_message(self, intent: Intent, result: ExecutionResult) -> str:
        return f"执行被阻塞：{'; '.join(result.errors)}"

    def _next_actions(self, intent: Intent, plan: TaskPlan, result: ExecutionResult) -> list[str]:
        actions: list[str] = []
        missing_table = "table_name" not in intent.params and intent.action in {
            "create_table",
            "query_lineage",
            "forward_modeling",
            "reverse_modeling",
            "publish_review",
            "ods_dwd_modeling",
        }
        if missing_table:
            actions.append("补充目标表名，例如 ods_xxx / dwd_xxx。")
        if any(step.error == "missing_table_name" for step in result.step_results):
            actions.append("提供目标表名，例如 ods_xxx / dwd_xxx。")
        for step in result.step_results:
            data = step.data or {}
            for action in data.get("actions", []) if isinstance(data.get("actions"), list) else []:
                if isinstance(action, str):
                    actions.append(action)
        if result.success:
            actions.extend(
                [
                    "查看计划步骤和产物草稿，确认是否进入真实执行。",
                    "补齐源表、字段、业务域、调度周期后运行完整 dry-run。",
                    "涉及发布、删除、覆盖等写操作时走 Publish Gate 审批。",
                ]
            )
        else:
            actions.append("先处理失败步骤，再继续后续 DataWorks 操作。")
        return list(dict.fromkeys(actions))

    def _collect_artifacts(self, result: ExecutionResult) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        for step in result.step_results:
            data = step.data or {}
            if data.get("ddl") and "ddl" not in artifacts:
                artifacts["ddl"] = data["ddl"]
            if data.get("sql") and "sql" not in artifacts:
                artifacts["sql"] = data["sql"]
            if data.get("schedule") and "schedule" not in artifacts:
                artifacts["schedule"] = data["schedule"]
            if data.get("lineage") and "lineage" not in artifacts:
                artifacts["lineage"] = data["lineage"]
            if data.get("risk_report") and "risk_report" not in artifacts:
                artifacts["risk_report"] = data["risk_report"]
            if data.get("ods_plan") and "ods_plan" not in artifacts:
                artifacts["ods_plan"] = data["ods_plan"]
            if data.get("dwd_preview") and "dwd_preview" not in artifacts:
                artifacts["dwd_preview"] = data["dwd_preview"]
            if data.get("dependency_plan") and "dependency_plan" not in artifacts:
                artifacts["dependency_plan"] = data["dependency_plan"]
            if data.get("capability_matrix") and "capability_matrix" not in artifacts:
                artifacts["capability_matrix"] = data["capability_matrix"]
        return artifacts

    def _collect_approvals(
        self,
        intent: Intent,
        plan: TaskPlan,
        result: ExecutionResult,
    ) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        if intent.action == "publish_review" or intent.is_negated:
            approvals.append(
                {
                    "type": "publish_gate",
                    "status": "required",
                    "reason": "请求触达发布/高风险边界，需要显式审批。",
                }
            )
        for step in result.step_results:
            data = step.data or {}
            if data.get("requires_approval") or data.get("publish_gate"):
                approvals.append(
                    {
                        "type": "publish_gate",
                        "status": "required",
                        "step_id": step.step_id,
                        "tool": step.tool,
                        "reason": "该步骤涉及真实写入、覆盖、发布或恢复动作。",
                    }
                )
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for item in approvals:
            key = (str(item.get("type")), str(item.get("tool", item.get("reason"))))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _agent_mode(
        self,
        intent: Intent,
        plan: TaskPlan,
        result: ExecutionResult,
        approvals: list[dict[str, Any]],
    ) -> str:
        if not result.success:
            return "blocked"
        if self._clarifying_questions(intent, result):
            return "needs_context"
        if approvals:
            return "approval_required"
        if plan.needs_confirmation:
            return "needs_context"
        return "proposal"

    def _clarifying_questions(self, intent: Intent, result: ExecutionResult) -> list[str]:
        questions: list[str] = []
        params = intent.params
        if intent.action in {"forward_modeling", "create_table", "agent_workflow"}:
            if not params.get("table_name"):
                questions.append("目标表名是什么？例如 dwd_trade_order_detail。")
            if not params.get("source_table"):
                questions.append("源表或主要输入表是什么？例如 ods_order。")
        if intent.action == "ods_dwd_modeling":
            source_table = params.get("source_table")
            ods_table = params.get("ods_table")
            source_type = params.get("source_type")
            is_existing_ods = isinstance(source_table, str) and source_table.lower().startswith(
                "ods_"
            )
            if not params.get("dwd_table") and not params.get("table_name"):
                questions.append(
                    "DWD \u76ee\u6807\u8868\u540d\u662f\u4ec0\u4e48\uff1f\u4f8b\u5982 dwd_trade_order_detail\u3002"
                )
            if not source_table and not ods_table and not params.get("oss_path"):
                questions.append(
                    "\u6e90\u8868\u3001OSS \u8def\u5f84\u6216\u5df2\u6709 ODS \u8868\u662f\u4ec0\u4e48\uff1f\u4f8b\u5982 orders / oss://bucket/path/orders.csv / ods_order\u3002"
                )
            if not source_type and not ods_table and not is_existing_ods:
                questions.append(
                    "ODS \u6765\u6e90\u7c7b\u578b\u662f\u4ec0\u4e48\uff1f\u53ef\u9009 mysql\u3001hologres\u3001oss\u3001realtime \u6216\u5df2\u6709 ODS\u3002"
                )
            if source_type in {
                "mysql",
                "polardb",
                "postgres",
                "oracle",
                "sqlserver",
                "hologres",
                "realtime",
            } and not params.get("datasource_name"):
                questions.append(
                    "DataWorks \u6570\u636e\u6e90\u540d\u79f0\u662f\u4ec0\u4e48\uff1f\u4f8b\u5982 jky_singleshop \u6216 dataworks_holo\u3002"
                )
            for step in result.step_results:
                missing = (step.data or {}).get("missing_context", [])
                if isinstance(missing, list) and missing:
                    questions.append(
                        "\u8bf7\u8865\u9f50\u7f3a\u5931\u4e0a\u4e0b\u6587\uff1a"
                        + "\u3001".join(str(item) for item in missing)
                        + "\u3002"
                    )
        if intent.action in {"metric_attribution"} and not params.get("metric_id"):
            questions.append("需要归因的指标或口径 ID 是什么？")
        if any(step.error == "missing_table_name" for step in result.step_results):
            questions.append("请补充目标表名后继续。")
        return list(dict.fromkeys(questions))
