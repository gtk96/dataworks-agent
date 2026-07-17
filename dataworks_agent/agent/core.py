"""Chat-oriented DataWorks Agent core."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.executor.task_executor import ExecutionResult, TaskExecutor
from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionExpiredError,
    build_interaction,
)
from dataworks_agent.agent.nlu.intent_parser import Intent, IntentParser
from dataworks_agent.agent.planner.task_planner import TaskPlan, TaskPlanner
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
        self._last_task_id: str | None = None
        self._query_frames: dict[str, tuple[float, dict[str, Any]]] = {}
        self._query_frame_ttl_seconds = 2 * 60 * 60
        self._query_frame_capacity = 128

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
        """Process user message."""
        if not message or not message.strip():
            return ChatResponse(
                message="请输入你希望 Agent 达成的业务或数据目标。我会先理解目标、拆解计划，再生成可审计的 dry-run 方案。",
                success=False,
                error="empty message",
            )

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
            if (
                answer is None
                and previous_context.get("pending_interaction")
                and not self._is_conversation_reset(incoming_message)
            ):
                pending = previous_context["pending_interaction"]
                answer = InteractionAnswer(
                    interaction_id=str(pending.get("interaction_id") or ""),
                    custom_text=incoming_message,
                    state_version=int(pending.get("state_version") or 0),
                )
            resolved_answer: dict[str, Any] = {}
            merged_context_updates = dict(context_updates or {})
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
                message = (
                    f"{objective}\n补充信息：{custom_text}"
                    if custom_text and objective and custom_text != objective
                    else custom_text or objective or incoming_message
                )
            message = await self._conversation_graph.resolve(
                message,
                conversation_id,
                context_updates=merged_context_updates,
            )
            intent = self._intent_parser.parse(message)
            intent.params = self._merge_conversation_params(
                previous_context.get("params") or {},
                intent.params,
                merged_context_updates.get("params") or {},
            )
            intent.params.setdefault("conversation_id", conversation_id)
            pending_interaction = previous_context.get("pending_interaction") or {}
            if answer is not None and pending_interaction.get("purpose"):
                intent.params["interaction_purpose"] = str(pending_interaction["purpose"])
            intent.params["goal"] = (
                intent.params.get("goal") or previous_context.get("objective") or incoming_message
            )
            if self._is_context_summary_request(incoming_message, previous_context):
                return self._build_context_summary_response(previous_context, incoming_message)
            if self._is_context_read_only_request(incoming_message, previous_context):
                return self._build_context_read_only_response(previous_context, incoming_message)

            # 处理问候意图
            if intent.action == "greeting":
                return ChatResponse(
                    message="你好！我是 DataWorks Agent，可以帮助你完成数仓建模、任务诊断、血缘分析等工作。请告诉我你想要处理什么任务。",
                    success=True,
                    data={"intent": self._intent_to_dict(intent), "agent_mode": "greeting"},
                )

            previous_action = str(previous_context.get("action") or "")
            if previous_action and (answer is not None or intent.action == "unknown"):
                intent.action = previous_action
                intent.confidence = max(intent.confidence, 0.75)
            business_query = self._resolve_business_query(message, conversation_id)
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
                workflow = await self._workflow_service.execute(
                    message=message,
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
                interaction = None
                if (
                    data.get("interaction")
                    or data.get("needs_clarification")
                    or data.get("option_chips")
                ):
                    current_context = await self._conversation_graph.context(conversation_id)
                    interaction = build_interaction(
                        {**data, "message": workflow.message},
                        purpose=self._interaction_purpose(data, intent.action),
                        state_version=int(current_context.get("state_version") or 0) + 1,
                    )
                    if interaction is not None:
                        data["interaction"] = interaction.model_dump()
                        data["needs_clarification"] = True
                response = ChatResponse(
                    message=workflow.message,
                    success=workflow.success,
                    data=data,
                    error=workflow.errors[0] if workflow.errors else None,
                )
                self._remember_business_query(conversation_id, data)
                await self._conversation_graph.remember(
                    conversation_id,
                    message,
                    needs_clarification=bool(interaction or data.get("needs_clarification")),
                    action=intent.action,
                    params=intent.params,
                    workflow_state={
                        "current_step": data.get("next_step"),
                        "missing_context": data.get("missing_context") or [],
                        "completed_steps": data.get("completed_steps") or [],
                        "result_data": self._conversation_result_snapshot(data),
                        "message": workflow.message,
                    },
                    pending_interaction=(
                        interaction.model_dump() if interaction is not None else None
                    ),
                    last_result=self._conversation_result_snapshot(data),
                )
                self._save_conversation_message(
                    conversation_id,
                    "assistant",
                    workflow.message,
                    payload={
                        "interaction": data.get("interaction"),
                        "option_chips": data.get("option_chips") or [],
                        "artifacts": data.get("artifacts") or [],
                    },
                )
                return response

            plan = self._task_planner.plan(intent)
            logger.info("Task planned: task_id=%s, steps=%d", plan.task_id, len(plan.steps))

            if not plan.steps:
                return self._build_no_plan_response(intent, plan)

            result = self._task_executor.execute(plan)
            self._last_task_id = result.task_id
            return self._build_response(intent, plan, result)
        except Exception as e:
            logger.exception("ChatAgent failed: %s", e)
            return ChatResponse(message=f"处理失败：{e}", success=False, error=str(e))

    @staticmethod
    def _is_conversation_reset(message: str) -> bool:
        text = message.lower()
        return any(marker in text for marker in ("??", "????", "???", "cancel", "reset"))

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

    def _resolve_business_query(
        self, message: str, conversation_id: str | None
    ) -> dict[str, Any] | None:
        direct = self._workflow_service.understand_business_query(message)
        if direct is not None:
            return direct
        if not conversation_id:
            return None
        self._prune_query_frames()
        previous = self._query_frames.get(conversation_id)
        if previous is None:
            return None
        return self._workflow_service.refine_business_query(message, previous[1])

    def _remember_business_query(self, conversation_id: str | None, data: dict[str, Any]) -> None:
        if not conversation_id:
            return
        semantic_plan = data.get("semantic_plan") or {}
        query_frame = semantic_plan.get("business_query")
        if not isinstance(query_frame, dict) or not query_frame.get("metric_id"):
            return
        self._query_frames[conversation_id] = (time.monotonic(), dict(query_frame))
        self._prune_query_frames()

    def _prune_query_frames(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (created_at, _) in self._query_frames.items()
            if now - created_at > self._query_frame_ttl_seconds
        ]
        for key in expired:
            self._query_frames.pop(key, None)
        overflow = len(self._query_frames) - self._query_frame_capacity
        if overflow > 0:
            oldest = sorted(self._query_frames, key=lambda key: self._query_frames[key][0])
            for key in oldest[:overflow]:
                self._query_frames.pop(key, None)

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
