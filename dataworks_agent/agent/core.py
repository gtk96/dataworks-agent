"""Chat-oriented DataWorks Agent core."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.executor.task_executor import ExecutionResult, TaskExecutor
from dataworks_agent.agent.nlu.intent_parser import Intent, IntentParser
from dataworks_agent.agent.planner.task_planner import TaskPlan, TaskPlanner
from dataworks_agent.agent.workflow_service import AgentWorkflowService

logger = logging.getLogger(__name__)


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
    ) -> ChatResponse:
        """Process user message."""
        if not message or not message.strip():
            return ChatResponse(
                message="请输入你希望 Agent 达成的业务或数据目标。我会先理解目标、拆解计划，再生成可审计的 dry-run 方案。",
                success=False,
                error="empty message",
            )

        try:
            intent = self._intent_parser.parse(message)
            if request_type and request_type != "auto":
                intent.action = request_type
            logger.info("NLU parsed: action=%s, confidence=%.2f", intent.action, intent.confidence)

            workflow_actions = {
                "agent_workflow",
                "ods_dwd_modeling",
                "forward_modeling",
                "reverse_modeling",
                "diagnose_issue",
                "cookie_manage",
                "ask_data",
            }
            if intent.action in workflow_actions and execution_mode is not None:
                workflow = await self._workflow_service.execute(
                    message=message,
                    action=intent.action,
                    params=intent.params,
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
                            "approval_required"
                            if data.get("publish_request")
                            else "executed"
                            if workflow.mode == "dev_execute" and workflow.success
                            else "blocked"
                            if not workflow.success
                            else "proposal"
                        ),
                    }
                )
                return ChatResponse(
                    message=workflow.message,
                    success=workflow.success,
                    data=data,
                    error=workflow.errors[0] if workflow.errors else None,
                )

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
            success=True,
            data={
                "intent": self._intent_to_dict(intent),
                "plan": plan.to_dict(),
                "clarifying_questions": questions,
                "next_actions": questions,
                "agent_mode": "needs_context",
            },
            error=None,
        )

    def _build_response(self, intent: Intent, plan: TaskPlan, result: ExecutionResult) -> ChatResponse:
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
            lines.append("已到真实写入/发布边界：后续必须进入 Publish Gate 审批，不会直接操作线上 DataWorks。")
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
            is_existing_ods = isinstance(source_table, str) and source_table.lower().startswith("ods_")
            if not params.get("dwd_table") and not params.get("table_name"):
                questions.append("DWD \u76ee\u6807\u8868\u540d\u662f\u4ec0\u4e48\uff1f\u4f8b\u5982 dwd_trade_order_detail\u3002")
            if not source_table and not ods_table and not params.get("oss_path"):
                questions.append("\u6e90\u8868\u3001OSS \u8def\u5f84\u6216\u5df2\u6709 ODS \u8868\u662f\u4ec0\u4e48\uff1f\u4f8b\u5982 orders / oss://bucket/path/orders.csv / ods_order\u3002")
            if not source_type and not ods_table and not is_existing_ods:
                questions.append("ODS \u6765\u6e90\u7c7b\u578b\u662f\u4ec0\u4e48\uff1f\u53ef\u9009 mysql\u3001hologres\u3001oss\u3001realtime \u6216\u5df2\u6709 ODS\u3002")
            if source_type in {"mysql", "polardb", "postgres", "oracle", "sqlserver", "hologres", "realtime"} and not params.get("datasource_name"):
                questions.append("DataWorks \u6570\u636e\u6e90\u540d\u79f0\u662f\u4ec0\u4e48\uff1f\u4f8b\u5982 jky_singleshop \u6216 dataworks_holo\u3002")
            for step in result.step_results:
                missing = (step.data or {}).get("missing_context", [])
                if isinstance(missing, list) and missing:
                    questions.append("\u8bf7\u8865\u9f50\u7f3a\u5931\u4e0a\u4e0b\u6587\uff1a" + "\u3001".join(str(item) for item in missing) + "\u3002")
        if intent.action in {"metric_attribution"} and not params.get("metric_id"):
            questions.append("需要归因的指标或口径 ID 是什么？")
        if any(step.error == "missing_table_name" for step in result.step_results):
            questions.append("请补充目标表名后继续。")
        return list(dict.fromkeys(questions))
