"""任务规划器 — 根据用户意图生成可执行的任务计划。"""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.agent.autonomous.state import (
    AutonomousContext,
    AutonomousTask,
    TaskType,
)

logger = logging.getLogger(__name__)


class AutonomousPlanner:
    """将用户意图拆解为有序的步骤链。

    ODS / DWD 的每一步都有明确的输入输出，后续 executor 按步骤顺序执行，
    verifier 按相同维度回查。
    """

    def __init__(self, context: AutonomousContext, rag_context: str | None = None) -> None:
        self._context = context
        self._rag_context = rag_context or ""

    @property
    def rag_context(self) -> str:
        return self._rag_context

    def plan_create_ods(self, params: dict[str, Any]) -> AutonomousTask:
        """规划 ODS 层创建任务。

        典型参数：target_table、source_table、source_type（mysql/hologres/oss/realtime）、
        datasouce_name、columns、partition_keys。
        """
        logger.info(
            "规划 ODS 创建任务: target=%s source=%s",
            params.get("target_table"),
            params.get("source_table"),
        )

        task = AutonomousTask(
            task_type=TaskType.CREATE_ODS,
            description=f"创建 ODS 表: {params.get('target_table', 'unknown')}",
            params=params,
            plan=[
                {"step": "validate_params", "description": "校验目标表名、源表、数据源类型"},
                {"step": "generate_ddl", "description": "生成 MaxCompute DDL"},
                {"step": "create_table", "description": "MaxCompute 建表（草稿）"},
                {"step": "create_node", "description": "创建 DI/Holo 节点"},
                {"step": "configure_schedule", "description": "配置调度周期与依赖"},
                {"step": "verify", "description": "验证表、节点、调度是否存在"},
            ],
        )
        return task

    def plan_create_dwd(self, params: dict[str, Any]) -> AutonomousTask:
        """规划 DWD 层创建任务。

        典型参数：target_table、source_table(s)、domain、entity、update_method、
        dwd_metadata、partition_keys。
        """
        logger.info(
            "规划 DWD 创建任务: target=%s sources=%s",
            params.get("target_table"),
            params.get("source_table"),
        )

        task = AutonomousTask(
            task_type=TaskType.CREATE_DWD,
            description=f"创建 DWD 表: {params.get('target_table', 'unknown')}",
            params=params,
            plan=[
                {"step": "validate_params", "description": "校验目标表名、源表前缀、更新方式"},
                {
                    "step": "discover_source_tables",
                    "description": "发现并确认上游源表结构",
                },
                {"step": "generate_ddl", "description": "生成 DWD DDL"},
                {"step": "generate_sql", "description": "生成 DWD DML/SQL"},
                {"step": "create_table", "description": "MaxCompute 建表"},
                {"step": "create_node", "description": "创建 SQL 节点"},
                {"step": "configure_dependencies", "description": "配置节点级上游依赖"},
                {"step": "configure_schedule", "description": "配置调度周期与自依赖"},
                {"step": "verify", "description": "验证表、节点、依赖、调度"},
            ],
        )
        return task

    def plan_modify_task(self, params: dict[str, Any]) -> AutonomousTask:
        """规划任务修改任务。

        典型参数：node_id 或 target_table、change_description、new_sql/new_ddl。
        """
        logger.info("规划任务修改: target=%s", params.get("target_table") or params.get("node_id"))

        task = AutonomousTask(
            task_type=TaskType.MODIFY_TASK,
            description=f"修改任务: {params.get('target_table') or params.get('node_id', 'unknown')}",
            params=params,
            plan=[
                {"step": "validate_params", "description": "校验 node_id / table 存在性"},
                {"step": "read_current", "description": "读取当前节点脚本与调度配置"},
                {"step": "apply_change", "description": "应用变更（仅草稿）"},
                {"step": "verify", "description": "验证变更已生效且未越权"},
            ],
        )
        return task

    def plan_configure_schedule(self, params: dict[str, Any]) -> AutonomousTask:
        """规划调度配置任务。"""
        logger.info("规划调度配置: target=%s", params.get("target_table") or params.get("node_id"))

        task = AutonomousTask(
            task_type=TaskType.CONFIGURE_SCHEDULE,
            description=f"配置调度: {params.get('target_table') or params.get('node_id', 'unknown')}",
            params=params,
            plan=[
                {"step": "validate_params", "description": "校验 cron / cycle_type / startTime"},
                {"step": "read_current", "description": "读取当前调度配置"},
                {"step": "apply_schedule", "description": "更新调度配置（草稿）"},
                {"step": "verify", "description": "验证新调度配置已写入"},
            ],
        )
        return task

    def plan_configure_dependency(self, params: dict[str, Any]) -> AutonomousTask:
        """规划依赖配置任务。"""
        logger.info(
            "规划依赖配置: target=%s upstream=%s",
            params.get("target_table"),
            params.get("upstream_nodes"),
        )

        task = AutonomousTask(
            task_type=TaskType.CONFIGURE_DEPENDENCY,
            description=f"配置依赖: {params.get('target_table', 'unknown')}",
            params=params,
            plan=[
                {"step": "validate_params", "description": "校验上游节点 ID / 表名合法性"},
                {"step": "read_current", "description": "读取当前节点依赖"},
                {"step": "apply_dependency", "description": "更新节点依赖（草稿）"},
                {"step": "verify", "description": "验证依赖关系已生效"},
            ],
        )
        return task

    def generate_plan(self, intent: str, params: dict[str, Any]) -> AutonomousTask:
        """根据意图字符串 + 参数生成对应任务计划。

        支持模糊匹配，例如 "帮我建 ODS 表"、"创建 dwd_xxx"、"修改节点"、
        "配置调度"、"设置依赖"。RAG 上下文会作为规划参考附加到任务描述中。
        """
        lower = intent.lower()

        if "dwd" in lower and any(kw in lower for kw in ("创建", "新建", "建", "create", "建模")):
            return self.plan_create_dwd(params)
        if "ods" in lower and any(kw in lower for kw in ("创建", "新建", "建", "create", "建模")):
            return self.plan_create_ods(params)
        if any(kw in lower for kw in ("修改", "更新", "modify", "change", "调整")):
            return self.plan_modify_task(params)
        if any(kw in lower for kw in ("调度", "schedule", "cron", "配置调度")):
            return self.plan_configure_schedule(params)
        if any(kw in lower for kw in ("依赖", "dependency", "depends", "上游", "配置依赖")):
            return self.plan_configure_dependency(params)

        # 兜底：从 target_table 前缀推断
        target = str(params.get("target_table") or params.get("table_name") or "")
        if target.lower().startswith("dwd_"):
            return self.plan_create_dwd(params)
        if target.lower().startswith("ods_"):
            return self.plan_create_ods(params)

        raise ValueError(
            f"无法识别意图 '{intent}'，请明确指定 ODS/DWD 创建、修改、调度或依赖配置。"
        )

    def attach_rag_context(self, context: str) -> None:
        """将 RAG 检索到的规范上下文注入规划器。"""
        self._rag_context = context or ""
        if context:
            logger.info("RAG context attached to planner (%d chars)", len(context))
