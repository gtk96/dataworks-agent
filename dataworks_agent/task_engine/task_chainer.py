"""TaskChainer — 任务接力器。

Loop Engineering 的 Self-prompting 机制：
上一轮跑完之后，不由人来想"下一步该问什么"，
而是让系统根据已有进展，自己写下一轮要跑的 Prompt。

Validates: Requirements 39
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from dataworks_agent.task_engine.task_memory import NextStep, TaskMemory, TaskMemoryService

logger = logging.getLogger(__name__)


@dataclass
class ChainingRule:
    """接力规则。"""

    id: str
    trigger_task_type: str
    trigger_status: str
    next_task_type: str
    description: str
    enabled: bool = True


@dataclass
class ChainingDecision:
    """接力决策。"""

    rule_id: str
    trigger_task_id: str
    trigger_task_type: str
    next_task_type: str
    description: str
    executed: bool = False
    reason: str = ""


class TaskChainer:
    """任务接力器。

    任务完成后根据规则自动触发下一个任务。
    """

    def __init__(self, rules_path: str | Path | None = None) -> None:
        self._rules: list[ChainingRule] = []
        self._memory_service = TaskMemoryService()
        self._max_chain_depth = 10

        if rules_path:
            self._load_rules(rules_path)
        else:
            self._load_default_rules()

    def _load_rules(self, rules_path: str | Path) -> None:
        """从 YAML 文件加载接力规则。"""
        try:
            with open(rules_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            for rule_data in config.get("chaining_rules", []):
                self._rules.append(
                    ChainingRule(
                        id=rule_data["id"],
                        trigger_task_type=rule_data["trigger_task_type"],
                        trigger_status=rule_data.get("trigger_status", "verified"),
                        next_task_type=rule_data["next_task_type"],
                        description=rule_data.get("description", ""),
                        enabled=rule_data.get("enabled", True),
                    )
                )

            self._max_chain_depth = config.get("max_chain_depth", 10)

            logger.info("加载 %d 条接力规则", len(self._rules))
        except Exception as e:
            logger.warning("加载接力规则失败: %s，使用默认规则", e)
            self._load_default_rules()

    def _load_default_rules(self) -> None:
        """加载默认接力规则。"""
        self._rules = [
            # ODS
            ChainingRule(
                id="ods_to_dml",
                trigger_task_type="ods_node_create",
                trigger_status="verified",
                next_task_type="dml_push",
                description="ODS 节点创建完成后，自动触发 DML 推送",
            ),
            ChainingRule(
                id="ods_dml_to_schedule",
                trigger_task_type="ods_dml_push",
                trigger_status="verified",
                next_task_type="schedule_config",
                description="ODS DML 推送完成后，自动触发调度参数配置",
            ),
            # DWD
            ChainingRule(
                id="dwd_to_dml",
                trigger_task_type="dwd_node_create",
                trigger_status="verified",
                next_task_type="dml_push",
                description="DWD 节点创建完成后，自动触发 DML 推送",
            ),
            ChainingRule(
                id="dwd_dml_to_deps",
                trigger_task_type="dwd_dml_push",
                trigger_status="verified",
                next_task_type="dependency_config",
                description="DWD DML 推送完成后，自动触发上游依赖配置",
            ),
            # DIM
            ChainingRule(
                id="dim_to_dml",
                trigger_task_type="dim_node_create",
                trigger_status="verified",
                next_task_type="dml_push",
                description="DIM 节点创建完成后，自动触发 DML 推送",
            ),
            ChainingRule(
                id="dim_dml_to_deps",
                trigger_task_type="dim_dml_push",
                trigger_status="verified",
                next_task_type="dependency_config",
                description="DIM DML 推送完成后，自动触发上游依赖配置",
            ),
            # DWS
            ChainingRule(
                id="dws_to_dml",
                trigger_task_type="dws_node_create",
                trigger_status="verified",
                next_task_type="dml_push",
                description="DWS 节点创建完成后，自动触发 DML 推送",
            ),
            ChainingRule(
                id="dws_dml_to_deps",
                trigger_task_type="dws_dml_push",
                trigger_status="verified",
                next_task_type="dependency_config",
                description="DWS DML 推送完成后，自动触发上游依赖配置",
            ),
        ]

    def on_task_complete(self, task_id: str, task_type: str, status: str) -> list[ChainingDecision]:
        """任务完成后检查是否需要触发接力。

        Args:
            task_id: 完成的任务ID
            task_type: 任务类型 (ods_node_create / dwd_dml_push / etc.)
            status: 任务状态 (verified / failed / etc.)

        Returns:
            接力决策列表
        """
        decisions: list[ChainingDecision] = []

        # 检查当前任务的接力深度
        memory = self._memory_service.get(task_id)
        if memory:
            chain_depth = self._calculate_chain_depth(memory)
            if chain_depth >= self._max_chain_depth:
                logger.warning(
                    "任务 %s 接力深度已达上限 %d，停止接力",
                    task_id,
                    self._max_chain_depth,
                )
                return decisions

        # 查找匹配的规则
        matching_rules = [
            rule
            for rule in self._rules
            if rule.enabled
            and rule.trigger_task_type == task_type
            and rule.trigger_status == status
        ]

        if not matching_rules:
            logger.debug("任务 %s (类型=%s, 状态=%s) 无匹配接力规则", task_id, task_type, status)
            return decisions

        # 为每个匹配规则生成决策
        for rule in matching_rules:
            decision = ChainingDecision(
                rule_id=rule.id,
                trigger_task_id=task_id,
                trigger_task_type=task_type,
                next_task_type=rule.next_task_type,
                description=rule.description,
                executed=False,
                reason=f"匹配规则: {rule.id}",
            )
            decisions.append(decision)

            # 生成下一步建议
            if memory:
                self._memory_service.append_step(
                    task_id,
                    __import__(
                        "dataworks_agent.task_engine.task_memory", fromlist=["StepRecord"]
                    ).StepRecord(
                        step_name=f"chain_trigger_{rule.next_task_type}",
                        status="completed",
                        result={"rule_id": rule.id, "next_task_type": rule.next_task_type},
                    ),
                )

            logger.info(
                "任务 %s 触发接力: %s → %s",
                task_id,
                task_type,
                rule.next_task_type,
            )

        return decisions

    def get_next_steps(self, task_id: str) -> list[NextStep]:
        """获取任务的下一步建议。"""
        memory = self._memory_service.get(task_id)
        if not memory:
            return []
        return memory.next_steps

    def get_rules(self) -> list[ChainingRule]:
        """获取所有接力规则。"""
        return self._rules.copy()

    def enable_rule(self, rule_id: str) -> bool:
        """启用接力规则。"""
        for rule in self._rules:
            if rule.id == rule_id:
                rule.enabled = True
                logger.info("接力规则 %s 已启用", rule_id)
                return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """禁用接力规则。"""
        for rule in self._rules:
            if rule.id == rule_id:
                rule.enabled = False
                logger.info("接力规则 %s 已禁用", rule_id)
                return True
        return False

    def _calculate_chain_depth(self, memory: TaskMemory) -> int:
        """计算任务的接力深度。"""
        depth = 0
        for step in memory.completed_steps:
            if step.step_name.startswith("chain_trigger_"):
                depth += 1
        return depth
