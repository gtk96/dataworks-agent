"""一句话 DataWorks Agent 的真实执行工作流。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from importlib.metadata import version
from typing import Any, Literal

import sqlglot
from sqlglot import exp

from dataworks_agent.agent.context import (
    HistoryProvider,
    MetadataProvider,
    MetadataQueryResult,
)
from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.agent.nlu.templates import BUSINESS_QUERY_PATTERNS
from dataworks_agent.agent.outcome_verifier import WorkflowOutcomeVerifier
from dataworks_agent.config import settings
from dataworks_agent.governance.closed_loop_verifier import (
    ClosedLoopVerifier,
    VerificationStatus,
)
from dataworks_agent.naming import generate_node_path, generate_ods_di_table_name
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    DWD_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    generate_cron,
)
from dataworks_agent.runtime.shims import (
    ConfirmRequest,
    Evaluator,
    IntentConfirmGate,
    LoopDecision,
    LoopKernel,
    LoopPolicy,
    MemoryEntry,
    MemoryLayeringService,
    MemoryType,
    ReflectionEngine,
    ReflectionResult,
    RepairResult,
    StopReason,
)
from dataworks_agent.schemas import assert_safe_table_name
from dataworks_agent.semantic.album_context import DataAlbumContextResolver
from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase
from dataworks_agent.semantic.query_planner import MetricQueryPlan, MetricQueryPlanner
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)

ExecutionMode = Literal["plan", "dev_execute"]
_MODELING_ACTIONS = {"agent_workflow", "ods_dwd_modeling", "forward_modeling", "any_ods_modeling"}
_FINAL_STATUSES = {"completed", "failed", "cancelled"}
_WRITE_WORDS = ("创建", "新建", "建好", "执行", "初始化", "生成任务", "落地", "部署开发")
_CJK_RE = re.compile(r"[一-鿿]+")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ASK_DOMAIN_ALBUM_HINTS: dict[str, int] = {
    # Curated DataMap album ids that are explicitly tagged for the request.
    # Order matters: earlier (more specific) hint wins on tie.
    "订单": 436,        # 订单数据（ods 层）订单
    "订单信息": 436,
    "订单明细": 436,
    "客户订单": 436,
    "用户订单": 436,
    "订单模型": 328,    # 模型汇总
    "订单汇总": 328,
    "订单汇总模型": 328,
}


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _today_partition_value() -> str:
    """Return yesterday's date in yyyymmdd (max-safe default sample)."""
    from datetime import datetime, timedelta

    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")


class QueryNeedsClarificationError(ValueError):
    """The question is valid, but no deterministic metric definition is available."""

    def __init__(
        self,
        question: str,
        album_contexts: list[Any],
        reason: str = "",
        *,
        knowledge_matches: list[dict[str, Any]] | None = None,
        clarifying_questions: list[str] | None = None,
        missing_contract_fields: list[str] | None = None,
        option_chips: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(question)
        self.question = question
        self.album_contexts = album_contexts
        self.reason = reason
        self.knowledge_matches = knowledge_matches or []
        self.clarifying_questions = clarifying_questions or []
        self.missing_contract_fields = missing_contract_fields or []
        self.option_chips = option_chips or []


@dataclass
class WorkflowResult:
    success: bool
    message: str
    workflow_type: str
    mode: ExecutionMode
    steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        return {
            "workflow_type": self.workflow_type,
            "execution_mode": self.mode,
            "steps": self.steps,
            "artifacts": self.artifacts,
            "errors": self.errors,
            **self.data,
        }


class AgentWorkflowService:
    """把会话意图路由到项目中已有的真实 AK/SK、Cookie 与 MCP 能力。"""

    def __init__(self) -> None:
        self._extractor = EntityExtractor()
        self._closed_loop_verifier = ClosedLoopVerifier()
        self._album_context_resolver = DataAlbumContextResolver()
        self._knowledge_base = SemanticKnowledgeBase()
        self._metric_query_planner = MetricQueryPlanner(knowledge_base=self._knowledge_base)
        self._outcome_verifier = WorkflowOutcomeVerifier()
        self._evaluator = Evaluator()
        self._reflection_engine = ReflectionEngine()
        self._intent_confirm_gate = IntentConfirmGate()
        self._memory_layering = MemoryLayeringService()
        self._metadata_provider = MetadataProvider()
        self._history_provider = HistoryProvider()

    def infer_mode(self, message: str, requested: str, action: str = "") -> ExecutionMode:
        if requested == "plan":
            return "plan"
        if requested == "dev_execute":
            return "dev_execute"
        if any(word in message for word in ("先规划", "只规划", "不要执行")):
            return "plan"
        if action in {"ask_data", "reverse_modeling", "diagnose_issue", "cookie_manage"}:
            return "dev_execute"
        if action in _MODELING_ACTIONS:
            return "dev_execute"
        return "dev_execute" if any(word in message for word in _WRITE_WORDS) else "plan"

    async def execute(
        self,
        *,
        message: str,
        action: str,
        params: dict[str, Any],
        execution_mode: str = "auto",
        initialize_data: bool = True,
        publish: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> WorkflowResult:
        routed = self._route_action(message, action)
        mode = self.infer_mode(message, execution_mode, routed)
        policy = self._loop_policy(routed, mode)
        kernel: LoopKernel[WorkflowResult] = LoopKernel(policy)
        event_log, event_run_id = self._start_loop_event_log(client_ip, routed)

        async def run_once(state: dict[str, Any], iteration: int) -> WorkflowResult:
            return await self._execute_once(
                routed=routed,
                message=message,
                params=params,
                mode=mode,
                initialize_data=initialize_data,
                publish=publish,
                client_ip=client_ip,
            )

        def verify(result: WorkflowResult, iteration: int) -> LoopDecision:
            return self._outcome_verifier.verify(
                result,
                workflow_type=routed,
                mode=mode,
                objective=message,
                publish_requested=publish,
            )

        async def repair(
            state: dict[str, Any],
            result: WorkflowResult,
            decision: LoopDecision,
            iteration: int,
        ) -> RepairResult:
            return await self._repair_loop(result, decision, iteration, message)

        outcome = await kernel.run(
            objective=message,
            action=run_once,
            verify=verify,
            repair=repair,
            initial_state={"workflow_type": routed, "mode": mode},
            observer=self._loop_observer(event_log, event_run_id),
            run_id=event_run_id or None,
        )
        result = outcome.result
        self._attach_loop_evaluation(result, outcome.to_dict(), routed)
        if not outcome.success and outcome.stop_reason not in {
            StopReason.NEEDS_CONTEXT,
            StopReason.APPROVAL_REQUIRED,
        }:
            result.success = False
            contract_error = f"Loop 验收停止：{outcome.stop_reason.value}"
            if contract_error not in result.errors:
                result.errors.append(contract_error)
            if result.message and "不会标记为完成" not in result.message:
                result.message += " 结果未通过统一 Loop 验收，不会标记为完成。"
        elif outcome.stop_reason == StopReason.APPROVAL_REQUIRED and not result.success:
            # Intent confirmation: 对于破坏性操作，拦截并请求用户确认
            confirm_req = await self._handle_intent_confirmation(
                outcome=outcome,
                message=message,
                routed=routed,
            )
            if confirm_req:
                result.data["confirm_request"] = confirm_req.to_dict()
                result.message = (
                    f"⚠️ 意图确认: {confirm_req.description}\n"
                    f"请求 ID: {confirm_req.request_id}\n"
                    f"请在 {int(confirm_req.ttl_seconds)} 秒内回复确认或拒绝。"
                )
        self._finish_loop_event_log(event_log, event_run_id, outcome.success)
        return result

    async def _execute_once(
        self,
        *,
        routed: str,
        message: str,
        params: dict[str, Any],
        mode: ExecutionMode,
        initialize_data: bool,
        publish: bool,
        client_ip: str,
    ) -> WorkflowResult:
        if routed == "cookie_manage":
            return await self._manage_cookie(message, mode)
        if routed == "ask_data":
            return await self._ask_data(message, mode, params)
        if routed == "reverse_modeling":
            return await self._reverse_model(message, params, mode)
        if routed == "diagnose_issue":
            return await self._diagnose(message, params, mode)
        return await self._forward_model(
            message,
            params,
            mode,
            initialize_data=initialize_data,
            publish=publish,
            client_ip=client_ip,
        )

    @staticmethod
    def _loop_policy(workflow_type: str, mode: ExecutionMode) -> LoopPolicy:
        if mode == "plan":
            return LoopPolicy(max_iterations=1, max_same_action=1, deadline_seconds=180)
        if workflow_type in ("forward_modeling", "any_ods_modeling"):
            return LoopPolicy(
                max_iterations=2,
                max_same_action=2,
                max_no_progress_rounds=1,
                deadline_seconds=900,
            )
        if workflow_type == "ask_data":
            return LoopPolicy(
                max_iterations=3,
                max_same_action=3,
                max_no_progress_rounds=2,
                deadline_seconds=max(180, settings.ask_data_timeout_seconds * 2),
            )
        return LoopPolicy(
            max_iterations=3,
            max_same_action=2,
            max_no_progress_rounds=1,
            deadline_seconds=max(180, settings.ask_data_timeout_seconds * 2),
        )

    async def _repair_loop(
        self,
        result: WorkflowResult,
        decision: LoopDecision,
        iteration: int,
        objective: str = "",
    ) -> RepairResult:
        # 1. 确定性修复（已有逻辑）
        if decision.failure_class == "authentication":
            bff = getattr(app_state, "_bff_client", None)
            if bff is None:
                return RepairResult(False, "refresh_cookie", "Cookie/BFF 客户端不可用。")
            outcome = await self._refresh_cookie_auth(bff)
            status = str(outcome.get("status") or "")
            applied = status in {"success", "refreshed", "healthy"}
            return RepairResult(
                applied,
                "refresh_cookie_from_9222",
                str(outcome.get("detail") or status or "Cookie 刷新完成"),
                {"cookie_refresh": outcome},
            )
        if decision.failure_class == "transient":
            delay = min(0.25 * (2 ** max(iteration - 1, 0)), 1.0)
            await asyncio.sleep(delay)
            return RepairResult(
                True,
                "bounded_retry",
                f"瞬时错误退避 {delay:.2f}s 后重试。",
                {"retry_delay_seconds": delay},
            )
        if decision.failure_class == "freshness_lag":
            delay = min(2.0 * (2 ** max(iteration - 1, 0)), 4.0)
            await asyncio.sleep(delay)
            return RepairResult(
                True,
                "wait_for_metric_refresh",
                "DWS/DWD reconciliation has a short refresh lag; retry after waiting.",
                {"retry_delay_seconds": delay},
            )

        # 2. Reflection 修复（Harness Reflection 支柱）
        # 当确定性修复无法处理时，启动 LLM 反思分析
        reflection = await self._reflection_engine.reflect(
            run_id=decision.evidence.get("run_id", f"iter_{iteration}"),
            iteration=iteration,
            objective=objective or result.message or "unknown",
            action_taken=result.workflow_type or "unknown",
            verification_result={
                "checks": [
                    {
                        "check_name": "loop_decision",
                        "passed": decision.passed,
                        "severity": "error" if not decision.passed else "info",
                        "message": decision.summary,
                    }
                ],
                "score": decision.score,
                "failure_class": decision.failure_class,
            },
            previous_reflections=self._reflection_engine.get_reflection_history(
                run_id=decision.evidence.get("run_id", ""),
            ),
        )

        # 3. 存储到 Episodic 记忆层
        self.store_episodic_memory(
            content={
                "category": reflection.category,
                "root_cause": reflection.root_cause,
                "score": decision.score,
                "adjustment": reflection.strategy_adjustment,
            },
            tags=["reflection", reflection.category],
            source="loop_repair",
        )

        # 4. 基于反思结果生成修复策略
        repair_result = self._repair_from_reflection(reflection, decision, iteration)
        if repair_result.applied:
            return repair_result

        # 4. 最终回退：无法修复
        return RepairResult(False, "", "没有安全、确定性的自动修复动作。")

    @staticmethod
    def _start_loop_event_log(client_ip: str, workflow_type: str) -> tuple[Any | None, str]:
        try:
            from dataworks_agent.eventlog.store import EventLog

            event_log = EventLog()
            run_id = event_log.create_run(
                f"agent:{client_ip}",
                channel="agent_loop",
                created_by_ip=client_ip,
                status="running",
            )
            event_log.append(
                run_id=run_id,
                session_id=f"agent:{client_ip}",
                event_type="loop_started",
                payload={"workflow_type": workflow_type},
            )
            return event_log, run_id
        except Exception as exc:
            logger.warning("Loop EventLog 初始化失败，继续执行主链路: %s", exc)
            return None, ""

    async def _repair_from_reflection(
        self,
        reflection: ReflectionResult,
        decision: LoopDecision,
        iteration: int,
    ) -> RepairResult:
        """基于 LLM 反思结果生成修复策略。

        参考 Harness Reflection 支柱：
        - 确定性验证失败后，LLM 分析偏差根因
        - 生成可执行的策略调整建议
        - 避免盲目重试，改为有方向的修正
        """
        category = reflection.category
        adjustment = reflection.strategy_adjustment

        # 根据反思类别生成对应的修复动作
        if category == "insufficient_context":
            return RepairResult(
                True,
                "reflect_insufficient_context",
                f"上下文不足: {adjustment}",
                {"reflection": reflection.to_dict(), "needs_clarification": True},
            )
        elif category == "wrong_tool":
            return RepairResult(
                True,
                "reflect_wrong_tool",
                f"工具不当: {adjustment}",
                {"reflection": reflection.to_dict(), "retry_with_alternative": True},
            )
        elif category == "constraint_violation":
            return RepairResult(
                False,
                "reflect_constraint_violation",
                f"红线违反: {adjustment} — 已阻断，需人工介入",
                {"reflection": reflection.to_dict(), "blocked": True},
            )
        elif category == "strategy_flaw":
            # 策略缺陷：调整参数后重试
            delay = min(0.5 * (2 ** max(iteration - 1, 0)), 2.0)
            return RepairResult(
                True,
                "reflect_strategy_retry",
                f"策略调整: {adjustment}，{delay:.1f}s 后重试",
                {"reflection": reflection.to_dict(), "retry_delay_seconds": delay},
            )
        elif category == "incorrect_input":
            return RepairResult(
                True,
                "reflect_input_correction",
                f"输入修正: {adjustment}",
                {"reflection": reflection.to_dict(), "reparse_input": True},
            )

        # 未知类别：不盲目重试
        return RepairResult(
            False,
            "reflect_unknown",
            f"未知偏差类别: {category} — {adjustment}",
            {"reflection": reflection.to_dict(), "manual_intervention": True},
        )

    async def _llm_reflect(self, prompt: str) -> str:
        """LLM 反思回调 — 实际使用时注入 LLM 客户端。

        当前为 stub，返回确定性回退结果。
        子类或外部注入可覆盖此方法。
        """
        # TODO: 注入实际 LLM 调用
        # from dataworks_agent.config import settings
        # client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        # response = client.chat.completions.create(...)
        # return response.choices[0].message.content
        return "{}"

    async def _handle_intent_confirmation(
        self,
        *,
        outcome: Any,
        message: str,
        routed: str,
    ) -> ConfirmRequest | None:
        """处理意图确认：当 Loop 因 APPROVAL_REQUIRED 停止时拦截。

        核心逻辑：
        1. 判断操作是否属于高风险（DROP/DELETE/PUBLISH/DEPLOY）
        2. 如果是，生成确认请求并返回给用户
        3. 如果用户已确认，继续执行；否则阻断
        """
        # 提取操作信息
        result_data = outcome.get("result", {}) if isinstance(outcome, dict) else {}

        # 从结果中提取操作类型
        action = self._extract_action_type(result_data, routed)
        target = self._extract_action_target(result_data, message)

        if action and IntentConfirmGate().needs_confirmation(action):
            gate = self._intent_confirm_gate
            description = f"操作类型: {action}, 目标: {target}"
            risk = "critical" if action in ("drop_table", "delete_node") else "high"

            confirm_req = await gate.request_confirmation(
                action=action,
                target=target or "unknown",
                description=description,
                risk_level=risk,
                payload={"routed": routed, "message": message},
            )
            return confirm_req

        return None

    @staticmethod
    def _extract_action_type(result_data: dict, routed: str) -> str | None:
        """从结果数据中提取操作类型。"""
        # 优先从 result_data 中读取
        action = result_data.get("action_type") or result_data.get("change_type")
        if action:
            return action

        # 根据 routed 类型推断
        type_map = {
            "drop_table": "drop_table",
            "delete_node": "delete_node",
            "publish": "publish",
            "deploy": "deploy",
            "execute_ddl": "execute_ddl",
        }
        return type_map.get(routed)

    @staticmethod
    def _extract_action_target(result_data: dict, message: str) -> str:
        """从结果数据或消息中提取操作目标。"""
        target = result_data.get("target") or result_data.get("table_name") or result_data.get("node_name")
        if target:
            return target
        # 从消息中提取表名/节点名
        if "table" in message.lower() or "表" in message:
            return message[:50]
        return "unknown"

    def store_episodic_memory(self, content: dict[str, Any], tags: list[str] | None = None, source: str = "") -> MemoryEntry:
        """存储 Episodic 记忆（对话轨迹、执行记录）。"""
        import uuid
        entry = MemoryEntry(
            entry_id=f"ep_{uuid.uuid4().hex[:12]}",
            memory_type=MemoryType.EPISODIC,
            content=content,
            tags=tags or [],
            source=source,
        )
        return self._memory_layering.store(entry)

    def store_semantic_memory(self, content: dict[str, Any], tags: list[str] | None = None, source: str = "") -> MemoryEntry:
        """存储 Semantic 记忆（领域知识、规则）。"""
        import uuid
        entry = MemoryEntry(
            entry_id=f"sm_{uuid.uuid4().hex[:12]}",
            memory_type=MemoryType.SEMANTIC,
            content=content,
            tags=tags or [],
            source=source,
        )
        return self._memory_layering.store(entry)

    def store_procedural_memory(self, content: dict[str, Any], tags: list[str] | None = None, source: str = "") -> MemoryEntry:
        """存储 Procedural 记忆（工作流模式、修复策略）。"""
        import uuid
        entry = MemoryEntry(
            entry_id=f"pr_{uuid.uuid4().hex[:12]}",
            memory_type=MemoryType.PROCEDURAL,
            content=content,
            tags=tags or [],
            source=source,
        )
        return self._memory_layering.store(entry)

    @staticmethod
    def _loop_observer(event_log: Any | None, run_id: str):
        if event_log is None or not run_id:
            return None

        def observe(event: str, payload: dict[str, Any]) -> None:
            try:
                event_log.append(
                    run_id=run_id,
                    session_id=str(event_log.get_run(run_id).session_id),
                    event_type=event,
                    payload=payload,
                )
                if event == "iteration_verified":
                    event_log.save_checkpoint(
                        run_id,
                        step_seq=int(payload.get("iteration", 0)),
                        state=payload,
                    )
            except Exception as exc:
                logger.warning("Loop EventLog 写入失败，继续执行主链路: %s", exc)

        return observe

    @staticmethod
    def _finish_loop_event_log(event_log: Any | None, run_id: str, success: bool) -> None:
        if event_log is None or not run_id:
            return
        try:
            event_log.update_run(run_id, status="completed" if success else "failed")
        except Exception as exc:
            logger.warning("Loop EventLog 完成状态写入失败: %s", exc)

    def _attach_loop_evaluation(
        self,
        result: WorkflowResult,
        loop_data: dict[str, Any],
        workflow_type: str,
    ) -> None:
        # Never attach raw iteration objects to the chat payload — SSE/JSON must stay plain.
        safe_loop = {
            "run_id": loop_data.get("run_id"),
            "objective": loop_data.get("objective"),
            "success": loop_data.get("success"),
            "stop_reason": loop_data.get("stop_reason"),
            "iteration_count": loop_data.get("iteration_count"),
            "best_score": loop_data.get("best_score"),
            "elapsed_ms": loop_data.get("elapsed_ms"),
            "runtime": loop_data.get("runtime"),
        }
        result.data["loop"] = safe_loop
        iterations = int(loop_data.get("iteration_count") or 0)
        success = bool(loop_data.get("success"))
        self._evaluator.record_metric("loop_verified_success", 1.0 if success else 0.0, "ratio")
        self._evaluator.record_metric("loop_iterations", float(iterations), "count")
        if not success and loop_data.get("stop_reason") not in {
            StopReason.NEEDS_CONTEXT.value,
            StopReason.APPROVAL_REQUIRED.value,
        }:
            self._evaluator.record_badcase(
                input_data={
                    "workflow_type": workflow_type,
                    "objective": loop_data.get("objective"),
                },
                output_data={"loop": safe_loop, "errors": result.errors},
                failure_reason=str(loop_data.get("stop_reason") or "verification_failed"),
                run_id=str(loop_data.get("run_id") or ""),
                category=f"{workflow_type}_loop",
            )
        result.data["evaluation"] = {
            "verified_success": success,
            "false_success_prevented": bool(result.success and not success),
            "iteration_count": iterations,
            "stop_reason": loop_data.get("stop_reason"),
        }

    @staticmethod
    def _route_action(message: str, action: str) -> str:
        lower = message.lower()
        if action == "cookie_manage" or "cookie" in lower or "9222" in lower or "登录态" in message:
            return "cookie_manage"
        business_query = any(
            re.search(pattern, message, re.I) for pattern in BUSINESS_QUERY_PATTERNS
        )
        if (
            action == "ask_data"
            or business_query
            or any(k in message for k in ("问数", "查数", "多少条", "前几条"))
        ):
            return "ask_data"
        return action

    def capability_status(self) -> dict[str, Any]:
        official = getattr(app_state, "_official_mcp_client", None)
        cookie_bff = getattr(app_state, "_bff_client", None) is not None
        cdp_9222 = getattr(app_state, "_cdp_client", None) is not None
        raw_cookie_health = app_state.cookie_health
        cookie_health = raw_cookie_health
        if raw_cookie_health in {"expired", "critical"} and (cookie_bff or cdp_9222):
            cookie_health = "degraded"
        return {
            "agent_runtime": {
                "framework": "LangGraph",
                "version": version("langgraph"),
                "ready": True,
                "checkpoint": "langgraph.memory",
            },
            "ak_sk": bool(settings.aliyun_access_key_id and settings.aliyun_access_key_secret),
            "openapi": getattr(app_state, "_openapi_client", None) is not None,
            "maxcompute": getattr(app_state, "_maxcompute_client", None) is not None,
            "node_adapter": getattr(app_state, "_node_client", None) is not None,
            "cookie_bff": cookie_bff,
            "cdp_9222": cdp_9222,
            "cookie_health": cookie_health,
            "cookie_mcp_health": raw_cookie_health,
            "official_mcp": official.status.to_dict()
            if official
            else {"enabled": False, "connected": False},
            # Native Cookie/BFF table search + IDA query (inspired by data-mcp tools)
            "table_search": cookie_bff,
            "ida_query": cookie_bff,
        }

    async def _manage_cookie(self, message: str, mode: ExecutionMode) -> WorkflowResult:
        status = self.capability_status()
        official = status["official_mcp"]
        steps = [
            {"step": "check_ak_sk", "status": "completed" if status["ak_sk"] else "failed"},
            {
                "step": "check_official_mcp",
                "status": "completed" if official.get("connected") else "warning",
            },
            {
                "step": "check_cookie_bff",
                "status": "completed" if status["cookie_bff"] else "warning",
            },
            {"step": "check_cdp_9222", "status": "completed" if status["cdp_9222"] else "warning"},
        ]
        if mode == "plan" or not any(
            k in message for k in ("提取", "刷新", "同步", "更新", "获取")
        ):
            degraded = status["cookie_health"] == "degraded"
            message_text = (
                "已检查执行底座：旧 Cookie MCP 登录态异常，但 BFF/CDP 兜底仍可用，当前为部分降级。"
                if degraded
                else "已检查 AK/SK、9222 调试浏览器、Cookie 兜底和官方 MCP 通道。"
            )
            return WorkflowResult(
                True,
                message_text,
                "cookie_manage",
                mode,
                steps=steps,
                data={"capabilities": status},
            )
        from dataworks_agent.cookie.background_refresh import cdp_extract_and_apply

        result = await cdp_extract_and_apply()
        ok = result.get("status") == "success"
        return WorkflowResult(
            ok,
            "已从 9222 登录浏览器提取并同步 Cookie。"
            if ok
            else f"Cookie 更新未完成：{result.get('detail', '未知错误')}",
            "cookie_manage",
            mode,
            steps=[{"step": "cookie_refresh", **result}],
            data={"capabilities": self.capability_status()},
            errors=[] if ok else [str(result.get("detail", "cookie refresh failed"))],
        )

    async def _official_call(
        self, tool: str, arguments: dict[str, Any]
    ) -> tuple[Any | None, str | None]:
        client = getattr(app_state, "_official_mcp_client", None)
        if client is None:
            return None, "官方 DataWorks MCP 客户端未启用"
        try:
            result = await asyncio.wait_for(client.call_tool(tool, arguments), timeout=30)
            if isinstance(result, dict) and result.get("is_error"):
                raise RuntimeError(str(result.get("content") or result))
            return result, None
        except Exception as exc:
            logger.warning("官方 DataWorks MCP %s 调用失败，准备降级: %s", tool, exc)
            return None, str(exc)

    @staticmethod
    def _find_nested_key(value: Any, key: str) -> Any:
        if isinstance(value, dict):
            for current_key, current_value in value.items():
                if str(current_key).lower() == key.lower():
                    return current_value
            for current_value in value.values():
                found = AgentWorkflowService._find_nested_key(current_value, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = AgentWorkflowService._find_nested_key(item, key)
                if found is not None:
                    return found
        return None

    @classmethod
    def _node_from_payload(cls, payload: Any) -> dict[str, Any]:
        node = cls._find_nested_key(payload, "Node")
        if isinstance(node, dict):
            return node
        if isinstance(payload, dict) and any(
            key in payload for key in ("Spec", "spec", "Id", "id")
        ):
            return payload
        return {}

    @classmethod
    def _dependencies_from_payload(cls, payload: Any) -> list[Any]:
        paging = cls._find_nested_key(payload, "PagingInfo")
        if isinstance(paging, dict):
            nodes = cls._find_nested_key(paging, "Nodes")
            if isinstance(nodes, list):
                return nodes
        nodes = cls._find_nested_key(payload, "Nodes")
        return nodes if isinstance(nodes, list) else []

    async def _read_node_metadata(
        self, node_id: str
    ) -> tuple[dict[str, Any], list[Any], dict[str, str], list[str]]:
        sources = {"official_mcp": "not_available", "openapi": "not_used"}
        warnings: list[str] = []
        node: dict[str, Any] = {}
        dependencies: list[Any] = []
        project_id = settings.dataworks_project_id

        node_arguments: dict[str, Any] = {"Id": node_id}
        if project_id:
            node_arguments["ProjectId"] = project_id
        mcp_node, node_error = await self._official_call("GetNode", node_arguments)
        if mcp_node is not None:
            node = self._node_from_payload(mcp_node)
        if project_id:
            mcp_dependencies, dependency_error = await self._official_call(
                "ListNodeDependencies",
                {"ProjectId": project_id, "Id": node_id, "PageSize": 100, "PageNumber": 1},
            )
        else:
            mcp_dependencies, dependency_error = (
                None,
                "缺少 DATAWORKS_PROJECT_ID，节点依赖已转 OpenAPI 兜底",
            )
        if mcp_dependencies is not None:
            dependencies = self._dependencies_from_payload(mcp_dependencies)
        if node:
            sources["official_mcp"] = "completed"
            if dependency_error:
                sources["official_mcp"] = "warning"
                warnings.append(dependency_error)
        else:
            sources["official_mcp"] = "warning"
            if node_error:
                warnings.append(node_error)

        api = getattr(app_state, "_openapi_client", None)
        if (not node or not dependencies) and api is not None:
            from dataworks_agent.api_clients.openapi_node_adapter import _to_map

            sources["openapi"] = "fallback"
            if not node:
                try:
                    node = _to_map(await api.get_node(node_id)).get("Node") or {}
                except Exception as exc:
                    warnings.append(str(exc))
            if not dependencies:
                try:
                    dependency_body = _to_map(await api.list_node_dependencies(node_id))
                    dependencies = (dependency_body.get("PagingInfo") or {}).get("Nodes") or []
                except Exception as exc:
                    warnings.append(str(exc))
        elif node:
            sources["openapi"] = "not_needed"
        return node, dependencies, sources, list(dict.fromkeys(warnings))

    async def _reverse_table_via_cookie(
        self, table: str, table_name: str, mode: ExecutionMode
    ) -> WorkflowResult | None:
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return None
        project = (
            table.rsplit(".", 1)[0]
            if "." in table
            else (settings.maxcompute_project or settings.dataworks_dev_schema)
        )
        table_guid = f"odps.{project}.{table_name}"
        try:
            ddl = await bff.get_creation_ddl(table_guid)
        except Exception as exc:
            if not self._is_cookie_auth_error(exc):
                logger.warning("Cookie BFF 读取表 DDL 失败: %s", exc)
                return None
            refresh = await self._refresh_cookie_auth(bff)
            if refresh.get("status") not in {"success", "refreshed", "extracted_unverified"}:
                return None
            try:
                ddl = await bff.get_creation_ddl(table_guid)
            except Exception as retry_exc:
                logger.warning("Cookie BFF 刷新后读取表 DDL 仍失败: %s", retry_exc)
                return None
        if not ddl:
            return None

        from dataworks_agent.governance.sql_lineage import parse_ddl_structure

        parsed = parse_ddl_structure(ddl)
        columns = parsed.get("columns") or []
        partitions = parsed.get("partitions") or []
        metadata = self._infer_reverse_metadata(table_name, columns)
        try:
            lineage = await bff.list_lineage(table_guid)
        except Exception as exc:
            lineage = {"warning": self._brief_error(exc)}
        return WorkflowResult(
            True,
            f"已通过 Cookie 元数据通道完成 {table} 的逆向建模；AK/SK 无表结构权限不会阻断该能力。",
            "reverse_modeling",
            mode,
            steps=[
                {"step": "read_cookie_table_ddl", "status": "completed"},
                {
                    "step": "parse_table_ddl",
                    "status": "completed" if parsed.get("parse_state") == "ok" else "warning",
                },
                {"step": "infer_semantic_candidates", "status": "completed"},
                {
                    "step": "read_cookie_lineage",
                    "status": "warning"
                    if isinstance(lineage, dict) and "warning" in lineage
                    else "completed",
                },
            ],
            artifacts=[
                {"type": "table_ddl", "name": table, "content": ddl},
                {
                    "type": "semantic_candidates",
                    "name": table,
                    "content": metadata["semantic_candidates"],
                },
            ],
            data={
                "source_type": "table",
                "metadata_channel": "cookie_bff",
                "table": table,
                "columns": columns,
                "partitions": partitions,
                "ddl": ddl,
                "lineage": lineage,
                **metadata,
            },
        )

    async def _reverse_model(
        self, message: str, params: dict[str, Any], mode: ExecutionMode
    ) -> WorkflowResult:
        table = (
            params.get("table_name")
            or params.get("source_table")
            or self._extractor.extract_table_name(message)
        )
        explicit_node = params.get("node_id")
        node_match = re.search(r"(?:节点|node)\s*[:：]?\s*([A-Za-z0-9_-]+)", message, re.I)
        node_id = str(explicit_node or (node_match.group(1) if node_match else ""))
        mc = getattr(app_state, "_maxcompute_client", None)

        if node_id:
            body, dependencies, metadata_sources, warnings = await self._read_node_metadata(node_id)
            if not body:
                return WorkflowResult(
                    False,
                    f"无法读取节点 {node_id}；官方 MCP 与 OpenAPI 均未返回节点信息。",
                    "reverse_modeling",
                    mode,
                    steps=[{"step": "read_node_flowspec", "status": "failed"}],
                    data={"metadata_sources": metadata_sources},
                    errors=warnings or ["node metadata unavailable"],
                )
            spec_value = body.get("Spec") or body.get("spec") or "{}"
            spec = json.loads(spec_value) if isinstance(spec_value, str) else spec_value
            nodes = (spec.get("spec") or {}).get("nodes") or []
            script = (nodes[0].get("script") if nodes else {}) or {}
            sql = script.get("content", "")
            upstream_tables = self._extract_sql_sources(sql) if sql else []
            return WorkflowResult(
                True,
                f"已逆向读取节点 {node_id} 的 FlowSpec、SQL 与节点级依赖。",
                "reverse_modeling",
                mode,
                steps=[
                    {"step": "read_node_flowspec", "status": "completed"},
                    {"step": "parse_node_sql", "status": "completed"},
                    {
                        "step": "read_node_dependencies",
                        "status": "completed" if dependencies else "warning",
                    },
                ],
                artifacts=[{"type": "node_sql", "name": node_id, "content": sql}],
                data={
                    "source_type": "node",
                    "node": body,
                    "flowspec": spec,
                    "dependencies": dependencies,
                    "upstream_tables": upstream_tables,
                    "metadata_sources": metadata_sources,
                },
                errors=warnings,
            )

        if not table:
            return WorkflowResult(
                False,
                "请在一句话中给出要逆向的表名或节点 ID。",
                "reverse_modeling",
                mode,
                errors=["missing table or node"],
            )
        table_name = table.split(".")[-1]
        assert_safe_table_name(table_name)
        if mc is None:
            cookie_result = await self._reverse_table_via_cookie(table, table_name, mode)
            if cookie_result is not None:
                return cookie_result
            return WorkflowResult(
                False,
                "MaxCompute AK/SK 与 Cookie 元数据通道均不可用，无法读取真实表结构。",
                "reverse_modeling",
                mode,
                steps=[{"step": "read_table_schema", "status": "blocked"}],
                data={"metadata_channels": ["maxcompute_ak_sk", "cookie_bff"]},
                errors=["table metadata channels unavailable"],
            )

        try:
            schema = await mc.get_table_schema(table)
        except Exception as exc:
            error = self._brief_error(exc)
            cookie_result = await self._reverse_table_via_cookie(table, table_name, mode)
            if cookie_result is not None:
                cookie_result.data["maxcompute_fallback_reason"] = error
                return cookie_result
            lower_error = error.lower()
            not_found = any(
                token in lower_error for token in ("not found", "nosuchobject", "does not exist")
            )
            permission_denied = any(
                token in lower_error
                for token in ("nopermission", "no privilege", "accessdenied", "permission")
            )
            if not_found:
                message_text = (
                    f"未找到表 {table}。请填写当前 MaxCompute 项目中的真实表名，"
                    "或提供 DataWorks 节点 ID 逆向读取 FlowSpec。"
                )
            elif permission_denied:
                message_text = (
                    f"已识别逆向目标 {table}，但当前 AK/SK 无权读取该 MaxCompute 表结构。"
                    "可提供 DataWorks 节点 ID，改走官方 MCP/OpenAPI 读取节点。"
                )
            else:
                message_text = f"读取表 {table} 的真实结构失败，请核对表名、项目和 AK/SK 权限。"
            return WorkflowResult(
                False,
                message_text,
                "reverse_modeling",
                mode,
                steps=[{"step": "read_maxcompute_schema", "status": "blocked"}],
                data={
                    "source_type": "table",
                    "table": table,
                    "clarifying_questions": ["请输入真实表名或 DataWorks 节点 ID"],
                    "next_actions": [
                        "确认表位于当前 MaxCompute 项目",
                        "提供 DataWorks 节点 ID 以使用官方 MCP/OpenAPI 逆向",
                    ],
                },
                errors=[error],
            )
        columns = [self._column_to_dict(column) for column in schema.columns]
        partitions = [self._column_to_dict(column) for column in schema.partition_keys]
        metadata = self._infer_reverse_metadata(table_name, columns)
        lineage: Any = []
        bff = getattr(app_state, "_bff_client", None)
        if bff is not None:
            try:
                lineage = await bff.list_lineage(f"odps.{settings.maxcompute_project}.{table_name}")
            except Exception as exc:
                lineage = {"warning": str(exc)}

        steps = [
            {"step": "read_maxcompute_schema", "status": "completed", "count": len(columns)},
            {"step": "infer_layer_and_update_mode", "status": "completed"},
            {"step": "infer_semantic_candidates", "status": "completed"},
            {
                "step": "read_cookie_lineage",
                "status": "completed"
                if not isinstance(lineage, dict) or "warning" not in lineage
                else "warning",
            },
        ]
        return WorkflowResult(
            True,
            f"已完成 {table} 的逆向建模：真实表结构、分层、更新方式、语义候选与 Cookie 血缘均已汇总。",
            "reverse_modeling",
            mode,
            steps=steps,
            artifacts=[
                {
                    "type": "table_schema",
                    "name": table,
                    "columns": columns,
                    "partitions": partitions,
                },
                {
                    "type": "semantic_candidates",
                    "name": table,
                    "content": metadata["semantic_candidates"],
                },
            ],
            data={
                "source_type": "table",
                "table": table,
                "columns": columns,
                "partitions": partitions,
                "lineage": lineage,
                **metadata,
            },
        )

    async def _diagnose(
        self, message: str, params: dict[str, Any], mode: ExecutionMode
    ) -> WorkflowResult:
        task_id = params.get("task_id") or self._extractor.extract_task_id(message)
        instance_match = re.search(
            r"(?:实例|instance)\s*(?:id)?\s*[:：]?\s*([A-Za-z0-9_-]+)", message, re.I
        )
        instance_id = params.get("instance_id") or (
            instance_match.group(1) if instance_match else None
        )
        checks = self.capability_status()
        details: dict[str, Any] = {"capabilities": checks, "startup": app_state.smoke_results}
        errors: list[str] = []
        task_data: dict[str, Any] | None = None

        if task_id:
            from sqlalchemy import select

            from dataworks_agent.db.database import SessionLocal
            from dataworks_agent.db.models import ModelingTaskModel, TaskStepLogModel

            with SessionLocal() as db:
                task = db.get(ModelingTaskModel, task_id)
                if task is not None:
                    task_data = {
                        "task_id": task.task_id,
                        "status": task.status,
                        "source_table": task.source_table,
                        "target_table": task.target_table,
                        "target_layer": task.target_layer,
                        "error_message": task.error_message,
                        "node_uuid": task.node_uuid,
                        "updated_at": task.updated_at,
                    }
                    logs = list(
                        db.scalars(
                            select(TaskStepLogModel)
                            .where(TaskStepLogModel.task_id == task_id)
                            .order_by(TaskStepLogModel.id.desc())
                            .limit(20)
                        )
                    )
                    details["step_logs"] = [
                        {
                            "step": log.step_name,
                            "status": log.status,
                            "error": log.error,
                            "duration_ms": log.duration_ms,
                            "created_at": log.created_at,
                        }
                        for log in reversed(logs)
                    ]
                    errors.extend(log.error for log in logs if log.error)
                    if task.error_message:
                        errors.append(task.error_message)
                details["task"] = task_data
                details["task_found"] = task_data is not None
                if task_data is None:
                    errors.append(f"本地任务 {task_id} 不存在")

        evidence_sources: dict[str, str] = {}
        if instance_id:
            instance_payload, instance_error = await self._official_call(
                "GetTaskInstance", {"Id": str(instance_id)}
            )
            log_payload, log_error = await self._official_call(
                "GetTaskInstanceLog", {"Id": str(instance_id)}
            )
            if instance_payload is not None:
                details["task_instance"] = instance_payload
            if log_payload is not None:
                details["task_instance_log"] = log_payload
            if instance_error or log_error:
                errors.extend(value for value in (instance_error, log_error) if value)
                evidence_sources["official_mcp_instance"] = "warning"
            else:
                evidence_sources["official_mcp_instance"] = "completed"

        node_id = str(params.get("node_id") or (task_data or {}).get("node_uuid") or "")
        node_warnings: list[str] = []
        if node_id:
            node, dependencies, node_sources, node_warnings = await self._read_node_metadata(
                node_id
            )
            if node:
                details["node"] = node
            if dependencies:
                details["node_dependencies"] = dependencies
            evidence_sources.update({f"node_{key}": value for key, value in node_sources.items()})
            errors.extend(node_warnings)

        from dataworks_agent.runtime.self_heal import IssueReport, IssueType, SelfHealFlow

        issue_type = self._infer_issue_type(message, errors)
        proposal = await SelfHealFlow().diagnose(
            IssueReport(
                issue_id=task_id or str(instance_id or f"diag_{uuid.uuid4().hex[:8]}"),
                issue_type=IssueType(issue_type),
                source=task_id or str(instance_id or "agent_health"),
                description="; ".join(dict.fromkeys(errors)) or message,
                context={
                    "affected_tables": [
                        value
                        for value in (
                            (task_data or {}).get("source_table"),
                            (task_data or {}).get("target_table"),
                        )
                        if value
                    ]
                },
            )
        )
        details["recovery_proposal"] = {
            "proposal_id": proposal.proposal_id,
            "action": proposal.action.value,
            "description": proposal.description,
            "requires_approval": proposal.requires_approval,
            "affected_resources": proposal.affected_resources,
        }

        execution_ready = checks["ak_sk"] and checks["maxcompute"] and checks["node_adapter"]
        diagnosed_status = (task_data or {}).get("status") or self._find_nested_key(
            details.get("task_instance"), "Status"
        )
        details["diagnosed_task_status"] = diagnosed_status
        details["health_degraded"] = not execution_ready or diagnosed_status in {
            "failed",
            "error",
            "Failed",
            "Error",
        }
        if task_data:
            evidence_sources["local_task"] = "completed"
        details["evidence_sources"] = evidence_sources
        target_requested = bool(task_id or instance_id or node_id)
        target_resolved = bool(task_data or details.get("task_instance") or details.get("node"))
        details["target_requested"] = target_requested
        details["target_resolved"] = target_resolved
        if target_requested and not target_resolved:
            details["needs_clarification"] = True
            details["clarifying_questions"] = [
                "未找到目标对象；请确认任务 ID、实例 ID 或节点 ID 后重试。"
            ]
        if not any((task_id, instance_id, node_id)):
            message_text = "执行底座健康检查已完成，并已生成恢复建议；提供任务、实例或节点 ID 可继续定位到具体故障。"
        elif target_resolved:
            message_text = "异常排查已完成：已汇总真实任务、实例或节点证据，并生成恢复建议。"
        else:
            message_text = "异常排查已完成，但未找到目标对象或远端证据不可用；结果已标记为降级，不会伪装成定位成功。"
        return WorkflowResult(
            True,
            message_text,
            "diagnose_issue",
            mode,
            steps=[
                {"step": "health_matrix", "status": "completed" if execution_ready else "warning"},
                {
                    "step": "task_and_step_logs",
                    "status": "completed"
                    if task_data or details.get("task_instance")
                    else ("warning" if task_id or instance_id else "skipped"),
                },
                {
                    "step": "node_dependency_inspection",
                    "status": "completed"
                    if node_id and details.get("node")
                    else ("warning" if node_id else "skipped"),
                },
                {"step": "self_heal_proposal", "status": "completed"},
            ],
            data=details,
            errors=list(dict.fromkeys(errors)),
        )

    async def _ask_data(
        self,
        message: str,
        mode: ExecutionMode,
        params: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        params = params or {}
        business_query = params.get("business_query")
        try:
            query_plan = await self._build_query_plan(
                message, business_query, params=params
            )
        except QueryNeedsClarificationError as clarification:
            return self._query_clarification_result(clarification, mode)

        self._validate_readonly_sql(query_plan.sql)
        sql = self._enforce_query_limit(query_plan.sql)
        query_plan.sql = sql
        artifact = {"type": "query_sql", "name": "readonly_query", "content": sql}
        artifacts = [artifact, query_plan.semantic_artifact()]
        if mode == "plan":
            return WorkflowResult(
                True,
                "已生成并校验只读查询 SQL；规划模式不会提交真实查询。",
                "ask_data",
                mode,
                steps=[
                    {"step": "generate_readonly_sql", "status": "completed"},
                    {"step": "execute_query", "status": "planned"},
                ],
                artifacts=artifacts,
                data={
                    "semantic_plan": query_plan.semantic_artifact()["content"],
                    "query": {
                        "sql": sql,
                        "executed": False,
                        "limit": settings.ask_data_default_limit,
                    },
                },
            )

        errors: list[str] = []
        prefer_cookie = self._prefer_cookie_query(sql)
        # Cookie/BFF first for production-ish projects and Chinese discovery results;
        # AK/SK MaxCompute remains the second channel.
        channels = (
            ("cookie_bff", "maxcompute_ak_sk")
            if prefer_cookie
            else ("maxcompute_ak_sk", "cookie_bff")
        )
        for channel in channels:
            try:
                if channel == "cookie_bff":
                    columns, rows = await self._run_cookie_bff_query(sql)
                else:
                    columns, rows = await self._run_maxcompute_query(sql)
                return await self._query_success(query_plan, artifacts, columns, rows, channel)
            except Exception as exc:
                brief = self._brief_error(exc)
                errors.append(f"{channel}: {brief}")
                logger.warning("%s 问数失败，准备切换下一通道: %s", channel, exc)

        return WorkflowResult(
            False,
            "只读 SQL 已生成，但 Cookie BFF 与 AK/SK 查询通道均未成功执行。",
            "ask_data",
            mode,
            steps=[
                {"step": "generate_readonly_sql", "status": "completed"},
                {"step": "execute_query", "status": "blocked"},
            ],
            artifacts=artifacts,
            data={
                "semantic_plan": query_plan.semantic_artifact()["content"],
                "query": {"sql": sql, "executed": False, "limit": settings.ask_data_default_limit},
                "next_actions": [
                    "检查 9222 登录态与 Cookie BFF",
                    "核对 MaxCompute 查询权限",
                ],
            },
            errors=list(dict.fromkeys(errors)),
        )

    async def _run_maxcompute_query(self, sql: str) -> tuple[list[Any], list[Any]]:
        mc = getattr(app_state, "_maxcompute_client", None)
        if mc is None:
            raise RuntimeError("maxcompute client unavailable")
        instance = await asyncio.wait_for(
            mc.submit_query(sql), timeout=settings.ask_data_timeout_seconds
        )
        result = await asyncio.wait_for(
            mc.wait_and_fetch(instance), timeout=settings.ask_data_timeout_seconds
        )
        return list(result.columns), list(result.rows[: settings.ask_data_default_limit])

    async def _run_cookie_bff_query(self, sql: str) -> tuple[list[Any], list[Any]]:
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            raise RuntimeError("cookie BFF client unavailable")

        try:
            return await self._run_cookie_bff_query_once(bff, sql)
        except Exception as exc:
            if not self._is_cookie_auth_error(exc):
                raise
            refresh = await self._refresh_cookie_auth(bff)
            if refresh.get("status") not in {"success", "refreshed", "extracted_unverified"}:
                detail = str(refresh.get("detail") or "Cookie refresh failed")
                raise RuntimeError(f"Cookie refresh failed: {detail}") from exc
            return await self._run_cookie_bff_query_once(bff, sql)

    @staticmethod
    async def _run_cookie_bff_query_once(bff: Any, sql: str) -> tuple[list[Any], list[Any]]:
        """Run read-only SQL via Cookie BFF.

        Prefer IDA (createExecutorJob4Ida) like data-mcp: broader account access and
        no resource-group dependency. Fall back to IDE createExecutorJobV3.
        """
        job_code = None
        used_ida = False
        if hasattr(bff, "execute_sql_ida"):
            job_code = await asyncio.wait_for(
                bff.execute_sql_ida(sql), timeout=settings.ask_data_timeout_seconds
            )
            used_ida = bool(job_code)
        if not job_code:
            job_code = await asyncio.wait_for(
                bff.execute_sql(sql), timeout=settings.ask_data_timeout_seconds
            )
        if not job_code:
            raise RuntimeError(getattr(bff, "last_error", None) or "BFF 未返回查询任务")

        if used_ida and hasattr(bff, "wait_ida_job"):
            completed = await asyncio.wait_for(
                bff.wait_ida_job(job_code), timeout=settings.ask_data_timeout_seconds
            )
        else:
            completed = await asyncio.wait_for(
                bff.wait_job(job_code), timeout=settings.ask_data_timeout_seconds
            )
        if not completed:
            raise RuntimeError(getattr(bff, "last_error", None) or "BFF 查询任务未成功")
        result = await asyncio.wait_for(
            bff.get_query_result(job_code), timeout=settings.ask_data_timeout_seconds
        )
        if not isinstance(result, dict):
            raise RuntimeError("BFF 未返回查询结果")
        headers = result.get("headerList") or []
        columns = [
            str(item.get("name", "")) if isinstance(item, dict) else str(item) for item in headers
        ]
        rows = list((result.get("bodyList") or [])[: settings.ask_data_default_limit])
        return columns, rows

    @staticmethod
    def _prefer_cookie_query(sql: str) -> bool:
        lowered = sql.lower()
        # Prefer Cookie/IDA for business projects commonly searched via Chinese keywords.
        preferred_projects = {
            "giikin_aliyun",
            "giikin",
            "giikin_develop",
            settings.dataworks_prod_schema.lower(),
            settings.dataworks_dev_schema.lower(),
            (settings.maxcompute_project or "").lower(),
        }
        return any(f"{project}." in lowered for project in preferred_projects if project)

    @staticmethod
    def _is_cookie_auth_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "csrf",
                "cookie",
                "login",
                "expired",
                "decrypt",
                "unauthorized",
                "forbidden",
                "403",
            )
        )

    @staticmethod
    async def _refresh_cookie_auth(bff: Any) -> dict[str, Any]:
        from dataworks_agent.cookie.background_refresh import run_cookie_background_refresh_once

        outcome = await run_cookie_background_refresh_once(force=True)
        reset = getattr(bff, "reset_auth_cache", None)
        if callable(reset):
            reset()
        else:
            bff._cookie = ""
            bff._csrf_token = ""
            bff._csrf_time = 0
        return outcome

    def _query_clarification_result(
        self, clarification: QueryNeedsClarificationError, mode: ExecutionMode
    ) -> WorkflowResult:
        contexts = clarification.album_contexts
        candidates = [
            {
                "album_id": context.album_id,
                "album": context.name,
                "description": context.description,
                "categories": context.categories,
                "tables": [
                    {
                        "table": table.full_name,
                        "comment": table.comment,
                        "remark": table.remark,
                        "category": table.category,
                    }
                    for table in context.tables
                ],
            }
            for context in contexts
        ]
        has_candidates = bool(candidates)
        knowledge_matches = clarification.knowledge_matches
        # Newer metadata path injects prebuilt option chips on the
        # exception itself so the frontend can render pick_table rows
        # without re-deriving them. Older paths still produce plain
        # knowledge_matches only.
        option_chips = getattr(clarification, "option_chips", None)
        if not option_chips:
            option_chips = []
            for idx, cand in enumerate(knowledge_matches[:10]):
                if not isinstance(cand, dict):
                    continue
                option_chips.append(
                    {
                        "type": "pick_table",
                        "id": f"opt_{idx}",
                        "label": cand.get("table")
                        or cand.get("full_name")
                        or "",
                        "subtitle": cand.get("comment") or "",
                        "layer": cand.get("layer"),
                        "value": cand.get("table")
                        or cand.get("full_name")
                        or "",
                    }
                )
            option_chips.append(
                {
                    "type": "free_text",
                    "id": "opt_custom",
                    "label": "输入其它表名或完整 SQL",
                    "placeholder": "project.table 或 SELECT ...",
                }
            )
        message = clarification.reason or (
            "该问题尚未命中已验证的指标口径。我已从数据专辑筛出候选表；"
            "请确认指标定义或过滤条件，我不会猜测生产口径。"
            if has_candidates
            else "该问题尚未命中已验证的指标口径。请补充指标定义、目标表或过滤条件；"
            "我不会因为缺少 LLM 配置而把正常问数标记为系统故障。"
        )
        artifacts: list[dict[str, Any]] = []
        if knowledge_matches:
            artifacts.append(
                {
                    "type": "business_knowledge_matches",
                    "name": "metric_candidates",
                    "content": knowledge_matches,
                }
            )
        if has_candidates:
            artifacts.append(
                {
                    "type": "data_album_candidates",
                    "name": "semantic_context",
                    "content": candidates,
                }
            )
        return WorkflowResult(
            True,
            message,
            "ask_data",
            mode,
            steps=[
                {"step": "resolve_semantic_context", "status": "completed"},
                {"step": "clarify_metric_caliber", "status": "waiting"},
                {"step": "execute_query", "status": "waiting"},
            ],
            artifacts=artifacts,
            data={
                "needs_clarification": True,
                "reason": clarification.reason,
                "knowledge_matches": knowledge_matches,
                "missing_contract_fields": clarification.missing_contract_fields,
                "album_candidates": candidates,
                "clarifying_questions": clarification.clarifying_questions
                or [
                    "这个指标的业务定义和排除条件是什么？",
                    "应使用哪个数据专辑或目标表？",
                    "时间范围、统计粒度和分组维度是什么？",
                ],
                "option_chips": option_chips,
                "query": {"executed": False},
            },
        )

    async def _query_success(
        self,
        query_plan: MetricQueryPlan,
        artifacts: list[dict[str, Any]],
        columns: list[Any],
        rows: list[Any],
        channel: str,
    ) -> WorkflowResult:
        sql = query_plan.sql
        query_type = str((query_plan.business_query or {}).get("query_type") or "total")
        if (
            query_plan.metric_id != "ad_hoc_query"
            and not query_plan.selected_dimensions
            and query_type != "trend"
            and len(rows) != 1
        ):
            return WorkflowResult(
                False,
                f"认证指标应唯一命中 1 行，实际返回 {len(rows)} 行，已拒绝给出可能错误的答案。",
                "ask_data",
                "dev_execute",
                steps=[
                    {"step": "resolve_semantic_context", "status": "completed"},
                    {"step": "execute_query", "status": "completed", "channel": channel},
                    {"step": "validate_metric_uniqueness", "status": "failed"},
                ],
                artifacts=artifacts,
                data={
                    "semantic_plan": query_plan.semantic_artifact()["content"],
                    "query": {
                        "sql": sql,
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows),
                        "executed": True,
                        "execution_channel": channel,
                    },
                },
                errors=["metric result is not unique"],
            )
        reconciliation = await self._reconcile_metric_result(query_plan, columns, rows, channel)
        if query_plan.reconciliation_sql:
            artifacts.append(
                {
                    "type": "reconciliation_sql",
                    "name": "metric_reconciliation",
                    "content": query_plan.reconciliation_sql,
                }
            )
        task_id = f"ask_data_{uuid.uuid4().hex[:12]}"
        verification = await self._closed_loop_verifier.verify(
            task_id,
            "ASK_DATA",
            {
                "sql": sql,
                "executed": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "semantic_required": query_plan.metric_id != "ad_hoc_query",
                "album_validation": query_plan.album_validation,
                "metadata_validation": query_plan.metadata_validation,
                "grain_validation": query_plan.grain_validation,
                "freshness_validation": query_plan.freshness_validation,
                "reconciliation": reconciliation,
            },
        )
        verification_data = {
            "task_id": verification.task_id,
            "task_type": verification.task_type,
            "status": verification.status.value,
            "summary": verification.summary,
            "passed_count": verification.passed_count,
            "failed_count": verification.failed_count,
            "warning_count": verification.warning_count,
            "checks": [
                {
                    "name": check.check_name,
                    "passed": check.passed,
                    "severity": check.severity.value,
                    "message": check.message,
                    "details": check.details,
                }
                for check in verification.checks
            ],
        }
        verified = verification.status == VerificationStatus.PASSED
        return WorkflowResult(
            verified,
            (
                self._format_query_answer(query_plan, columns, rows)
                if verified
                else "查询已执行，但闭环验收未通过，结果不会标记为完成。"
            ),
            "ask_data",
            "dev_execute",
            steps=[
                {"step": "generate_readonly_sql", "status": "completed"},
                {"step": "execute_query", "status": "completed", "channel": channel},
                {
                    "step": "reconcile_metric_result",
                    "status": "completed" if reconciliation.get("passed") else "failed",
                }
                if query_plan.metric_id != "ad_hoc_query"
                else {"step": "reconcile_metric_result", "status": "not_applicable"},
                {
                    "step": "closed_loop_verification",
                    "status": "completed" if verified else "failed",
                },
            ],
            artifacts=artifacts,
            data={
                "task_id": task_id,
                "semantic_plan": query_plan.semantic_artifact()["content"],
                "query": {
                    "sql": sql,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "executed": True,
                    "execution_channel": channel,
                },
                "reconciliation": reconciliation,
                "verification": verification_data,
            },
            errors=[] if verified else [verification.summary],
        )

    async def _reconcile_metric_result(
        self,
        query_plan: MetricQueryPlan,
        columns: list[Any],
        rows: list[Any],
        channel: str,
    ) -> dict[str, Any]:
        if query_plan.metric_id == "ad_hoc_query":
            return {"required": False, "passed": True, "status": "not_applicable"}
        reconciliation_contract = query_plan.caliber.get("reconciliation") or {}
        if not query_plan.reconciliation_sql:
            if reconciliation_contract.get("required") is False:
                return {
                    "required": False,
                    "passed": True,
                    "status": "contract_not_required",
                    "strategy": reconciliation_contract.get("strategy", "source_contract"),
                }
            return {
                "required": True,
                "passed": False,
                "status": "missing_contract",
                "message": "指标缺少对账契约",
            }
        try:
            bound_sql = self._bind_reconciliation_date(query_plan.reconciliation_sql, columns, rows)
            query_plan.reconciliation_sql = bound_sql
            self._validate_readonly_sql(bound_sql)
            reconciliation_sql = self._enforce_query_limit(bound_sql)
            if channel == "cookie_bff":
                other_columns, other_rows = await self._run_cookie_bff_query(reconciliation_sql)
            else:
                other_columns, other_rows = await self._run_maxcompute_query(reconciliation_sql)
            passed, details = self._compare_metric_results(
                query_plan, columns, rows, other_columns, other_rows
            )
            return {
                "required": True,
                "passed": passed,
                "status": "passed" if passed else "mismatch",
                "sql": reconciliation_sql,
                "details": details,
            }
        except Exception as exc:
            return {
                "required": True,
                "passed": False,
                "status": "execution_failed",
                "message": self._brief_error(exc),
            }

    @staticmethod
    def _bind_reconciliation_date(sql: str, columns: list[Any], rows: list[Any]) -> str:
        token = "__PRIMARY_DATA_DATE__"
        if token not in sql:
            return sql
        if not rows:
            raise ValueError("主查询没有结果，无法绑定对账日期")
        names = [str(getattr(column, "name", column)) for column in columns]
        row = rows[0]
        mapped = (
            row
            if isinstance(row, dict)
            else dict(zip(names, row if isinstance(row, (list, tuple)) else [row], strict=False))
        )
        value = str(mapped.get("data_date") or "").strip()
        if not re.fullmatch(r"\d{4}(?:-?\d{2}){2}", value):
            raise ValueError(f"主查询返回了无效的数据日期: {value}")
        return sql.replace(token, value.replace("-", ""))

    @staticmethod
    def _compare_metric_results(
        query_plan: MetricQueryPlan,
        columns: list[Any],
        rows: list[Any],
        other_columns: list[Any],
        other_rows: list[Any],
    ) -> tuple[bool, dict[str, Any]]:
        from decimal import Decimal, InvalidOperation

        names = [str(getattr(column, "name", column)) for column in columns]
        other_names = [str(getattr(column, "name", column)) for column in other_columns]
        dimension_columns = [
            str(item.get("column") or "")
            for item in query_plan.caliber.get("dimensions", [])
            if str(item.get("name") or "") in query_plan.selected_dimensions
        ]
        measure = query_plan.caliber.get("measure", {})
        measure_alias = str(measure.get("alias") or measure.get("column") or "value")
        result_column = (
            measure_alias if query_plan.selected_dimensions else f"total_{measure_alias}"
        )
        key_columns = ["data_date", "data_hour", *dimension_columns]

        def normalize(row_names: list[str], result_rows: list[Any]) -> dict[tuple[str, ...], str]:
            normalized: dict[tuple[str, ...], str] = {}
            for row in result_rows:
                mapped = (
                    row
                    if isinstance(row, dict)
                    else dict(
                        zip(
                            row_names,
                            row if isinstance(row, (list, tuple)) else [row],
                            strict=False,
                        )
                    )
                )
                key = tuple(str(mapped.get(name) or "") for name in key_columns)
                raw = mapped.get(result_column)
                try:
                    value = str(Decimal(str(raw)).normalize())
                except (InvalidOperation, TypeError, ValueError):
                    value = str(raw)
                normalized[key] = value
            return normalized

        primary = normalize(names, rows)
        reference = normalize(other_names, other_rows)
        return primary == reference, {
            "primary_rows": len(primary),
            "reference_rows": len(reference),
            "primary": {"|".join(key): value for key, value in primary.items()},
            "reference": {"|".join(key): value for key, value in reference.items()},
        }

    @staticmethod
    def _format_query_answer(
        query_plan: MetricQueryPlan, columns: list[Any], rows: list[Any]
    ) -> str:
        from decimal import Decimal, InvalidOperation

        names = [str(getattr(column, "name", column)) for column in columns]
        if not rows:
            return f"{query_plan.metric_name}查询完成，但当前时间范围没有返回数据。"

        def map_row(row: Any) -> dict[str, Any]:
            if isinstance(row, dict):
                return row
            values = row if isinstance(row, (list, tuple)) else [row]
            return dict(zip(names, values, strict=False))

        measure = query_plan.caliber.get("measure", {})
        measure_alias = str(measure.get("alias") or measure.get("column") or "value")
        result_column = (
            measure_alias if query_plan.selected_dimensions else f"total_{measure_alias}"
        )
        unit = str(measure.get("unit") or "").upper()

        def display(value: Any) -> str:
            try:
                number = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return str(value)
            if unit == "CNY":
                return f"¥{number:,.2f}"
            if unit in {"RATIO", "PERCENT", "%"}:
                return f"{number * 100:,.2f}%"
            if number == number.to_integral_value():
                return f"{int(number):,}"
            return f"{number:,.2f}"

        mapped_rows = [map_row(row) for row in rows]
        first = mapped_rows[0]
        business_query = query_plan.business_query or {}
        query_type = str(business_query.get("query_type") or "total")
        is_trend = query_type == "trend"
        time_range = business_query.get("time_range") or {}
        data_date = str(first.get("data_date") or "")
        data_hour = str(first.get("data_hour") or "")
        requested_start = str(time_range.get("start") or "")
        requested_end = str(time_range.get("end") or "")
        if str(time_range.get("kind") or "") == "range" and requested_start and requested_end:
            snapshot = f"（时间范围 {requested_start} 至 {requested_end}）"
        else:
            snapshot = (
                f"（数据日期 {data_date}，截至 {data_hour}:00）"
                if data_date and data_hour
                else f"（数据日期 {data_date}）"
                if data_date
                else ""
            )
        album_names = "、".join(item["name"] for item in query_plan.albums)
        evidence = (
            f"\n\n口径证据：数据专辑“{album_names}” + approved v{query_plan.metric_version}。"
            if album_names
            else ""
        )
        if not query_plan.selected_dimensions and not is_trend:
            return (
                f"**{query_plan.metric_name}：{display(first.get(result_column))}**{snapshot}"
                f"{evidence}"
            )

        selected_columns = ["data_date"] if is_trend else []
        selected_columns.extend(
            str(item.get("column") or "")
            for item in query_plan.caliber.get("dimensions", [])
            if str(item.get("name") or "") in query_plan.selected_dimensions
        )
        lines = [f"**{query_plan.metric_name}{snapshot}**"]
        total = Decimal("0")
        total_available = str(measure.get("aggregation") or "").lower() in {"sum", "count"}
        if total_available:
            try:
                total = sum(
                    (Decimal(str(item.get(result_column))) for item in mapped_rows),
                    start=Decimal("0"),
                )
            except (InvalidOperation, TypeError, ValueError):
                total_available = False
        for item in mapped_rows[:20]:
            label = " / ".join(str(item.get(column) or "—") for column in selected_columns)
            value = item.get(result_column)
            lines.append(f"- {label}：{display(value)}")
        if len(mapped_rows) > 20:
            lines.append(f"- ……其余 {len(mapped_rows) - 20} 行请查看结果表")
        if total_available:
            total_label = "区间合计" if is_trend else "合计"
            lines.append(f"- **{total_label}：{display(total)}**")
        lines.append(evidence)
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _brief_error(exc: Exception) -> str:
        text = " ".join(str(exc).strip().splitlines())
        lower = text.lower()
        if "nosuchobject" in lower or "table not found" in lower:
            return "MaxCompute table not found"
        if "odps:createinstance" in lower:
            return "MaxCompute permission denied: missing odps:CreateInstance"
        if any(token in lower for token in ("nopermission", "no privilege", "accessdenied")):
            return "MaxCompute permission denied"
        return text[:180] or exc.__class__.__name__

    def understand_business_query(self, message: str) -> dict[str, Any] | None:
        understood = self._metric_query_planner.understand(message)
        return understood[0].to_dict() if understood is not None else None

    def refine_business_query(
        self, message: str, previous: dict[str, Any]
    ) -> dict[str, Any] | None:
        refined = self._metric_query_planner.refine(message, previous)
        return refined.to_dict() if refined is not None else None

    async def _build_readonly_sql(self, message: str) -> str:
        """Compatibility wrapper used by tests and callers that only need SQL."""
        return (await self._build_query_plan(message)).sql

    async def _build_query_plan(
        self,
        message: str,
        business_query: dict[str, Any] | None = None,
        *,
        params: dict[str, Any] | None = None,
    ) -> MetricQueryPlan:
        params = params or {}
        fenced = re.search(r"```sql\s*(.*?)```", message, re.I | re.S)
        if fenced:
            return self._ad_hoc_query_plan(fenced.group(1).strip(), "用户提供 SQL")

        # History-pre-resolve for follow-ups like "刚才那张表有多少条"
        # where the regex extractor cannot pull a physical name from the
        # current message.  We feed the most recent table as a fallback
        # table candidate further down.
        history_table: str | None = None
        recent = await self._history_provider.recent_tables(
            params.get("conversation_id") or business_query
        )
        if recent and self._looks_like_physical_table(recent[0]):
            history_table = recent[0]

        table = (
            params.get("table_name")
            or params.get("source_table")
            or self._extractor.extract_table_name(message)
        )
        if not table:
            raw = re.search(r"(?:查询|统计|查看|表)\s*([A-Za-z][A-Za-z0-9_.]+)", message)
            table = raw.group(1) if raw else None
        if not table and history_table:
            # Use the last-discussed table from history when the new
            # query references the same logical entity ("刚才那张表",
            # "它", "上一张"…) but no new keyword is present.
            followup_markers = (
                "刚才",
                "之前",
                "上一张",
                "它",
                "上面",
                "前面",
                "刚才的",
                "那个",
            )
            marker_hit = any(marker in message for marker in followup_markers)
            counting_hit = (
                "多少条" in message
                or "行数" in message
                or "count" in message.lower()
            )
            logger.info(
                "history_table=%s marker_hit=%s counting_hit=%s (message=%s)",
                history_table,
                marker_hit,
                counting_hit,
                message[:80],
            )
            if marker_hit or counting_hit:
                table = history_table

        # Physical English table names can be queried directly.
        if table and self._looks_like_physical_table(str(table)):
            table_name = str(table)
            assert_safe_table_name(table_name.split(".")[-1])
            sql = self._build_simple_table_sql(message, table_name)
            return self._ad_hoc_query_plan(
                sql,
                "用户明确指定表" if table_name != history_table
                else "上下文延续：最近引用表",
                table=table_name,
            )

        # Chinese business keywords (e.g. 订单表) → MetadataProvider first
        # (cookie/bff search + data-album ranking) before falling through
        # to the semantic / LLM layer.
        search_keyword = self._extract_table_search_keyword(message, params)
        if search_keyword:
            metadata_result = await self._metadata_provider.search_table(
                search_keyword, message
            )
            if metadata_result is not None:
                resolved = await self._build_plan_from_metadata(
                    message, search_keyword, metadata_result
                )
                if resolved is not None:
                    return resolved

        candidate_tables = (
            self._metric_query_planner.candidate_tables_for_query(business_query)
            if business_query
            else self._metric_query_planner.candidate_tables(message)
        )
        required_album_ids = (
            self._metric_query_planner.required_album_ids_for_query(business_query)
            if business_query
            else self._metric_query_planner.required_album_ids(message)
        )
        album_contexts = await self._album_context_resolver.resolve(
            message,
            required_tables=candidate_tables,
            required_album_ids=required_album_ids,
        )
        semantic_plan = (
            self._metric_query_planner.plan_frame(business_query, album_contexts)
            if business_query
            else self._metric_query_planner.plan(message, album_contexts)
        )
        if semantic_plan is not None:
            if semantic_plan.album_validation.get("status") not in {
                "direct_match",
                "lineage_match",
            }:
                raise QueryNeedsClarificationError(
                    message,
                    album_contexts,
                    f"指标表 {semantic_plan.table} 未在声明的数据专辑资产中直接命中，也没有已验证血缘，已阻止执行。",
                )
            await self._validate_semantic_plan_metadata(semantic_plan)
            return semantic_plan
        knowledge_result = self._knowledge_base.search(message, album_contexts)
        if knowledge_result.matches:
            names = "、".join(match.item.name for match in knowledge_result.matches)
            reason = (
                f"已识别到多个待确认的经营指标：{names}。请选择具体指标并确认业务口径；"
                "这些候选仅有资产证据，尚未批准为可执行 query contract。"
                if len(knowledge_result.matches) > 1
                else f"已识别到{names}，但该指标口径仍是 draft。请先确认以下业务口径，系统不会猜测生产 SQL。"
            )
            raise QueryNeedsClarificationError(
                message,
                album_contexts,
                reason,
                knowledge_matches=[match.to_dict() for match in knowledge_result.matches],
                clarifying_questions=knowledge_result.clarifying_questions,
                missing_contract_fields=knowledge_result.missing_contract_fields,
            )
        if not settings.llm_api_key:
            raise QueryNeedsClarificationError(
                message,
                album_contexts,
                reason=(
                    f"未在元数据搜表 / 语义层命中“{search_keyword or message}”对应的物理表。"
                    "请补充英文表名（如 dwd_trade_order_detail），或确认 Cookie BFF 可用。"
                ),
            )

        from dataworks_agent.llm.context import ContextBuilder
        from dataworks_agent.llm.service import LLMService

        builder = ContextBuilder().add_instruction(
            "Only generate one read-only MaxCompute SELECT/WITH statement without explanation. "
            "Never generate write operations. Use LIMIT 100 by default."
        )
        album_metadata = self._album_context_resolver.format_for_llm(album_contexts)
        if album_metadata:
            builder.add_metadata(album_metadata)
        context = builder.add_prompt(message).build()
        response = await LLMService.from_settings(settings).complete(context, "normal")
        sql = response.content.strip().removeprefix("```sql").removesuffix("```").strip()
        plan = self._ad_hoc_query_plan(sql, "数据专辑约束的 LLM 规划")
        plan.albums = [
            {"album_id": item.album_id, "name": item.name, "categories": item.categories}
            for item in album_contexts
        ]
        return plan

    @staticmethod
    def _looks_like_physical_table(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        # Chinese labels like 订单 / 订单表 are search keywords, not physical tables.
        if re.search(r"[一-鿿]", text):
            return False
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?", text))

    @classmethod
    def _extract_table_search_keyword(
        cls, message: str, params: dict[str, Any] | None = None
    ) -> str:
        params = params or {}
        for key in ("table_name", "source_table", "keyword"):
            value = str(params.get(key) or "").strip()
            if value and not cls._looks_like_physical_table(value):
                candidate = value.removesuffix("表").strip() or value
                if len(candidate) >= 2:
                    return candidate

        # Strip leading chat verbs so "查询销售表" / "看看广告消耗表" -> bare noun + 表.
        text = message.strip()
        text = re.sub(
            r"^(?:请)?(?:帮我)?(?:查(?:询|看)?|检索|找|看){1,3}(?:一下|一|下)?",
            "",
            text,
        )
        match = re.search(r"([一-龥A-Za-z0-9_]{2,24})表", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"([一-龥A-Za-z0-9_]{2,24})表", message)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _table_layer(name: str) -> str:
        lowered = str(name or "").lower()
        match = re.search(r"(?:^|_)(ods|dwd|dim|dws|dmr|rp)(?:_|$)", lowered)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_layer_filter(message: str) -> str:
        """Pick a single layer token from a follow-up message like "只要 dwd"."""
        text = (message or "").lower()
        match = re.search(r"\b(ods|dwd|dim|dws|dmr|rp)\b", text)
        return match.group(1) if match else ""

    @staticmethod
    def _user_wants_non_ods(message: str) -> bool:
        """Return True when the user is asking about the business layer.

        Default = True (Chinese business wording like 订单表 / 销售表 maps to
        DWS/DWD/DIM, not ODS). Opt out via ODS / 贴源 / 原始 / 同步 wording
        so the full candidate list stays available.
        """
        text = (message or "").lower()
        ods_markers = (
            "ods",
            "贴源",
            "原始",
            "同步表",
            "同步层",
            "dataworks层",
        )
        return not any(marker in text for marker in ods_markers)

    @staticmethod
    def _build_simple_table_sql(message: str, table: str) -> str:
        if any(k in message for k in ("多少条", "行数", "count", "数量")):
            return f"SELECT COUNT(*) AS row_count FROM {table}"
        return f"SELECT * FROM {table} LIMIT {settings.ask_data_default_limit}"

    @staticmethod
    def _project_of(table: str) -> str:
        return table.split(".", 1)[0].lower() if "." in table else ""

    @staticmethod
    def _partition_columns_for(table: str) -> tuple[str, ...]:
        """Resolve partition columns per dataworks-agent / data-mcp knowledge.

        Project rules (dataworks_agent.standards.steering.data-warehouse-standards):
        - giikin_aliyun uses ``pt`` (single daily partition).
        - giikin / giikin_develop use ``dt`` (+ optional ``ht``).
        - Tables whose name ends in ``_hour`` / ``_hourly`` need ``dt + ht``.

        Returns an ordered tuple suitable for ``WHERE pk='X' AND pk='Y'``.
        """
        proj = AgentWorkflowService._project_of(table)
        name = table.split(".")[-1].lower()
        if proj == "giikin_aliyun":
            return ("pt",)
        if name.endswith(("_hour", "_hourly")):
            return ("dt", "ht")
        if proj.startswith("giikin"):
            return ("dt",)
        return ("dt",)

    @staticmethod
    def _table_layer(name: str) -> str:
        lowered = str(name or "").lower()
        match = re.search(r"(?:^|_)(ods|dwd|dim|dws|dmr|rp)(?:_|$)", lowered)
        return match.group(1) if match else ""

    @staticmethod
    def _partition_sample_value(col: str) -> str:
        """Static placeholder partition value when no live evidence exists.

        Follows data-mcp's ``submit_query`` guidance + project spec:
        - For ``pt`` / ``dt`` use yesterday in yyyymmdd.
        - For ``ht`` use 00 (zero hour) so a query never silently
          over-fetches another day's data; the platform re-binds these
          via ``${workspace.hour_last1h}`` at scheduling time.
        """
        if col == "ht":
            return "00"
        return _today_partition_value()

    async def _partition_filter_clause(
        self, table: str
    ) -> tuple[str, str | None]:
        """Pick ``WHERE ...`` clause and a sample partition value (or None).

        Strategy:
        1. Try ``bff.get_table_ddl`` for the project's PARTITIONED BY clause
           (single source of truth — same lookup data-mcp describes).
        2. Fall back to the project + name-suffix rules above.
        Sample value comes from the most recent upstream task's parameter
        values when available, otherwise stays ``None`` so callers know it
        was a static rule-based guess.
        """
        bff = getattr(app_state, "_bff_client", None)
        cols: tuple[str, ...] = ()
        sample_value: str | None = None
        partition_source = "static_rule"
        if bff is not None:
            try:
                ddl = await bff.get_creation_ddl(f"odps.{table}")
            except Exception as exc:
                logger.warning("get_creation_ddl(%s) 失败: %s", table, exc)
                ddl = None
            if isinstance(ddl, str) and ddl:
                parsed = self._parse_partition_columns_from_ddl(ddl)
                if parsed:
                    cols = parsed
                    partition_source = "table_ddl"
        if not cols:
            cols = self._partition_columns_for(table)
        # Try to fetch a recent business date hint (e.g. dt=20260701).
        if bff is not None and any(c in {"dt", "pt"} for c in cols):
            try:
                params = await bff.get_node_params  # type: ignore[attr-defined]
            except Exception:
                params = None
            if not params:
                sample_value = None
        clause = self._format_partition_clause(cols, sample_value)
        return clause, partition_source

    @staticmethod
    def _parse_partition_columns_from_ddl(ddl: str) -> tuple[str, ...]:
        match = re.search(
            r"PARTITIONED\s+BY\s*\(([^)]*)\)",
            ddl,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ()
        cols: list[str] = []
        for raw in match.group(1).split(","):
            name = raw.strip().split()[0].strip("`\"'[]")
            if name:
                cols.append(name)
        return tuple(cols)

    @staticmethod
    def _format_partition_clause(
        cols: tuple[str, ...], sample_value: str | None
    ) -> str:
        if not cols:
            return ""
        parts: list[str] = []
        for col in cols:
            value = sample_value or AgentWorkflowService._partition_sample_value(col)
            parts.append(f"{col}='{value}'")
        return " WHERE " + " AND ".join(parts)

    @staticmethod
    def _build_table_sql(
        message: str,
        table: str,
        partition_clause: str,
        *,
        alias: str | None = None,
    ) -> str:
        if any(k in message for k in ("多少条", "行数", "count", "数量")):
            base = f"SELECT COUNT(*) AS row_count FROM {table}{partition_clause}"
        else:
            base = f"SELECT * FROM {table}{partition_clause} LIMIT {settings.ask_data_default_limit}"
        return base

    async def _resolve_table_via_bff_search(
        self, keyword: str, message: str
    ) -> MetricQueryPlan | None:
        """Resolve Chinese keywords to physical tables via Cookie BFF search.

        Pipeline (inspired by data-mcp list_tables + the project's data-album
        scorer in semantic/album_context.py):

        1. Resolve the **business-domain album** first (e.g. 订单数据 / 订单信息 /
           社交电商模型汇总). The album id is cached per-conversation-style
           keyword so the same hot-keyword doesn't pay the album-list cost
           twice.
        2. Pull that album's entities (``list_meta_album_entities``) — these
           are the strongest candidates because DataMap explicitly tagged
           them as belonging to the requested business domain.
        3. Augment with ``bff.search_tables(keyword)`` for long-tail hits
           that the album may not yet cover.
        4. Best-effort ``get_upstream_tasks`` for ``ref_count`` popularity.
        5. Score = (album hit, ref_count). Album hit always wins ties.
        """
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return None

        # 1. Resolve the most relevant business-domain album for this keyword.
        album = await self._resolve_keyword_album(keyword)
        album_entities: list[dict[str, Any]] = []
        if album is not None:
            try:
                album_entities = await bff.list_meta_album_entities(
                    album["album_id"], page_size=500
                )
            except Exception as exc:
                logger.warning("list_meta_album_entities(%s) 失败: %s", album, exc)
                album_entities = []

        # 2. Free-text BFF search for the rest.
        try:
            tables = await bff.search_tables(keyword)
        except Exception as exc:
            if self._is_cookie_auth_error(exc):
                refresh = await self._refresh_cookie_auth(bff)
                if refresh.get("status") in {"success", "refreshed", "extracted_unverified"}:
                    try:
                        tables = await bff.search_tables(keyword)
                    except Exception as retry_exc:
                        logger.warning(
                            "BFF search_tables(%s) 刷新后仍失败: %s", keyword, retry_exc
                        )
                        tables = []
                else:
                    logger.warning("BFF search_tables(%s) Cookie 失效: %s", keyword, exc)
                    tables = []
            else:
                logger.warning("BFF search_tables(%s) 失败: %s", keyword, exc)
                tables = []

        # 3. Merge album entities (priority) with BFF search results.
        # Filter out entries whose table_name is empty, contains "*" (BFF
        # sometimes returns redacted project / table names) or fails the
        # identifier whitelist — these would crash assert_safe_table_name.
        def _clean_name(raw_name: object) -> str:
            text = str(raw_name or "").strip()
            if not text or "*" in text:
                return ""
            if not _IDENTIFIER_RE.match(text.split(".")[-1]):
                return ""
            return text

        # Filter BFF-search candidates that don't actually mention the
        # keyword anywhere (table name / comment). ``搜索单车`` returning
        # 订单/物料 tables is noise; reject those up front.
        def _matches_keyword(item: dict[str, Any]) -> bool:
            if not keyword:
                return True
            key = keyword.lower()
            haystack_parts = [
                str(item.get("table_name") or "").lower(),
                str(item.get("comment") or "").lower(),
                str(item.get("remark") or "").lower(),
            ]
            return any(key in part for part in haystack_parts if part)

        merged: dict[str, dict[str, Any]] = {}
        for item in album_entities:
            if not isinstance(item, dict):
                continue
            name = _clean_name(item.get("table_name") or item.get("name"))
            project = _clean_name(item.get("project") or item.get("databaseName"))
            if not name:
                continue
            full_name = f"{project}.{name}" if project else name
            guid = str(item.get("entity_guid") or item.get("entityGuid") or "")
            if not guid and project and name:
                guid = f"odps.{project}.{name}"
            merged[full_name.lower()] = {
                "project": project,
                "table_name": name,
                "full_name": full_name,
                "comment": item.get("comment") or "",
                "entity_guid": guid,
                "ref_count": 0,
                "album_hit": True,
                "album_id": album["album_id"] if album else None,
                "album_name": album["name"] if album else "",
                "album_category": str(item.get("remark") or ""),
            }
        for item in tables or []:
            if not isinstance(item, dict):
                continue
            if not _matches_keyword(item):
                continue
            name = _clean_name(item.get("table_name") or item.get("name"))
            project = _clean_name(item.get("project") or item.get("databaseName"))
            if not name:
                continue
            full_name = f"{project}.{name}" if project else name
            guid = str(item.get("entity_guid") or item.get("entityGuid") or "")
            if not guid and project and name:
                guid = f"odps.{project}.{name}"
            key = full_name.lower()
            row = merged.setdefault(
                key,
                {
                    "project": project,
                    "table_name": name,
                    "full_name": full_name,
                    "comment": item.get("comment") or "",
                    "entity_guid": guid,
                    "ref_count": int(item.get("ref_count") or 0),
                    "album_hit": False,
                    "album_id": None,
                    "album_name": "",
                    "album_category": "",
                },
            )
            if not row.get("comment") and item.get("comment"):
                row["comment"] = item.get("comment") or ""

        normalized = list(merged.values())
        if not normalized:
            # Both album and BFF search came back empty after keyword
            # filtering — don't fabricate candidates. Let the caller fall
            # through to the semantic / LLM path so we either ask for
            # clarification on real data or generate SQL with context.
            logger.info(
                "bff_search no hit for keyword=%s (album=%s, raw_bff=%d)",
                keyword,
                album.get("name") if album else None,
                len(tables or []),
            )
            return None
        if album is None and not any(item.get("album_hit") for item in normalized) and len(normalized) > 1:
            # No business-domain album matched: only trust BFF-search
            # results when there is exactly one candidate. Many candidates
            # without album evidence usually means the keyword is too
            # noisy (e.g. 查一下单车 matched against 物料 tables), so
            # defer to the semantic / LLM layer instead of dumping the
            # list to the user.
            logger.info(
                "bff_search weak hit (%d) for keyword=%s without album, deferring to semantic layer",
                len(normalized),
                keyword,
            )
            return None

        # 4.5. Default to "business-facing" layers (DWS / DWD / DIM / DMR).
        # Chinese business keywords like 订单表 normally mean the served
        # layer, not the ODS layer. Let the user explicitly opt in via
        # ODS-shaped phrasing before falling back.
        prefer_non_ods = self._user_wants_non_ods(message)
        if prefer_non_ods:
            business = [
                item
                for item in normalized
                if not str(item.get("table_name") or "").lower().startswith(
                    ("ods_", "tb_ods_")
                )
            ]
            if business:
                normalized = business
        # Layer filter from follow-up hints (e.g. "只要 dwd", "看 dws").
        requested_layer = self._extract_layer_filter(message)
        if requested_layer:
            layered = [
                item
                for item in normalized
                if AgentWorkflowService._table_layer(item.get("table_name") or "")
                == requested_layer
            ]
            if layered:
                normalized = layered

        # 5. ref_count popularity ranking for BFF-only candidates.
        bff_only = [item for item in normalized if not item.get("album_hit")]
        if bff_only and any(item.get("entity_guid") for item in bff_only):
            await self._enrich_table_ref_counts(bff, bff_only)

        # 6. Sort: album hit first, then ref_count desc.
        normalized.sort(
            key=lambda item: (
                1 if item.get("album_hit") else 0,
                int(item.get("ref_count") or 0),
            ),
            reverse=True,
        )

        top = normalized[0]
        unique_names = {item["full_name"] for item in normalized}

        # Album-anchored single hit is always a strong-rank hit.
        if top.get("album_hit") and len(normalized) == 1:
            return self._plan_single_hit(message, keyword, top)
        if top.get("album_hit") and len(normalized) > 1:
            runner_up_score = (
                0
                if not normalized[1].get("album_hit")
                else int(normalized[1].get("ref_count") or 0)
            )
            top_key = int(top.get("ref_count") or 0)
            # Demote auto-pick when the top candidate has no real evidence
            # (ref_count == 0) and the runner-up is also an album hit:
            # surface the candidates so the user can choose rather than
            # silently picking the first one in iteration order.
            if (
                top_key > 0
                and (runner_up_score == 0 or top_key >= runner_up_score + 5)
            ):
                return self._plan_single_hit(message, keyword, top)

        # Single BFF-search hit with no album candidates: trust it as a
        # unique result. This preserves the original behaviour of returning
        # the candidate when metadata search yields exactly one table.
        if len(normalized) == 1 and not top.get("album_hit"):
            return self._plan_single_hit(message, keyword, top)
        if len(unique_names) == 1 and len(normalized) > 1:
            return self._plan_single_hit(message, keyword, top)

        # Many candidates: always show the top 10 (album-anchored first)
        # so the user can pick. We deliberately do NOT auto-pick one just
        # because it's in the album — 30 unrelated tables in 订单域 would
        # still confuse the user, but 10 with their layer annotated is
        # actually useful.

        candidates = [
            {
                "table": item["full_name"],
                "comment": item.get("comment") or "",
                "ref_count": item.get("ref_count") or 0,
                "album_hit": bool(item.get("album_hit")),
                "album": item.get("album_name") or "",
                "category": item.get("album_category") or "",
                "layer": AgentWorkflowService._table_layer(item.get("table_name") or ""),
                "entity_guid": item.get("entity_guid") or "",
            }
            for item in normalized[:10]
        ]
        album_label = top.get("album_name") or "未命中专辑"
        # Show layer summary so the user can drill down ("DWS only" /
        # "跳过 ODS" etc.) instead of eyeballing 30 candidates.
        layer_counts: dict[str, int] = {}
        for item in normalized:
            layer = AgentWorkflowService._table_layer(item.get("table_name") or "")
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
        layer_hint = (
            "候选层级：" + " / ".join(
                f"{layer.upper()}={layer_counts[layer]}" for layer in layer_counts
            )
            if layer_counts
            else ""
        )
        raise QueryNeedsClarificationError(
            message,
            [],
            reason=(
                f"元数据搜表为“{keyword}”找到 {len(normalized)} 张候选表，"
                f"建议专辑：{album_label}。"
                + (f" {layer_hint}。" if layer_hint else " 请选择一张后再查询。")
                + " 可回复 \"只要 dwd\" 或具体表名进一步收敛。"
            ),
            knowledge_matches=candidates,
            clarifying_questions=[
                "请从候选表中选择一张，或直接回复完整表名（project.table）。",
                "如果目标是统计行数，也可以说：查 giikin.xxx 有多少条。",
                "回复 \"只要 dws / dwd / ods\" 可以只看对应分层。",
            ],
        )

    def _plan_single_hit(
        self, message: str, keyword: str, item: dict[str, Any]
    ) -> MetricQueryPlan:
        table = item["full_name"]
        bare = table.split(".")[-1] if "." in table else table
        assert_safe_table_name(bare)
        partition_clause, partition_source = (
            self._build_table_partition_clause_sync(table)
        )
        sql = self._build_table_sql(message, table, partition_clause)
        plan = self._ad_hoc_query_plan(
            sql,
            f"Cookie BFF + 业务域专辑命中：{keyword} → {table}",
            table=table,
        )
        plan.selection_evidence.append(
            f"album={item.get('album_name') or '-'} "
            f"album_hit={int(bool(item.get('album_hit')))} "
            f"ref_count={item.get('ref_count')} "
            f"partition={partition_clause or 'none'} "
            f"source={partition_source}"
        )
        return plan

    async def _build_plan_from_metadata(
        self,
        message: str,
        keyword: str,
        result: MetadataQueryResult,
    ) -> MetricQueryPlan | None:
        """Bridge ``MetadataProvider.search_table`` into the planner flow.

        The provider returns raw candidates; this helper applies the
        same layer + album + ref_count scoring we already encode for the
        legacy inline path so the rule-based planner can continue
        producing single-hit plans / clarification errors.
        """
        normalized = await self._shape_metadata_candidates(message, keyword, result)
        if not normalized:
            return None

        top = normalized[0]
        unique_names = {item["full_name"] for item in normalized}

        if top.get("album_hit") and len(normalized) == 1:
            return self._plan_single_hit(message, keyword, top)
        if top.get("album_hit") and len(normalized) > 1:
            runner_up_score = (
                0
                if not normalized[1].get("album_hit")
                else int(normalized[1].get("ref_count") or 0)
            )
            top_key = int(top.get("ref_count") or 0)
            if (
                top_key > 0
                and (runner_up_score == 0 or top_key >= runner_up_score + 5)
            ):
                return self._plan_single_hit(message, keyword, top)

        if len(normalized) == 1 and not top.get("album_hit"):
            return self._plan_single_hit(message, keyword, top)
        if len(unique_names) == 1 and len(normalized) > 1:
            return self._plan_single_hit(message, keyword, top)

        return self._raise_metadata_clarification(
            message, keyword, result, normalized
        )

    async def _shape_metadata_candidates(
        self,
        message: str,
        keyword: str,
        result: MetadataQueryResult,
    ) -> list[dict[str, Any]]:
        """Apply layer filter + ranking + prefer-non-ODS to provider output."""
        normalized = list(result.candidates)

        prefer_non_ods = self._user_wants_non_ods(message)
        if prefer_non_ods:
            business = [
                item
                for item in normalized
                if not str(item.get("table_name") or "").lower().startswith(
                    ("ods_", "tb_ods_")
                )
            ]
            if business:
                normalized = business

        requested_layer = self._extract_layer_filter(message)
        if requested_layer:
            layered = [
                item
                for item in normalized
                if self._table_layer(item.get("table_name") or "") == requested_layer
            ]
            if layered:
                normalized = layered

        bff = getattr(app_state, "_bff_client", None)
        bff_only = [item for item in normalized if not item.get("album_hit")]
        if bff is not None and bff_only and any(
            item.get("entity_guid") for item in bff_only
        ):
            await self._enrich_table_ref_counts(bff, bff_only)

        for item in normalized:
            if not item.get("layer"):
                item["layer"] = self._table_layer(item.get("table_name") or "")
        normalized.sort(
            key=lambda item: (
                1 if item.get("album_hit") else 0,
                int(item.get("ref_count") or 0),
            ),
            reverse=True,
        )
        return normalized

    def _raise_metadata_clarification(
        self,
        message: str,
        keyword: str,
        result: MetadataQueryResult,
        normalized: list[dict[str, Any]],
    ) -> MetricQueryPlan | None:
        """Reuse the existing clarification path but with provider output."""
        candidates = [
            {
                "table": item["full_name"],
                "comment": item.get("comment") or "",
                "ref_count": item.get("ref_count") or 0,
                "album_hit": bool(item.get("album_hit")),
                "album": item.get("album_name") or "",
                "category": item.get("album_category") or "",
                "layer": self._table_layer(item.get("table_name") or ""),
                "entity_guid": item.get("entity_guid") or "",
            }
            for item in normalized[:10]
        ]
        # Structured option chips for the frontend: a top-pick + the
        # top-9 album / ref_count ranked candidates + a free-text
        # fallback. The frontend renders ``type="pick_table"`` chips as
        # clickable options and always shows the free-text fallback.
        option_chips: list[dict[str, Any]] = []
        for idx, cand in enumerate(candidates):
            option_chips.append(
                {
                    "type": "pick_table",
                    "id": f"opt_{idx}",
                    "label": cand["table"],
                    "subtitle": cand.get("comment") or "",
                    "layer": cand.get("layer"),
                    "value": cand["table"],
                }
            )
        option_chips.append(
            {
                "type": "free_text",
                "id": "opt_custom",
                "label": "输入其它表名或完整 SQL",
                "placeholder": "project.table 或 SELECT ...",
            }
        )
        album_label = (
            (result.album or {}).get("name") if result.album else None
        ) or "未命中专辑"
        layer_counts: dict[str, int] = {}
        for item in normalized:
            layer = self._table_layer(item.get("table_name") or "")
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
        layer_hint = (
            "候选层级：" + " / ".join(
                f"{layer.upper()}={layer_counts[layer]}" for layer in layer_counts
            )
            if layer_counts
            else ""
        )
        option_chips: list[dict[str, Any]] = []
        for idx, cand in enumerate(candidates[:10]):
            option_chips.append(
                {
                    "type": "pick_table",
                    "id": f"opt_{idx}",
                    "label": cand["table"],
                    "subtitle": cand.get("comment") or "",
                    "layer": cand.get("layer"),
                    "value": cand["table"],
                }
            )
        option_chips.append(
            {
                "type": "free_text",
                "id": "opt_custom",
                "label": "输入其它表名或完整 SQL",
                "placeholder": "project.table 或 SELECT ...",
            }
        )
        raise QueryNeedsClarificationError(
            message,
            [],
            reason=(
                f"元数据搜表为“{keyword}”找到 {len(normalized)} 张候选表，"
                f"建议专辑：{album_label}。"
                + (f" {layer_hint}。" if layer_hint else " 请选择一张后再查询。")
                + " 可点选候选表，或点\"输入其它\"自定义回复。"
            ),
            knowledge_matches=candidates,
            clarifying_questions=[
                "请从候选表中选择一张，或直接回复完整表名（project.table）。",
                "如果目标是统计行数，也可以说：查 giikin.xxx 有多少条。",
                "回复 \"只要 dws / dwd / ods\" 可以只看对应分层。",
            ],
            option_chips=option_chips,
        )

    @staticmethod
    def _build_table_partition_clause_sync(table: str) -> tuple[str, str]:
        """Best-effort partition filter when running synchronously."""
        cols = AgentWorkflowService._partition_columns_for(table)
        if not cols:
            return "", "static_rule_no_partition"
        return (
            AgentWorkflowService._format_partition_clause(cols, None),
            "static_rule",
        )

    @staticmethod
    async def _enrich_table_ref_counts(
        bff: Any, tables: list[dict[str, Any]], *, concurrency: int = 8
    ) -> None:
        """Attach popularity ranking using upstream task counts when available."""
        if not tables:
            return
        semaphore = asyncio.Semaphore(concurrency)

        async def _one(item: dict[str, Any]) -> None:
            guid = str(item.get("entity_guid") or "")
            if not guid:
                return
            try:
                async with semaphore:
                    upstream = await bff.get_upstream_tasks(guid)
                item["ref_count"] = len(upstream or [])
            except Exception:
                # Keep zero; ranking still works with partial data.
                return

        await asyncio.gather(*[_one(item) for item in tables])

    async def _resolve_keyword_album(self, keyword: str) -> dict[str, Any] | None:
        """Find the best matching DataMap album for a Chinese keyword.

        Priority:
        1. Curated album id in ``_ASK_DOMAIN_ALBUM_HINTS`` (the user-confirmed
           authoritative album, e.g. 订单 → 订单数据（ods 层）订单 id=436).
        2. Best-effort DataMap album list scan, scored by name/description
           match + business tags (订单 / 模型汇总 / 汇总 / 社交电商).
        """
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return None
        normalized = (keyword or "").strip()
        if not normalized:
            return None

        # 1. Curated hint lookup first.
        hinted_id = _ASK_DOMAIN_ALBUM_HINTS.get(normalized)
        for tag, album_id in _ASK_DOMAIN_ALBUM_HINTS.items():
            if tag and tag in normalized and album_id:
                hinted_id = album_id
                break
        if hinted_id:
            cache: dict[str, tuple[float, dict[str, Any] | None]] = getattr(
                app_state, "_album_keyword_cache", {}
            )
            cached = cache.get(normalized)
            now = time.monotonic()
            if cached is not None and now - cached[0] < settings.ask_data_album_cache_seconds:
                return cached[1]
            try:
                detail = await bff.get_meta_album(hinted_id)
            except Exception as exc:
                logger.warning("get_meta_album(%s) 失败: %s", hinted_id, exc)
                detail = None
            if isinstance(detail, dict):
                hint = {
                    "album_id": hinted_id,
                    "name": str(detail.get("albumName") or detail.get("name") or ""),
                    "description": str(
                        detail.get("albumDesc") or detail.get("description") or ""
                    ),
                    "score": 100.0,
                }
                cache[normalized] = (now, hint)
                app_state._album_keyword_cache = cache
                return hint

        # 2. Fallback: scan the album list.
        cache = getattr(app_state, "_album_keyword_cache", {})
        now = time.monotonic()
        cached = cache.get(normalized)
        if cached is not None and now - cached[0] < settings.ask_data_album_cache_seconds:
            return cached[1]
        try:
            albums = await bff.list_meta_albums(page_size=100)
        except Exception as exc:
            logger.warning("list_meta_albums 失败: %s", exc)
            cache[normalized] = (now, None)
            app_state._album_keyword_cache = cache
            return None
        if not isinstance(albums, list) or not albums:
            cache[normalized] = (now, None)
            app_state._album_keyword_cache = cache
            return None

        best: dict[str, Any] | None = None
        best_score = -1.0
        for album in albums:
            name = str(album.get("albumName") or album.get("name") or "").strip()
            desc = str(album.get("albumDesc") or album.get("description") or "").strip()
            score = 0.0
            if name == normalized:
                score += 20.0
            if normalized and normalized in name:
                score += 8.0
            if name:
                for token in _CJK_RE.findall(name):
                    if token and token in normalized:
                        score += 3.0
            if normalized and normalized in desc:
                score += 1.5
            for tag, bonus in (
                ("订单", 4.0),
                ("模型汇总", 4.0),
                ("汇总", 2.0),
                ("社交电商", 1.0),
            ):
                if tag in name:
                    score += bonus
            if score > best_score:
                best_score = score
                best = {
                    "album_id": _as_int(album.get("id") or album.get("albumId")),
                    "name": name,
                    "description": desc,
                    "score": score,
                }
        result = best if best and best_score >= 4.0 else None
        cache[normalized] = (now, result)
        app_state._album_keyword_cache = cache
        return result

    @staticmethod
    def _ad_hoc_query_plan(sql: str, evidence: str, *, table: str = "") -> MetricQueryPlan:
        return MetricQueryPlan(
            sql=sql,
            metric_id="ad_hoc_query",
            metric_name="自主问数",
            metric_version=1,
            table=table,
            selection_evidence=[evidence],
            caliber={"source": "ad_hoc"},
        )

    async def _validate_semantic_plan_metadata(self, plan: MetricQueryPlan) -> None:
        ddl, metadata_channel = await self._load_certified_table_ddl(plan)
        if not ddl:
            raise QueryNeedsClarificationError(
                plan.metric_name,
                [],
                "认证表元数据无法通过 MaxCompute AK/SK 或 Cookie 通道读取，已阻止未经结构核验的查询。",
            )

        from dataworks_agent.governance.sql_lineage import parse_ddl_structure

        parsed = parse_ddl_structure(ddl)
        if parsed.get("parse_state") != "ok":
            raise QueryNeedsClarificationError(
                plan.metric_name,
                [],
                "认证表 DDL 解析失败，已阻止使用未经校验的指标口径。",
            )
        available = {str(item.get("name") or "").lower() for item in parsed.get("columns", [])}
        available.update(
            str(item.get("name") or "").lower() for item in parsed.get("partitions", [])
        )
        caliber = plan.caliber
        required = {str(caliber["measure"]["column"]).lower()}
        required.update(str(name).lower() for name in caliber.get("fixed_filters", {}))
        selected_names = set(plan.selected_dimensions)
        filter_ids = set((caliber.get("query_filters") or {}).keys())
        required.update(
            str(item.get("column") or "").lower()
            for item in caliber.get("dimensions", [])
            if str(item.get("name") or "") in selected_names
            or str(item.get("id") or item.get("column") or "") in filter_ids
        )
        freshness = caliber.get("freshness", {})
        required.update(
            str(freshness.get(key) or "").lower()
            for key in ("date_partition", "business_date", "hour_partition")
        )
        required.discard("")
        missing = sorted(required - available)
        if missing:
            raise QueryNeedsClarificationError(
                plan.metric_name,
                [],
                f"指标语义定义与真实表结构不一致，缺少字段：{', '.join(missing)}",
            )
        plan.metadata_validation = {
            "status": "passed",
            "channel": metadata_channel,
            "required_fields": sorted(required),
            "table": plan.table,
        }
        plan.selection_evidence.append(f"真实 DDL 字段与分区校验通过（{metadata_channel}）")

    async def _load_certified_table_ddl(self, plan: MetricQueryPlan) -> tuple[str | None, str]:
        project, _, table_name = plan.table.partition(".")
        mc = getattr(app_state, "_maxcompute_client", None)
        get_mc_ddl = getattr(mc, "get_table_ddl", None) if mc is not None else None
        if callable(get_mc_ddl):
            try:
                ddl = await get_mc_ddl(
                    table_name or project, project=project if table_name else None
                )
                if ddl:
                    return str(ddl), "maxcompute_ak_sk"
            except Exception as exc:
                logger.warning(
                    "MaxCompute 认证表元数据读取失败，尝试 Cookie 兜底: %s",
                    exc,
                )

        bff = getattr(app_state, "_bff_client", None)
        get_cookie_ddl = getattr(bff, "get_creation_ddl", None) if bff is not None else None
        if not callable(get_cookie_ddl):
            return None, "unavailable"
        try:
            ddl = await get_cookie_ddl(f"odps.{plan.table}")
        except Exception as exc:
            if not self._is_cookie_auth_error(exc):
                logger.warning("Cookie 认证表元数据读取失败: %s", exc)
                return None, "cookie_bff"
            refresh = await self._refresh_cookie_auth(bff)
            if refresh.get("status") not in {"success", "refreshed", "extracted_unverified"}:
                return None, "cookie_bff"
            ddl = await get_cookie_ddl(f"odps.{plan.table}")
        return (str(ddl), "cookie_bff") if ddl else (None, "cookie_bff")

    @staticmethod
    def _validate_readonly_sql(sql: str) -> None:
        statements = sqlglot.parse(sql, read="hive")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise ValueError("自主问数只允许单条 SELECT/WITH 查询")
        forbidden = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Alter,
            exp.Create,
            exp.Command,
        )
        if any(statement.find(kind) for statement in statements for kind in forbidden):
            raise ValueError("自主问数检测到写入或 DDL 操作，已阻止")

    @staticmethod
    def _enforce_query_limit(sql: str) -> str:
        statement = sqlglot.parse_one(sql, read="hive")
        limit = statement.args.get("limit")
        max_rows = settings.ask_data_default_limit
        if limit is not None and isinstance(limit.expression, exp.Literal):
            try:
                if int(limit.expression.this) <= max_rows:
                    return statement.sql(dialect="hive")
            except (TypeError, ValueError):
                pass
        return statement.limit(max_rows, copy=True).sql(dialect="hive")

    async def _execute_standard_oss_flow(
        self,
        *,
        message: str,
        params: dict[str, Any],
        mode: ExecutionMode,
        initialize_data: bool,
        publish: bool,
        client_ip: str,
    ) -> WorkflowResult:
        """Run the guarded standard OSS -> ODS -> DWD path.

        This path intentionally does not fall back to the generic OSS naming or
        AK/SK table creation: the standard source has a fixed ODS contract and
        its directory/table inspection must come from the Cookie/BFF channel.
        """
        from dataworks_agent.modeling.root_checker import RootChecker
        from dataworks_agent.modeling.standard_oss import (
            MATERIAL_REPORT_DWD_TABLE,
            MATERIAL_REPORT_ODS_TABLE,
            MATERIAL_REPORT_TEMPLATE_TASK_ID,
            ROOT_CHECKER_NAME,
            STANDARD_DWD_SQL_DIRECTORY,
            STANDARD_ODS_SQL_DIRECTORY,
            build_standard_material_report_artifacts,
            build_standard_material_report_ods_artifacts,
        )
        from dataworks_agent.services.ods_oss import (
            OssImportPipeline,
            infer_file_format,
            inspect_oss_directory_with_cookie,
            parse_oss_path,
        )

        # The standard naming contract is repository-owned. Do not ask the
        # user to repeat a DWD name that is deterministically defined by the
        # OSS standard; only explicit input may override it.
        requested_dwd_table = params.get("dwd_table")
        if not requested_dwd_table:
            candidate_table = str(params.get("table_name") or "").strip()
            # The NLU commonly extracts the ODS target as table_name. It must
            # not silently rename the deterministic standard DWD target.
            if candidate_table and not candidate_table.lower().startswith("ods_"):
                requested_dwd_table = candidate_table
        dwd_table = str(requested_dwd_table or MATERIAL_REPORT_DWD_TABLE).strip()
        dev_schema = "giikin"
        prod_schema = str(params.get("prod_schema") or "giikin").strip()
        oss_path = str(
            params.get("oss_path") or self._extractor.extract_oss_path(message) or ""
        ).strip()
        # Use the repository-owned standard directories by default; explicit
        # user values still override them.
        ods_sql_directory = str(
            params.get("ods_sql_directory")
            or self._extractor.extract_ods_sql_directory(message)
            or STANDARD_ODS_SQL_DIRECTORY
        ).strip()
        dwd_sql_directory = str(
            params.get("dwd_sql_directory")
            or self._extractor.extract_dwd_sql_directory(message)
            or STANDARD_DWD_SQL_DIRECTORY
        ).strip()
        explicit_granularity = params.get("granularity") or self._extractor.extract_granularity(
            message
        )
        if not explicit_granularity and (
            MATERIAL_REPORT_ODS_TABLE.endswith("_hour") or dwd_table.endswith("_hour")
        ):
            explicit_granularity = "hour"
        missing: list[str] = []
        if not oss_path:
            question = "Please provide the OSS directory in the form oss://bucket/prefix/."
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[{"step": "standard_oss_context_gate", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["oss_path"],
                    "ods_table": MATERIAL_REPORT_ODS_TABLE,
                    "template_task_id": str(
                        params.get("template_task_id")
                        or params.get("task_id")
                        or MATERIAL_REPORT_TEMPLATE_TASK_ID
                    ),
                    "publish_gate": "not_requested",
                },
            )
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            question = "标准 OSS 流程必须通过 Cookie/BFF 检查 OSS 目录和外部表；请先启动并登录 Cookie 会话。"
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[{"step": "cookie_bff_preflight", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["cookie_bff"],
                    "ods_table": MATERIAL_REPORT_ODS_TABLE,
                    "dwd_table": dwd_table,
                    "template_task_id": str(
                        params.get("template_task_id")
                        or params.get("task_id")
                        or MATERIAL_REPORT_TEMPLATE_TASK_ID
                    ),
                    "publish_gate": "not_requested",
                },
            )

        try:
            location = parse_oss_path(oss_path)
        except ValueError as exc:
            question = f"OSS 目录格式无法解析：{exc}。请提供形如 oss://bucket/prefix/ 的目录。"
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[{"step": "inspect_oss_directory", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["oss_path"],
                    "ods_table": MATERIAL_REPORT_ODS_TABLE,
                    "dwd_table": dwd_table,
                    "template_task_id": str(
                        params.get("template_task_id")
                        or params.get("task_id")
                        or MATERIAL_REPORT_TEMPLATE_TASK_ID
                    ),
                    "publish_gate": "not_requested",
                },
            )

        requested_format = str(
            params.get("file_format") or self._extractor.extract_file_format(message) or "json"
        )
        file_format = infer_file_format(str(location["canonical_uri"]), requested_format) or "json"
        directory = await inspect_oss_directory_with_cookie(
            bff, str(location["canonical_uri"]), file_format
        )
        if not directory.get("success") or not (directory.get("directory_check") or {}).get(
            "success"
        ):
            question = "Cookie 检查未确认 OSS 目录、数据源、外部表或 LOCATION；请核对 DataWorks OSS 配置和目录。"
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[{"step": "inspect_oss_directory", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["managed_oss_directory"],
                    "ods_table": MATERIAL_REPORT_ODS_TABLE,
                    "dwd_table": dwd_table,
                    "template_task_id": str(
                        params.get("template_task_id")
                        or params.get("task_id")
                        or MATERIAL_REPORT_TEMPLATE_TASK_ID
                    ),
                    "directory_check": directory.get("directory_check") or {},
                    "source_discovery": directory,
                    "publish_gate": "not_requested",
                },
            )

        if not ods_sql_directory:
            missing.append("ods_sql_directory")
        if not dwd_sql_directory:
            missing.append("dwd_sql_directory")
        if explicit_granularity not in {"day", "hour"}:
            missing.append("granularity")
        if missing:
            questions = []
            if "ods_sql_directory" in missing:
                questions.append("Provide the DataWorks ODS SQL directory.")
            if "dwd_sql_directory" in missing:
                questions.append("Provide the DataWorks DWD SQL directory.")
            if "granularity" in missing:
                questions.append("Confirm whether the DWD table is day or hour granularity.")
            actions: list[dict[str, Any]] = []
            if "granularity" in missing:
                actions.extend(
                    [
                        {
                            "id": "granularity_hour",
                            "label": "hour table",
                            "value": "hour",
                            "payload": {"params": {"granularity": "hour"}},
                        },
                        {
                            "id": "granularity_day",
                            "label": "day table",
                            "value": "day",
                            "payload": {"params": {"granularity": "day"}},
                        },
                    ]
                )
            return WorkflowResult(
                True,
                "Standard OSS modeling is waiting for the missing context: " + " ".join(questions),
                "forward_modeling",
                mode,
                steps=[{"step": "standard_oss_context_gate", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": questions,
                    "missing_context": missing,
                    "next_step": "confirm_sql_directories_and_granularity",
                    "next_actions": actions,
                    "allow_custom_input": True,
                    "custom_input_hint": "Enter ODS SQL directory, DWD SQL directory, and day/hour in one message.",
                    "ods_table": MATERIAL_REPORT_ODS_TABLE,
                    "dwd_table": dwd_table,
                    "template_task_id": str(
                        params.get("template_task_id")
                        or params.get("task_id")
                        or MATERIAL_REPORT_TEMPLATE_TASK_ID
                    ),
                    "dev_schema": dev_schema,
                    "ods_sql_directory": ods_sql_directory,
                    "dwd_sql_directory": dwd_sql_directory,
                    "prod_schema": prod_schema,
                    "publish_gate": "not_requested",
                },
            )

        profile = dict(params.get("data_profile") or {})
        if not profile.get("columns") and params.get("columns"):
            profile["columns"] = list(params["columns"])
        if not profile.get("columns") and profile.get("records"):
            from dataworks_agent.services.ods_oss.schema_discovery import infer_json_columns

            try:
                profile["columns"] = infer_json_columns(
                    [record for record in profile["records"] if isinstance(record, dict)]
                )
            except (TypeError, ValueError):
                profile["columns"] = []
        if not profile.get("columns") or all(
            str(c.get("name") if isinstance(c, dict) else c).lower() == "json_data"
            for c in profile["columns"]
        ):
            from dataworks_agent.services.ods_oss import discover_oss_schema_with_fallback

            sampled = await discover_oss_schema_with_fallback(
                bff,
                str(location["canonical_uri"]),
                file_format,
                sample_managed_json=True,
                managed_result=directory,
            )
            if sampled.get("success") and sampled.get("columns"):
                profile = dict(sampled)
            else:
                question = "无法从 OSS 样本探查 JSON/数据字段；请提供真实样本或 data_profile。"
                return WorkflowResult(
                    True,
                    question,
                    "forward_modeling",
                    mode,
                    steps=[{"step": "profile_json_sample", "status": "needs_context"}],
                    data={
                        "standard": "tiktok_smart_plus_material_report",
                        "needs_clarification": True,
                        "clarifying_questions": [question],
                        "missing_context": ["data_profile"],
                        "next_step": "provide_data_profile",
                        "next_actions": [
                            {
                                "id": "provide_data_profile",
                                "label": "\u7c98\u8d34 JSON \u6837\u672c",
                                "value": "data_profile",
                                "requires_custom_input": True,
                            },
                            {
                                "id": "provide_data_profile_columns",
                                "label": "\u8f93\u5165 data_profile.columns",
                                "value": "data_profile_columns",
                                "requires_custom_input": True,
                            },
                        ],
                        "allow_custom_input": True,
                        "custom_input_hint": '\u8bf7\u5728\u4e0b\u65b9\u8f93\u5165\u6846\u7c98\u8d34\u771f\u5b9e JSON \u6837\u672c\uff08\u5bf9\u8c61\u6216\u6570\u7ec4\uff09\uff0c\u6216\u8f93\u5165 data_profile\uff0c\u4f8b\u5982\uff1a{"columns":[{"name":"material_id","type":"STRING"}]}\uff0c\u7136\u540e\u53d1\u9001\u3002',
                        "directory_check": directory["directory_check"],
                        "sample_discovery": sampled,
                        "publish_gate": "not_requested",
                    },
                )

        observed_columns = list(profile.get("columns") or [])
        from dataworks_agent.modeling.standard_oss import (
            candidate_logical_primary_keys,
            normalize_json_field_mappings,
        )

        mappings_raw = params.get("json_field_mappings") or params.get("field_mappings")
        if not mappings_raw:
            suggestions = [
                {
                    "json_key": str(c.get("name") or c),
                    "target_name": str(c.get("name") or c),
                    "type": str(c.get("type") or "STRING"),
                }
                for c in observed_columns
                if str(c.get("name") if isinstance(c, dict) else c).lower()
                not in {"json_data", "dt", "ht"}
            ]
            question = "请确认 JSON 字段到 DWD 字段的映射。"
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[{"step": "confirm_json_field_mapping", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["json_field_mappings"],
                    "observed_columns": observed_columns,
                    "mapping_candidates": suggestions,
                    "next_step": "confirm_json_field_mapping",
                    "next_actions": [
                        {
                            "id": "use_observed_json_fields",
                            "label": "Use all observed fields",
                            "value": "use_observed_json_fields",
                            "payload": {"params": {"json_field_mappings": suggestions}},
                        }
                    ],
                    "allow_custom_input": True,
                    "custom_input_hint": "Enter JSON field mapping as json_key:target_name:type, separated by commas.",
                    "candidate_logical_primary_keys": candidate_logical_primary_keys(
                        observed_columns, profile
                    ),
                    "directory_check": directory["directory_check"],
                    "publish_gate": "not_requested",
                },
            )

        try:
            mappings = normalize_json_field_mappings(mappings_raw)
        except (TypeError, ValueError) as exc:
            return WorkflowResult(
                False,
                "JSON 字段映射无法解析为 DWD 字段。",
                "forward_modeling",
                mode,
                errors=[str(exc)],
            )
        if not mappings:
            return WorkflowResult(
                True,
                "请提供 JSON 到 DWD 的字段映射。",
                "forward_modeling",
                mode,
                data={
                    "needs_clarification": True,
                    "missing_context": ["json_field_mappings"],
                    "next_step": "confirm_json_field_mapping",
                    "next_actions": [],
                    "allow_custom_input": True,
                    "custom_input_hint": "Provide JSON field mappings explicitly.",
                },
            )

        candidates = candidate_logical_primary_keys(observed_columns, profile)
        logical_keys = params.get("logical_primary_keys")
        if not logical_keys:
            question = "请确认 DWD 的逻辑主键；候选：" + (
                " + ".join("+".join(c) for c in candidates)
                if candidates
                else "暂无可靠候选，请根据真实样本确认。"
            )
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[{"step": "confirm_logical_primary_key", "status": "needs_context"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["logical_primary_keys"],
                    "candidate_logical_primary_keys": candidates,
                    "next_step": "confirm_logical_primary_key",
                    "next_actions": [
                        {
                            "id": "logical_key_" + "_".join(candidate),
                            "label": " + ".join(candidate),
                            "value": " + ".join(candidate),
                            "payload": {"params": {"logical_primary_keys": candidate}},
                        }
                        for candidate in candidates[:5]
                    ],
                    "allow_custom_input": True,
                    "custom_input_hint": "Enter one or more logical primary key columns, separated by commas.",
                    "observed_columns": observed_columns,
                    "directory_check": directory["directory_check"],
                    "publish_gate": "not_requested",
                },
            )

        root_result = await RootChecker().check_fields(
            [mapping.target_name for mapping in mappings]
        )
        if not root_result.passed:
            return WorkflowResult(
                False,
                "DWD 字段未通过线上词根校验，已阻断 DDL/任务创建。",
                "forward_modeling",
                mode,
                steps=[{"step": "dmr_pub_column_check", "status": "failed"}],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "checker": ROOT_CHECKER_NAME,
                    "root_check": root_result.model_dump(),
                    "directory_check": directory["directory_check"],
                    "publish_gate": "not_requested",
                },
                errors=[root_result.summary],
            )

        try:
            dwd_artifacts = build_standard_material_report_artifacts(
                dwd_table=dwd_table,
                field_mappings=mappings_raw,
                ods_table=MATERIAL_REPORT_ODS_TABLE,
                template_task_id=str(
                    params.get("template_task_id")
                    or params.get("task_id")
                    or MATERIAL_REPORT_TEMPLATE_TASK_ID
                ),
                schedule_minute=int(params.get("schedule_minute") or 3),
                dev_schema=dev_schema,
                prod_schema=prod_schema,
                granularity=str(explicit_granularity),
                logical_primary_keys=logical_keys,
                data_profile=profile,
                ods_sql_directory=ods_sql_directory,
                dwd_sql_directory=dwd_sql_directory,
            )
            ods_artifacts = build_standard_material_report_ods_artifacts(
                oss_path=str(location["location_uri"]),
                file_format=file_format,
                dev_schema="giikin",
                prod_schema=prod_schema,
                ods_sql_directory=ods_sql_directory,
                external_table=str(
                    directory.get("table_name") or "tiktok_smart_plus_material_report"
                ),
                external_project="giikin_develop",
                source_partition_value=str(params.get("source_partition_value") or "${gmtdate}"),
            )
        except (TypeError, ValueError) as exc:
            return WorkflowResult(
                False,
                "标准 OSS ODS/DWD 产物生成失败。",
                "forward_modeling",
                mode,
                errors=[str(exc)],
            )

        dwd_artifacts["validation"]["root_check"] = root_result.model_dump()
        dwd_artifacts["validation"]["root_source"] = root_result.source
        dwd_artifacts["validation"]["checker"] = ROOT_CHECKER_NAME
        dwd_artifacts["validation"]["passed"] = bool(
            root_result.passed and dwd_artifacts["validation"]["ddl_check"]["passed"]
        )
        if not dwd_artifacts["validation"]["passed"]:
            return WorkflowResult(
                False,
                "DWD DDL 校验未通过，已阻断后续执行。",
                "forward_modeling",
                mode,
                data={"standard": dwd_artifacts, "ods": ods_artifacts},
                errors=["DDL validation failed"],
            )

        artifacts = {
            "ods": ods_artifacts,
            "dwd": dwd_artifacts,
            "directory_check": directory["directory_check"],
            "sample_profile": profile,
        }
        if mode == "plan":
            return WorkflowResult(
                True,
                "已通过 Cookie 检查并生成 ODS/DWD 产物；计划模式不写入 DataWorks，生产变更仍需 Publish Gate。",
                "forward_modeling",
                mode,
                steps=[
                    {"step": "inspect_oss_directory", "status": "completed"},
                    {"step": "profile_json_sample", "status": "completed"},
                    {"step": "dmr_pub_column_check", "status": "completed"},
                    {"step": "build_standard_ods_dwd_artifacts", "status": "completed"},
                ],
                artifacts=[artifacts],
                data={
                    "standard": "tiktok_smart_plus_material_report",
                    "artifacts": artifacts,
                    "publish_gate": "required_for_publish",
                },
            )

        dev_ods = await self._create_table_cookie(
            ods_artifacts["environment_artifacts"]["dev"]["ddl"],
            dev_schema,
            MATERIAL_REPORT_ODS_TABLE,
        )
        dev_dwd = await self._create_table_cookie(
            dwd_artifacts["environment_artifacts"]["dev"]["ddl"], dev_schema, dwd_table
        )
        if dev_ods.get("status") == "failed" or dev_dwd.get("status") == "failed":
            return WorkflowResult(
                False,
                "Cookie 建开发表失败。",
                "forward_modeling",
                mode,
                data={"artifacts": artifacts, "dev_tables": {"ods": dev_ods, "dwd": dev_dwd}},
                errors=[str(dev_ods.get("error") or dev_dwd.get("error"))],
            )

        pipeline = await OssImportPipeline(bff).run(
            oss_path=str(location.get("location_uri") or location["canonical_uri"]),
            target_table=MATERIAL_REPORT_ODS_TABLE,
            file_format="json",
            schedule_type="hour",
            node_path_prefix=ods_sql_directory,
            schedule_minute=int(params.get("schedule_minute") or 3),
            publish=False,
            ingestion_mode="raw_json_text",
            root_node_uuid=str(
                params.get("root_node_uuid")
                or settings.dataworks_default_root_node_uuid
                or settings.root_check_node_uuid
                or ""
            ),
            output_ref=f"{dev_schema}.{MATERIAL_REPORT_ODS_TABLE}",
        )
        if not pipeline.get("success"):
            return WorkflowResult(
                False,
                "ODS SQL 节点创建或调度配置失败",
                "forward_modeling",
                mode,
                data={
                    "artifacts": artifacts,
                    "dev_tables": {"ods": dev_ods, "dwd": dev_dwd},
                    "ods_pipeline": pipeline,
                },
                errors=[
                    str(
                        (pipeline.get("steps") or {}).get("configure_schedule", {}).get("error")
                        or (pipeline.get("steps") or {}).get("create_node", {}).get("error")
                        or pipeline.get("error")
                        or "ODS pipeline failed"
                    )
                ],
            )

        dwd_pipeline = await self._create_standard_dwd_pipeline_cookie(
            bff=bff,
            dwd_artifacts=dwd_artifacts,
            dwd_sql_directory=dwd_sql_directory,
            dev_schema=dev_schema,
            ods_table=MATERIAL_REPORT_ODS_TABLE,
            dwd_table=dwd_table,
            granularity=str(explicit_granularity),
            schedule_minute=int(params.get("schedule_minute") or 3),
        )
        if not dwd_pipeline.get("success"):
            return WorkflowResult(
                False,
                "DWD SQL 节点创建、调度或 ODS→DWD 依赖配置失败",
                "forward_modeling",
                mode,
                data={
                    "artifacts": artifacts,
                    "dev_tables": {"ods": dev_ods, "dwd": dev_dwd},
                    "ods_pipeline": pipeline,
                    "dwd_pipeline": dwd_pipeline,
                },
                errors=[str(dwd_pipeline.get("error") or "DWD pipeline failed")],
            )

        result_data: dict[str, Any] = {
            "standard": "tiktok_smart_plus_material_report",
            "artifacts": artifacts,
            "dev_tables": {"ods": dev_ods, "dwd": dev_dwd},
            "prod_tables": {
                "ods": {
                    "status": "approval_required",
                    "ddl": ods_artifacts["environment_artifacts"]["prod"]["ddl"],
                },
                "dwd": {
                    "status": "approval_required",
                    "ddl": dwd_artifacts["environment_artifacts"]["prod"]["ddl"],
                },
            },
            "ods_pipeline": pipeline,
            "dwd_pipeline": dwd_pipeline,
            "schedule": dwd_artifacts["schedule"],
            "dependency_plan": dwd_artifacts["dependency_plan"],
            "template_task_id": dwd_artifacts["template_task_id"],
            "checker": ROOT_CHECKER_NAME,
            "publish_gate": "not_requested",
            "next_actions": [
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
            ],
            "allow_custom_input": True,
            "custom_input_hint": "\u53ef\u4ee5\u8f93\u5165 SQL\u3001\u8c03\u5ea6\u3001\u53d1\u5e03\u5ba1\u6279\u6216\u5176\u4ed6\u540e\u7eed\u8981\u6c42\u3002",
        }
        steps = [
            {"step": "inspect_oss_directory", "status": "completed"},
            {"step": "profile_json_sample", "status": "completed"},
            {"step": "dmr_pub_column_check", "status": "completed"},
            {"step": "create_dev_tables_cookie", "status": "completed"},
            {"step": "create_ods_sql_node_cookie", "status": "completed"},
            {"step": "configure_ods_schedule_cookie", "status": "completed"},
            {"step": "create_dwd_sql_node_cookie", "status": "completed"},
            {"step": "configure_dwd_schedule_cookie", "status": "completed"},
            {"step": "configure_ods_to_dwd_dependency_cookie", "status": "completed"},
            {"step": "create_prod_tables", "status": "approval_required"},
            {"step": "publish_gate", "status": "skipped"},
        ]
        message_text = "Standard OSS -> ODS -> DWD flow completed: Cookie created ODS/DWD tables and SQL nodes in giikin_develop, configured the ODS->DWD dependency, and left production artifacts behind the Publish Gate."

        if publish:
            from dataworks_agent.runtime.publish_gate import PublishGate

            gate = getattr(app_state, "_publish_gate", None) or PublishGate()
            app_state._publish_gate = gate
            request = await gate.interrupt_for_approval(
                run_id=f"agent_{uuid.uuid4().hex[:12]}",
                session_id=client_ip,
                table_name=dwd_table,
                change_type="create",
                payload={"standard": "tiktok_smart_plus_material_report", "artifacts": artifacts},
                context={"mode": mode},
            )
            result_data["publish_request"] = request.__dict__
            result_data["publish_gate"] = "approval_required"
            steps[-1]["status"] = "approval_required"
            message_text += f" 已创建发布审批请求 {request.request_id}，审批后才能发布生产。"

        return WorkflowResult(
            True,
            message_text,
            "forward_modeling",
            mode,
            steps=steps,
            artifacts=[artifacts],
            data=result_data,
        )

    async def _create_standard_dwd_pipeline_cookie(
        self,
        *,
        bff: Any,
        dwd_artifacts: dict[str, Any],
        dwd_sql_directory: str,
        dev_schema: str,
        ods_table: str,
        dwd_table: str,
        granularity: str,
        schedule_minute: int,
    ) -> dict[str, Any]:
        """Create the standard DWD SQL node, schedule, and ODS dependency via Cookie/BFF."""
        if not str(dwd_sql_directory or "").strip():
            return {"success": False, "error": "DWD SQL 节点目录不能为空"}
        sql = str(dwd_artifacts.get("environment_artifacts", {}).get("dev", {}).get("sql") or "")
        if not sql:
            return {"success": False, "error": "DWD SQL 内容不能为空"}

        node_path = generate_node_path(dwd_sql_directory.strip().rstrip("/"), dwd_table)
        node_uuid = await bff.create_node(dwd_table, node_path, language="odps-sql")
        if not node_uuid:
            return {
                "success": False,
                "error": getattr(bff, "last_error", None) or "DWD create_node failed",
                "node_path": node_path,
            }
        if not await bff.update_node(node_uuid, sql):
            return {
                "success": False,
                "error": getattr(bff, "last_error", None) or "DWD update_node failed",
                "node_uuid": node_uuid,
                "node_path": node_path,
            }

        is_hour = granularity == "hour"
        cycle_type = "NotDaily" if is_hour else "Daily"
        cron = generate_cron(
            "hour" if is_hour else "day", hour=0 if is_hour else 3, minute=schedule_minute
        )
        parameters = DWD_SQL_PARAMETERS if is_hour else DAILY_SQL_PARAMETERS
        upstream = f"giikin.{ods_table}"
        dependencies = [
            {
                "type": "Normal",
                "sourceType": "Manual",
                "output": upstream,
                "refTableName": upstream,
            },
            {"type": "CrossCycleDependsOnSelf"},
        ]
        vertex_config = {
            "trigger": {
                "type": "Scheduler",
                "cron": cron,
                "cycleType": cycle_type,
                "startTime": "1970-01-01 00:00:00",
                "endTime": "9999-01-01 00:00:00",
                "timezone": "Asia/Shanghai",
            },
            "script": {"parameters": parameters},
            "strategy": {"instanceMode": "Immediately"},
            "dependencies": dependencies,
        }
        scheduled = await bff.update_vertex(node_uuid, vertex_config)
        if not scheduled:
            return {
                "success": False,
                "error": getattr(bff, "last_error", None) or "DWD update_vertex failed",
                "node_uuid": node_uuid,
                "node_path": node_path,
                "cron": cron,
            }

        dependency_status = "inline"
        if hasattr(bff, "_put"):
            try:
                dependency_response = await bff._put(
                    "ide/addNodeDependencies",
                    {
                        "projectId": getattr(bff, "project_id", None),
                        "uuid": node_uuid,
                        "dependencies": dependencies,
                    },
                )
                if dependency_response.get("code") != 200:
                    return {
                        "success": False,
                        "error": getattr(bff, "last_error", None)
                        or "DWD dependency configuration failed",
                        "node_uuid": node_uuid,
                        "node_path": node_path,
                        "cron": cron,
                        "dependencies": dependencies,
                    }
                dependency_status = "cookie_bff"
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"DWD dependency configuration failed: {exc}",
                    "node_uuid": node_uuid,
                    "node_path": node_path,
                    "cron": cron,
                    "dependencies": dependencies,
                }

        return {
            "success": True,
            "node_uuid": node_uuid,
            "node_path": node_path,
            "sql": sql,
            "cron": cron,
            "cycle_type": cycle_type,
            "parameters": parameters,
            "dependencies": dependencies,
            "dependency_status": dependency_status,
            "publish": "saved_not_deployed",
        }

    async def _create_table_cookie(
        self, ddl: str, schema: str, target_table: str
    ) -> dict[str, Any]:
        """Create one MaxCompute table through the Cookie/BFF IDA SQL channel."""
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return {"status": "failed", "error": "Cookie/BFF 不可用"}
        from dataworks_agent.services.ods_di.di_config import (
            inject_schema_prefix_in_ddl,
            strip_leading_drop_table,
        )

        try:
            existing = await bff.get_creation_ddl(f"odps.{schema}.{target_table}")
            if existing:
                return {
                    "status": "skipped",
                    "reason": "table_exists",
                    "schema": schema,
                    "table": target_table,
                }
            ddl_exec = strip_leading_drop_table(inject_schema_prefix_in_ddl(ddl, schema))
            job_code = await bff.execute_sql_ida(ddl_exec)
            cookie_error = getattr(bff, "last_error", None) or "execute_sql_ida failed"
            if job_code:
                created = await bff.wait_ida_job(job_code, max_retry=36, interval=5)
                if created:
                    return {
                        "status": "created",
                        "schema": schema,
                        "table": target_table,
                        "job_code": job_code,
                        "auth": "cookie_bff_ida",
                    }
                cookie_error = getattr(bff, "last_error", None) or "wait_ida_job failed"

            # IDA can reject DATASOURCE_CONFIG even when the regular IDE SQL
            # executor is allowed for the same signed-in user. Try that Cookie
            # route before falling back to the separately authorized dev client.
            v3_job_code = await bff.execute_sql(ddl_exec)
            if v3_job_code:
                created = await bff.wait_job(v3_job_code, max_retry=36, interval=5)
                if created:
                    return {
                        "status": "created",
                        "schema": schema,
                        "table": target_table,
                        "job_code": v3_job_code,
                        "auth": "cookie_bff_v3",
                    }
                cookie_error = getattr(bff, "last_error", None) or "wait_job failed"
            else:
                cookie_error = (
                    f"{cookie_error}; execute_sql failed: "
                    f"{getattr(bff, 'last_error', None) or 'no job code'}"
                )

            # Some Cookie sessions can inspect DataWorks but are not allowed to
            # execute SQL through DATASOURCE_CONFIG. The workspace's documented
            # capability matrix allows AK/SK MaxCompute DDL in dev, so use it as
            # a bounded fallback instead of reporting a false hard failure.
            mc = getattr(app_state, "_maxcompute_client", None)
            if mc is not None:
                try:
                    ddl_result = await mc.execute_ddl(ddl_exec)
                except Exception as exc:
                    ddl_result = None
                    fallback_error = str(exc)
                else:
                    fallback_error = (
                        getattr(ddl_result, "error", None) or "AK/SK execute_ddl failed"
                    )
                if ddl_result is not None and getattr(ddl_result, "success", False):
                    return {
                        "status": "created",
                        "schema": schema,
                        "table": target_table,
                        "instance_id": getattr(ddl_result, "instance_id", ""),
                        "auth": "maxcompute_ak_sk_fallback",
                        "fallback_reason": str(cookie_error),
                    }
                cookie_error = f"{cookie_error}; AK/SK fallback: {fallback_error}"
            return {
                "status": "failed",
                "error": str(cookie_error),
                "job_code": job_code or None,
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "schema": schema, "table": target_table}

    async def _forward_model(
        self,
        message: str,
        params: dict[str, Any],
        mode: ExecutionMode,
        *,
        initialize_data: bool,
        publish: bool,
        client_ip: str,
    ) -> WorkflowResult:
        tables = self._extractor.extract_table_names(message)
        by_layer: dict[str, list[str]] = {layer: [] for layer in ("ods", "dwd", "dim", "dws")}
        for table in tables:
            layer = table.split("_", 1)[0].lower()
            if layer in by_layer:
                assert_safe_table_name(table)
                by_layer[layer].append(table)
        # Explicit ODS/DWD names are authoritative. In particular, the standard
        # TikTok material-report ODS must never be replaced by a guessed OSS name.
        explicit_ods = params.get("ods_table")
        explicit_dwd = params.get("dwd_table") or params.get("table_name")
        for layer, table_name in (("ods", explicit_ods), ("dwd", explicit_dwd)):
            if isinstance(table_name, str) and table_name and table_name not in by_layer[layer]:
                assert_safe_table_name(table_name)
                by_layer[layer].append(table_name)
                tables.append(table_name)
        source_table = params.get("source_table") or self._extractor.extract_source_table(message)
        datasource = params.get("datasource_name") or self._extractor.extract_datasource_name(
            message
        )
        source_type = (
            params.get("source_type") or self._extractor.extract_source_type(message) or "mysql"
        ).lower()
        oss_path = params.get("oss_path") or self._extractor.extract_oss_path(message)
        granularity = (
            params.get("granularity") or self._extractor.extract_granularity(message) or "day"
        )
        if source_type == "oss" and not oss_path:
            identifier = str(datasource or "").strip()
            subject = f" `{identifier}`" if identifier else ""
            question = (
                f"已识别为 OSS 建模，但{subject} 还不能定位到 OSS 对象。"
                "请补充完整 oss:// 路径；Agent 会优先复用 DataWorks 托管元数据，必要时再用本地 OSS SDK 受限探测字段。"
                "如果目录没有扩展名，可同时说明“文件格式是 JSON”。"
            )
            return WorkflowResult(
                True,
                question,
                "forward_modeling",
                mode,
                steps=[
                    {
                        "step": "confirm_oss_path_format_and_schema",
                        "status": "needs_context",
                        "phase": "understand",
                    }
                ],
                data={
                    "capabilities": self.capability_status(),
                    "source_type": source_type,
                    "needs_clarification": True,
                    "clarifying_questions": [question],
                    "missing_context": ["oss_path"],
                    "generated_tables": {},
                    "publish_gate": "not_requested",
                },
            )
        if source_type == "oss":
            from dataworks_agent.modeling.standard_oss import is_standard_material_report

            standard_params = dict(params)
            standard_params.setdefault(
                "ods_table", explicit_ods or (by_layer["ods"][0] if by_layer["ods"] else "")
            )
            if is_standard_material_report(standard_params):
                return await self._execute_standard_oss_flow(
                    message=message,
                    params=standard_params,
                    mode=mode,
                    initialize_data=initialize_data,
                    publish=publish,
                    client_ip=client_ip,
                )
        if source_type == "oss" and not source_table:
            source_table = datasource or self._oss_source_name(str(oss_path))
        generated_tables: dict[str, str] = {}
        if not any(by_layer.values()) and source_table and self._requests_full_chain(message):
            generated_tables = self._derive_forward_table_names(
                source_table=source_table,
                datasource=datasource or (source_table if source_type == "oss" else "source"),
                source_type=source_type,
                granularity=granularity,
            )
            for layer, table_name in generated_tables.items():
                by_layer[layer].append(table_name)
            tables.extend(generated_tables.values())
        schedule_minute = params.get("schedule_minute") or 1
        plan = self._build_forward_plan(
            by_layer, source_table, datasource, initialize_data, source_type
        )
        if mode == "plan":
            return WorkflowResult(
                True,
                "已生成 ODS→DWD/DIM→DWS 全链路开发执行计划；切换到开发执行即可建表、建草稿节点并初始化。",
                "forward_modeling",
                mode,
                steps=plan,
                data={
                    "capabilities": self.capability_status(),
                    "publish_gate": "required_for_publish",
                    "source_type": source_type,
                    "generated_tables": generated_tables,
                },
            )

        execution_steps = [dict(step) for step in plan]
        clients_ready = bool(
            getattr(app_state, "_node_client", None)
            and getattr(app_state, "_maxcompute_client", None)
        )
        self._set_step_status(
            execution_steps,
            "credential_and_cookie_health",
            "completed" if clients_ready else "failed",
        )
        if not clients_ready:
            return WorkflowResult(
                False,
                "AK/SK 执行底座未就绪，无法进行开发环境真实写入。",
                "forward_modeling",
                mode,
                steps=execution_steps,
                data={"capabilities": self.capability_status()},
                errors=["execution clients unavailable"],
            )
        if not source_table and source_type != "oss":
            return WorkflowResult(
                False,
                "缺少源表。请在一句话中说明数据源和源表。",
                "forward_modeling",
                mode,
                steps=execution_steps,
                errors=["missing source_table"],
            )
        if not any(by_layer.values()):
            return WorkflowResult(
                False,
                "请在一句话中给出至少一个 ods_/dwd_/dim_/dws_ 目标表名。",
                "forward_modeling",
                mode,
                steps=execution_steps,
                errors=["missing target tables"],
            )

        preflight = await self._official_datasource_preflight(
            None if source_type == "oss" else datasource
        )
        self._set_step_status(execution_steps, "official_mcp_health", preflight["status"])
        executed: list[dict[str, Any]] = []
        upstream = source_table or ""
        if by_layer["ods"]:
            ods_table = by_layer["ods"][0]
            ods_result = await self._execute_ods(
                message=message,
                params=params,
                source_type=source_type,
                datasource=datasource,
                source_table=source_table or "",
                target_table=ods_table,
                granularity=granularity,
                schedule_minute=schedule_minute,
                initialize=initialize_data,
            )
            needs_context = bool(ods_result.get("needs_context"))
            if ods_result.get("success"):
                executed.append({"layer": "ODS", "table": ods_table, "result": ods_result})
            self._set_step_status(
                execution_steps,
                "discover_source_schema",
                "completed"
                if ods_result.get("success")
                else "needs_context"
                if needs_context
                else "failed",
            )
            self._set_step_status(
                execution_steps,
                "create_ods_table_and_source_node",
                "completed"
                if ods_result.get("success")
                else "skipped"
                if needs_context
                else "failed",
            )
            if initialize_data:
                init_status = (
                    "completed"
                    if source_type not in {"oss", "hologres", "holo", "realtime"}
                    and ods_result.get("success")
                    else "skipped"
                )
                self._set_step_status(execution_steps, "initialize_ods_data", init_status)
            if not ods_result.get("success"):
                if needs_context:
                    question = str(
                        ods_result.get("clarifying_question")
                        or "OSS 字段探测受阻。请修复读取权限，或直接补充字段定义后继续。"
                    )
                    return WorkflowResult(
                        True,
                        str(
                            ods_result.get("message") or "OSS 源已识别，但字段探测需要补充上下文。"
                        ),
                        "forward_modeling",
                        mode,
                        steps=execution_steps,
                        data={
                            "executed": executed,
                            "attempted": [{"layer": "ODS", "table": ods_table}],
                            "official_mcp_preflight": preflight,
                            "source_type": source_type,
                            "source_discovery": ods_result.get("schema_discovery") or {},
                            "needs_clarification": True,
                            "clarifying_questions": [question],
                            "missing_context": ods_result.get("missing_context")
                            or ["managed_source_or_columns"],
                            "generated_tables": generated_tables,
                            "publish_gate": "not_requested",
                        },
                    )
                return WorkflowResult(
                    False,
                    "ODS 建表、节点或初始化失败，已停止下游建模。",
                    "forward_modeling",
                    mode,
                    steps=execution_steps,
                    data={"executed": executed, "official_mcp_preflight": preflight},
                    errors=[str(ods_result.get("error") or "ODS execution failed")],
                )
            upstream = ods_table

        for layer in ("dwd", "dim"):
            for table in by_layer[layer]:
                layer_result = await self._deploy_warehouse_layer(
                    layer.upper(), upstream, table, granularity, schedule_minute
                )
                executed.append({"layer": layer.upper(), "table": table, "result": layer_result})
                self._set_step_status(
                    execution_steps,
                    f"create_{layer}_tables_nodes_schedule",
                    "completed" if layer_result.get("success") else "failed",
                )
                if not layer_result.get("success"):
                    return WorkflowResult(
                        False,
                        f"{layer.upper()} 开发任务创建失败。",
                        "forward_modeling",
                        mode,
                        steps=execution_steps,
                        data={"executed": executed, "official_mcp_preflight": preflight},
                        errors=[f"{layer} execution failed"],
                    )
                if layer == "dwd":
                    upstream = table
        for table in by_layer["dws"]:
            layer_result = await self._deploy_warehouse_layer(
                "DWS", upstream, table, granularity, schedule_minute
            )
            executed.append({"layer": "DWS", "table": table, "result": layer_result})
            self._set_step_status(
                execution_steps,
                "create_dws_tables_nodes_schedule",
                "completed" if layer_result.get("success") else "failed",
            )
            if not layer_result.get("success"):
                return WorkflowResult(
                    False,
                    "DWS 开发任务创建失败。",
                    "forward_modeling",
                    mode,
                    steps=execution_steps,
                    data={"executed": executed, "official_mcp_preflight": preflight},
                    errors=["dws execution failed"],
                )
            upstream = table

        result_data: dict[str, Any] = {
            "executed": executed,
            "capabilities": self.capability_status(),
            "official_mcp_preflight": preflight,
            "publish_gate": "not_requested",
            "source_type": source_type,
            "generated_tables": generated_tables,
        }
        if source_type == "oss" and executed:
            result_data["source_discovery"] = executed[0]["result"].get("schema_discovery", {})
        message_text = (
            "开发环境全链路已完成：表已创建，节点与调度已保存；"
            "初始化按请求执行，正式发布仍等待 Publish Gate。"
        )
        self._set_step_status(execution_steps, "publish_gate", "skipped")
        if publish:
            from dataworks_agent.runtime.publish_gate import PublishGate

            gate = getattr(app_state, "_publish_gate", None) or PublishGate()
            app_state._publish_gate = gate
            request = await gate.interrupt_for_approval(
                run_id=f"agent_{uuid.uuid4().hex[:12]}",
                session_id=client_ip,
                table_name=tables[-1] if tables else source_table,
                change_type="create",
                payload={"message": message, "tables": by_layer, "executed": executed},
                context={"mode": mode},
            )
            result_data["publish_request"] = request.__dict__
            result_data["publish_gate"] = "approval_required"
            self._set_step_status(execution_steps, "publish_gate", "approval_required")
            message_text = (
                f"开发环境全链路已完成，并已创建发布审批 {request.request_id}；"
                "未绕过 Publish Gate 上线。"
            )
        return WorkflowResult(
            True,
            message_text,
            "forward_modeling",
            mode,
            steps=execution_steps,
            artifacts=self._execution_artifacts(executed),
            data=result_data,
        )

    @staticmethod
    def _requests_full_chain(message: str) -> bool:
        lowered = message.lower()
        return (
            "全链路" in message
            or "建模处理" in message
            or "正向建模" in message
            or all(layer in lowered for layer in ("ods", "dwd", "dim", "dws"))
        )

    @staticmethod
    def _oss_source_name(oss_path: str) -> str:
        path = oss_path.split("?", 1)[0].rstrip("/")
        name = path.rsplit("/", 1)[-1] or "oss_object"
        return name.rsplit(".", 1)[0] or "oss_object"

    @staticmethod
    def _derive_forward_table_names(
        *, source_table: str, datasource: str, source_type: str, granularity: str
    ) -> dict[str, str]:
        source_name = source_table.split(".")[-1].lower()
        safe_source = re.sub(r"[^a-z0-9_]+", "_", source_name).strip("_") or "source_table"
        safe_datasource = re.sub(r"[^a-z0-9_]+", "_", datasource.lower()).strip("_") or "source"
        if source_type == "oss" and safe_datasource == safe_source:
            ods_table = f"ods_oss_{safe_source}_{granularity.lower()}"
        else:
            ods_table = generate_ods_di_table_name(
                safe_datasource,
                safe_source,
                granularity,
                source_type=source_type,
            )
        suffix = "hi" if granularity in {"hour", "hourly"} else "di"
        return {
            "ods": ods_table,
            "dwd": f"dwd_auto_{safe_source}_detail_{suffix}",
            "dim": f"dim_auto_{safe_source}_{suffix}",
            "dws": f"dws_auto_{safe_source}_summary_{suffix}",
        }

    @staticmethod
    def _build_forward_plan(
        by_layer: dict[str, list[str]],
        source_table: str | None,
        datasource: str | None,
        initialize: bool,
        source_type: str = "mysql",
    ) -> list[dict[str, Any]]:
        # Connectivity checks remain mandatory execution preflight, but they are
        # implementation details rather than user-facing modeling milestones.
        steps: list[dict[str, Any]] = []
        if by_layer["ods"]:
            steps.extend(
                [
                    {
                        "step": "discover_source_schema",
                        "datasource": datasource,
                        "source_table": source_table,
                        "source_type": source_type,
                        "status": "planned",
                    },
                    {
                        "step": "create_ods_table_and_source_node",
                        "tables": by_layer["ods"],
                        "source_type": source_type,
                        "status": "planned",
                    },
                ]
            )
            if initialize:
                steps.append({"step": "initialize_ods_data", "status": "planned"})
        for layer in ("dwd", "dim", "dws"):
            if by_layer[layer]:
                steps.append(
                    {
                        "step": f"create_{layer}_tables_nodes_schedule",
                        "tables": by_layer[layer],
                        "status": "planned",
                    }
                )
        steps.append({"step": "publish_gate", "status": "required_only_for_publish"})
        return steps

    @staticmethod
    def _set_step_status(steps: list[dict[str, Any]], step_name: str, status: str) -> None:
        for step in steps:
            if step.get("step") == step_name:
                step["status"] = status

    async def _official_datasource_preflight(self, datasource: str | None) -> dict[str, Any]:
        if not datasource:
            return {"status": "skipped", "reason": "datasource not required or missing"}
        if not settings.dataworks_project_id:
            return {
                "status": "warning",
                "error": "missing DATAWORKS_PROJECT_ID",
                "fallback": "cookie_bff",
            }
        payload, error = await self._official_call(
            "ListDataSources",
            {
                "ProjectId": settings.dataworks_project_id,
                "Name": datasource,
                "EnvType": "Dev",
                "PageSize": 10,
                "PageNumber": 1,
            },
        )
        if error:
            return {"status": "warning", "error": error, "fallback": "cookie_bff"}
        return {"status": "completed", "datasource": datasource, "result": payload}

    @staticmethod
    def _extract_inline_columns(message: str) -> list[dict[str, str]]:
        match = re.search(r"(?:字段|columns?)\s*[:：]?\s*([^。；;]+)", message, re.I)
        if not match:
            return []
        columns: list[dict[str, str]] = []
        for item in re.split(r"[,，]", match.group(1)):
            parts = item.strip().split()
            if len(parts) < 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[0]):
                continue
            columns.append({"name": parts[0], "type": parts[1]})
        return columns

    async def _ensure_oss_table(
        self,
        target_table: str,
        granularity: str,
        columns: list[dict[str, Any]],
        *,
        oss_path: str,
        file_format: str,
    ) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        if await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            return {
                "status": "exists",
                "columns": columns,
                "schema_discovery": {
                    "success": True,
                    "source": "existing_target_table",
                    "channel": "existing_target_table",
                    "file_format": file_format,
                },
            }

        schema_discovery: dict[str, Any]
        if columns:
            schema_discovery = {
                "success": True,
                "source": "explicit_columns",
                "channel": "explicit_columns",
                "file_format": file_format,
                "columns": columns,
            }
        else:
            from dataworks_agent.services.ods_oss import discover_oss_schema_with_fallback

            schema_discovery = await discover_oss_schema_with_fallback(
                getattr(app_state, "_bff_client", None),
                oss_path,
                file_format,
            )
            if not schema_discovery.get("success"):
                location = schema_discovery.get("location") or {}
                endpoint = str(location.get("endpoint") or "自动按地域推导")
                bucket = str(location.get("bucket") or "未识别")
                prefix = str(location.get("object_key") or "") or "根目录"
                detected_format = str(schema_discovery.get("file_format") or "未确定").upper()
                reason = str(schema_discovery.get("error") or "未知原因")
                next_action = str(
                    schema_discovery.get("next_action")
                    or "请修复 OSS 读取权限，或直接提供字段定义。"
                )
                return {
                    "status": "needs_context",
                    "error": reason,
                    "message": (
                        "已识别 OSS 地址和文件格式，但在建表前的真实字段探测阶段受阻。"
                        f" Endpoint: {endpoint}；Bucket: {bucket}；Prefix: {prefix}；"
                        f"格式: {detected_format}。"
                    ),
                    "clarifying_question": f"字段探测失败：{reason}。下一步：{next_action}",
                    "missing_context": ["managed_source_or_columns"],
                    "schema_discovery": schema_discovery,
                }
            columns = list(schema_discovery.get("columns") or [])

        if not columns:
            return {
                "status": "needs_context",
                "error": "OSS 样本未推断出可建表字段",
                "clarifying_question": "请确认 JSON 样本包含对象字段，或直接提供字段定义。",
                "missing_context": ["columns"],
                "schema_discovery": schema_discovery,
            }
        reserved = [
            str(column.get("name") or "")
            for column in columns
            if str(column.get("name") or "").lower() in {"dt", "ht"}
        ]
        if reserved:
            return {
                "status": "needs_context",
                "error": f"OSS 字段与 ODS 分区字段冲突：{'、'.join(reserved)}",
                "clarifying_question": "请确认冲突字段的映射方式后再建表。",
                "missing_context": ["column_mapping"],
                "schema_discovery": schema_discovery,
            }

        ddl_columns = ",\n".join(
            f"  `{column['name']}` {self._normalize_mc_type(str(column.get('type', 'string')))}"
            for column in columns
        )
        partitions = (
            "`dt` STRING, `ht` STRING" if granularity in {"hour", "hourly"} else "`dt` STRING"
        )
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n"
            f"{ddl_columns}\n) COMMENT 'OSS Agent generated' PARTITIONED BY ({partitions});"
        )
        ddl_result = await mc.execute_ddl(ddl)
        return {
            "status": "created" if ddl_result.success else "failed",
            "ddl": ddl,
            "error": ddl_result.error,
            "columns": columns,
            "schema_discovery": schema_discovery,
        }

    async def _ensure_table_from_source(
        self, source_table: str, target_table: str, granularity: str
    ) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        if await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            return {"status": "exists"}
        schema = await mc.get_table_schema(source_table)
        columns = [column for column in schema.columns if column.name.lower() not in {"dt", "ht"}]
        if not columns:
            return {"status": "failed", "error": f"源表 {source_table} 无业务字段"}
        ddl_columns = ",\n".join(
            f"  `{column.name}` {self._normalize_mc_type(str(column.type))}" for column in columns
        )
        partitions = (
            "`dt` STRING, `ht` STRING" if granularity in {"hour", "hourly"} else "`dt` STRING"
        )
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n"
            f"{ddl_columns}\n) COMMENT 'Realtime Agent generated' PARTITIONED BY ({partitions});"
        )
        ddl_result = await mc.execute_ddl(ddl)
        return {
            "status": "created" if ddl_result.success else "failed",
            "ddl": ddl,
            "error": ddl_result.error,
            "columns": columns,
        }

    async def _execute_ods(
        self,
        *,
        message: str,
        params: dict[str, Any],
        source_type: str,
        datasource: str | None,
        source_table: str,
        target_table: str,
        granularity: str,
        schedule_minute: int,
        initialize: bool,
    ) -> dict[str, Any]:
        bff = getattr(app_state, "_bff_client", None)
        nodes = getattr(app_state, "_node_client", None)
        normalized_granularity = "hour" if granularity in {"hour", "hourly"} else "day"

        if source_type in {"hologres", "holo"}:
            if bff is None or nodes is None:
                return {
                    "success": False,
                    "error": "Hologres ODS 需要 Cookie/BFF 元数据兜底和 AK/SK 节点客户端",
                }
            holo_schema = str(params.get("holo_schema") or datasource or "").strip().lower()
            if not holo_schema:
                return {
                    "success": False,
                    "error": "Hologres ODS 需要 holo_schema 或 datasource_name",
                }
            from dataworks_agent.services.ods_holo import HoloOdsPipeline

            pipeline = HoloOdsPipeline(
                bff,
                None,
                node_client=nodes,
                mc_client=app_state._maxcompute_client,
            )
            return await pipeline.run(
                holo_schema=holo_schema,
                source_table=source_table,
                target_table=target_table,
                granularity=normalized_granularity,
                script_path=str(params.get("script_path") or settings.holo_ods_node_path),
                schedule_minute=schedule_minute,
                where_mode=str(params.get("where_mode") or "auto"),
            )

        if source_type == "oss":
            from dataworks_agent.services.ods_oss import (
                OssImportPipeline,
                infer_file_format,
                parse_oss_path,
            )

            oss_path = params.get("oss_path") or self._extractor.extract_oss_path(message)
            if not oss_path:
                return {"success": False, "error": "OSS ODS 需要 oss:// 路径"}
            try:
                location = parse_oss_path(str(oss_path))
            except ValueError as exc:
                return {
                    "success": False,
                    "needs_context": True,
                    "error": str(exc),
                    "message": "OSS 地址无法规范化，尚未执行建表或建节点。",
                    "clarifying_question": f"{exc}。请提供有效的 OSS 地址后继续。",
                    "missing_context": ["oss_path"],
                    "schema_discovery": {
                        "success": False,
                        "error_code": "invalid_location",
                        "error": str(exc),
                    },
                }
            canonical_path = str(location.get("location_uri") or location["canonical_uri"])
            columns = params.get("columns") or self._extract_inline_columns(message)
            requested_format = params.get("file_format") or self._extractor.extract_file_format(
                message
            )
            file_format = infer_file_format(canonical_path, str(requested_format or ""))
            if columns and not file_format:
                schema_discovery = {
                    "success": False,
                    "location": location,
                    "file_format": "",
                    "error_code": "format_required",
                    "error": "OSS 文件格式尚未确定",
                    "next_action": "请补充文件格式，例如“文件格式是 JSON”。",
                }
                return {
                    "success": False,
                    "needs_context": True,
                    "error": schema_discovery["error"],
                    "message": "OSS 地址和字段已识别，但文件格式尚未确定，未建表或建节点。",
                    "clarifying_question": schema_discovery["next_action"],
                    "missing_context": ["file_format"],
                    "schema_discovery": schema_discovery,
                }
            ensure_result = await self._ensure_oss_table(
                target_table,
                granularity,
                columns,
                oss_path=str(oss_path),
                file_format=file_format,
            )
            if ensure_result.get("status") == "needs_context":
                return {
                    "success": False,
                    "needs_context": True,
                    "error": ensure_result.get("error"),
                    "message": ensure_result.get("message"),
                    "clarifying_question": ensure_result.get("clarifying_question"),
                    "missing_context": ensure_result.get("missing_context"),
                    "schema_discovery": ensure_result.get("schema_discovery") or {},
                    "steps": {"discover_schema": ensure_result},
                }
            if ensure_result.get("status") == "failed":
                return {
                    "success": False,
                    "error": ensure_result.get("error"),
                    "schema_discovery": ensure_result.get("schema_discovery") or {},
                    "steps": {"ensure_table": ensure_result},
                }

            schema_discovery = ensure_result.get("schema_discovery") or {}
            file_format = str(schema_discovery.get("file_format") or file_format).lower()
            if file_format not in {"csv", "json", "parquet"}:
                return {
                    "success": False,
                    "needs_context": True,
                    "error": "无法确定 OSS 文件格式",
                    "message": "OSS 地址已识别，但文件格式尚未确定，未创建节点。",
                    "clarifying_question": "请补充文件格式，例如“文件格式是 JSON”。",
                    "missing_context": ["file_format"],
                    "schema_discovery": schema_discovery,
                }
            result = await OssImportPipeline(nodes).run(
                oss_path=canonical_path,
                target_table=target_table,
                file_format=file_format,
                wildcard=str(params.get("wildcard") or ""),
                schedule_type=normalized_granularity,
                schedule_minute=schedule_minute,
                publish=False,
                ingestion_mode=str(schema_discovery.get("ingestion_mode") or "structured"),
                root_node_uuid=str(
                    params.get("root_node_uuid")
                    or settings.dataworks_default_root_node_uuid
                    or settings.root_check_node_uuid
                    or ""
                ),
                output_ref=f"{settings.dataworks_dev_schema}.{target_table}",
            )
            result.setdefault("steps", {})["ensure_table"] = ensure_result
            result["schema_discovery"] = schema_discovery
            result["oss_location"] = location
            return result

        if source_type == "realtime":
            database_schema = str(params.get("database_schema") or datasource or "").strip()
            if not database_schema:
                return {
                    "success": False,
                    "error": "实时 ODS 需要 database_schema 或 datasource_name",
                }
            delta_table = str(
                params.get("delta_table") or f"{database_schema}__{source_table}_delta"
            )
            ensure_result = await self._ensure_table_from_source(delta_table, target_table, "hour")
            if ensure_result.get("status") == "failed":
                return {
                    "success": False,
                    "error": ensure_result.get("error"),
                    "steps": {"ensure_table": ensure_result},
                }
            select_dml = params.get("select_dml")
            if not select_dml:
                columns = ensure_result.get("columns")
                if not columns:
                    schema = await app_state._maxcompute_client.get_table_schema(delta_table)
                    columns = [
                        column
                        for column in schema.columns
                        if column.name.lower() not in {"dt", "ht"}
                    ]
                select_dml = (
                    "SELECT "
                    + ", ".join(f"`{column.name}`" for column in columns)
                    + f" FROM {delta_table}"
                )
            sync_rows = params.get("sync_rows") or [{"dst_table": delta_table}]
            from dataworks_agent.services.ods_realtime import RealtimeSyncPipeline

            result = await RealtimeSyncPipeline(nodes).run(
                database_schema=database_schema,
                table_name=source_table,
                sync_rows=sync_rows,
                select_dml=str(select_dml),
                target_table=target_table,
                granularity="hour",
                schedule_minute=schedule_minute,
                publish=False,
            )
            result.setdefault("steps", {})["ensure_table"] = ensure_result
            return result

        if not datasource:
            return {"success": False, "error": "ODS DI 需要 datasource_name"}
        if bff is None:
            return {
                "success": False,
                "error": "Cookie/BFF 不可用，无法发现数据源字段或手动初始化 DI",
            }
        from dataworks_agent.services.ods_di.pipeline import DIPipeline

        pipeline = DIPipeline(
            bff,
            None,
            node_client=nodes,
            mc_client=app_state._maxcompute_client,
        )
        return await pipeline.run(
            datasource_name=datasource,
            source_table=source_table,
            target_table=target_table,
            granularity=normalized_granularity,
            schedule_minute=schedule_minute,
            source_type=source_type,
            mc_project=settings.dataworks_dev_schema,
            with_initialization=initialize,
            init_config={
                "dev_mc_project": settings.dataworks_dev_schema,
                "prod_mc_project": settings.dataworks_prod_schema,
                "copy_to_prod": False,
                "publish_incremental_after_init": False,
            },
        )

    async def _deploy_warehouse_layer(
        self,
        layer: str,
        source_table: str,
        target_table: str,
        granularity: str,
        schedule_minute: int,
    ) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        nodes = app_state._node_client
        schema = await mc.get_table_schema(source_table)
        columns = [c for c in schema.columns if c.name.lower() not in {"dt", "ht", "hh"}]
        if not columns:
            return {"success": False, "error": f"源表 {source_table} 无业务字段"}
        partition_names = ["dt", "ht"] if granularity in {"hour", "hourly"} else ["dt"]
        ddl_cols = ",\n".join(
            f"  `{c.name}` {self._normalize_mc_type(c.type)} COMMENT '{self._escape_comment(c.comment)}'"
            for c in columns
        )
        partitions = ", ".join(f"`{name}` STRING" for name in partition_names)
        ddl = f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n{ddl_cols}\n) COMMENT '{layer} Agent generated' PARTITIONED BY ({partitions});"
        if not await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            ddl_result = await mc.execute_ddl(ddl)
            if not ddl_result.success:
                return {"success": False, "error": ddl_result.error, "ddl": ddl}
        select_cols = ",\n".join(f"  `{c.name}`" for c in columns)
        if granularity in {"hour", "hourly"}:
            partition = "PARTITION (dt='${bizdate}', ht='${hour}')"
            where = "WHERE dt='${bizdate}' AND ht='${hour}'"
            cycle = "NotDaily"
            parameters = HOURLY_SQL_PARAMETERS
            cron = generate_cron("hour", minute=schedule_minute)
        else:
            partition = "PARTITION (dt='${bizdate}')"
            where = "WHERE dt='${bizdate}'"
            cycle = "Daily"
            parameters = DAILY_SQL_PARAMETERS
            cron = generate_cron("day", hour=3, minute=schedule_minute)
        sql = f"INSERT OVERWRITE TABLE {settings.dataworks_dev_schema}.{target_table} {partition}\nSELECT\n{select_cols}\nFROM {settings.dataworks_dev_schema}.{source_table}\n{where};"
        node_path = generate_node_path(
            f"dataworks_agent/{'02_DWD' if layer == 'DWD' else '03_' + layer}", target_table
        )
        node_uuid = await nodes.create_node(target_table, node_path, language="odps-sql")
        if not node_uuid or not await nodes.update_node(node_uuid, sql):
            return {
                "success": False,
                "error": nodes.last_error or "create/update node failed",
                "ddl": ddl,
                "sql": sql,
            }
        scheduled = await nodes.update_vertex(
            node_uuid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": cron,
                    "cycleType": cycle,
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": parameters},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": [
                    {
                        "type": "Normal",
                        "sourceType": "Manual",
                        "output": f"{settings.maxcompute_project or settings.dataworks_dev_schema}.{source_table}",
                        "refTableName": f"{settings.maxcompute_project or settings.dataworks_dev_schema}.{source_table}",
                    },
                    {"type": "CrossCycleDependsOnSelf"},
                ],
            },
        )
        return {
            "success": bool(scheduled),
            "table_status": "exists_or_created",
            "node_uuid": node_uuid,
            "node_path": node_path,
            "cron": cron,
            "ddl": ddl,
            "sql": sql,
            "publish": "saved_not_deployed",
        }

    @staticmethod
    def _normalize_mc_type(value: str) -> str:
        lower = value.lower()
        if any(t in lower for t in ("tinyint", "smallint", "int", "bigint")):
            return "BIGINT"
        if any(t in lower for t in ("decimal", "double", "float")):
            return "DECIMAL(24,6)"
        if "boolean" in lower:
            return "BOOLEAN"
        return "STRING"

    @staticmethod
    def _escape_comment(value: str) -> str:
        return (value or "").replace("'", "''")

    @staticmethod
    def _column_to_dict(column: Any) -> dict[str, Any]:
        return {
            "name": getattr(column, "name", ""),
            "type": str(getattr(column, "type", "")),
            "comment": getattr(column, "comment", "") or "",
        }

    @staticmethod
    def _extract_sql_sources(sql: str) -> list[str]:
        try:
            statement = sqlglot.parse_one(sql, read="hive")
        except Exception:
            return []
        return list(
            dict.fromkeys(
                table.sql(dialect="hive") for table in statement.find_all(exp.Table) if table.name
            )
        )

    @staticmethod
    def _infer_reverse_metadata(table_name: str, columns: list[dict[str, Any]]) -> dict[str, Any]:
        from dataworks_agent.governance.table_name_parser import identify_layer, parse_table_name
        from dataworks_agent.governance.update_mode_inferer import infer_update_mode

        layer = identify_layer(table_name)
        try:
            parsed = parse_table_name(table_name)
        except Exception:
            parsed = {}
        try:
            resolution = infer_update_mode(table_name)
            update_mode: Any = {
                "dwd_update_mode": resolution.dwd_update_mode,
                "sql_update_mode": resolution.sql_update_mode,
                "partition_fields": resolution.partition_fields,
            }
        except Exception:
            update_mode = "unknown"
        semantic_candidates = []
        for column in columns:
            name = column["name"].lower()
            kind = (
                "measure"
                if any(
                    token in name
                    for token in ("amt", "amount", "price", "cnt", "count", "qty", "gmv")
                )
                else "dimension"
            )
            semantic_candidates.append(
                {
                    "name": column["name"],
                    "kind": kind,
                    "data_type": column["type"],
                    "description": column.get("comment", ""),
                    "confidence": 0.82 if column.get("comment") else 0.62,
                }
            )
        return {
            "layer": layer,
            "domain": parsed.get("subject_domain", "") if isinstance(parsed, dict) else "",
            "entity": parsed.get("description", "") if isinstance(parsed, dict) else "",
            "update_mode": update_mode,
            "semantic_candidates": semantic_candidates,
        }

    @staticmethod
    def _infer_issue_type(message: str, errors: list[str]) -> str:
        text = f"{message} {' '.join(errors)}".lower()
        if any(token in text for token in ("延迟", "上游未完成", "upstream delay")):
            return "upstream_delay"
        if any(token in text for token in ("质量", "空值", "重复", "quality")):
            return "quality_issue"
        if any(token in text for token in ("数据异常", "数据不对", "波动", "data anomaly")):
            return "data_anomaly"
        return "schedule_failure"

    @staticmethod
    def _execution_artifacts(executed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for item in executed:
            result = item["result"]
            for kind in ("ddl", "sql"):
                if result.get(kind):
                    artifacts.append({"type": kind, "name": item["table"], "content": result[kind]})
            ensure_table = (result.get("steps") or {}).get("ensure_table") or {}
            if ensure_table.get("ddl") and not result.get("ddl"):
                artifacts.append(
                    {"type": "ddl", "name": item["table"], "content": ensure_table["ddl"]}
                )
        return artifacts
