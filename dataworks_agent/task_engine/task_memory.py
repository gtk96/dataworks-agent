"""TaskMemoryService — 任务 Memory 持久化服务。

Loop Engineering 的核心：进度写在对话外面，独立于对话存在。
任何 Agent 在任何时间都能读取"现在到哪儿了"。

Validates: Requirements 38
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import TaskMemoryModel

logger = logging.getLogger(__name__)


@dataclass
class StepRecord:
    """步骤记录。"""

    step_name: str
    status: str  # completed / failed / skipped
    started_at: str = ""
    completed_at: str = ""
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """决策记录。"""

    decision: str
    reason: str
    alternatives: list[str] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class ArtifactRef:
    """产物引用。"""

    artifact_type: str  # ddl / dml / node / schedule / dependency
    artifact_id: str
    description: str = ""
    location: str = ""


@dataclass
class NextStep:
    """下一步建议。"""

    step_type: str  # dml_push / schedule_config / dependency_config / verification / done
    description: str
    priority: int = 0  # 越小越优先
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Blocker:
    """阻塞项。"""

    blocker_type: str  # dependency / permission / validation / external
    description: str
    created_at: str = ""


@dataclass
class TaskMemory:
    """任务 Memory 数据结构。"""

    task_id: str
    session_id: str = ""

    # 进度追踪
    completed_steps: list[StepRecord] = field(default_factory=list)
    current_step: str = ""

    # 决策记录
    decisions: list[Decision] = field(default_factory=list)

    # 产物引用
    artifacts: list[ArtifactRef] = field(default_factory=list)

    # 下一步建议
    next_steps: list[NextStep] = field(default_factory=list)

    # 阻塞项
    blockers: list[Blocker] = field(default_factory=list)

    # 验收状态
    verification_status: str = "pending"  # pending / passed / failed
    verification_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "completed_steps": [s.__dict__ for s in self.completed_steps],
            "current_step": self.current_step,
            "decisions": [d.__dict__ for d in self.decisions],
            "artifacts": [a.__dict__ for a in self.artifacts],
            "next_steps": [n.__dict__ for n in self.next_steps],
            "blockers": [b.__dict__ for b in self.blockers],
            "verification_status": self.verification_status,
            "verification_result": self.verification_result,
        }


class TaskMemoryService:
    """任务 Memory 服务。

    提供任务 Memory 的 CRUD 操作，以及 next_steps 自动生成。
    """

    def get(self, task_id: str) -> TaskMemory | None:
        """获取任务 Memory。"""
        with SessionLocal() as db:
            model = db.get(TaskMemoryModel, task_id)
            if not model:
                return None
            return self._model_to_memory(model)

    def get_or_create(self, task_id: str, session_id: str = "") -> TaskMemory:
        """获取或创建任务 Memory。"""
        memory = self.get(task_id)
        if memory:
            return memory

        memory = TaskMemory(task_id=task_id, session_id=session_id)
        self._save(memory)
        return memory

    def update(self, memory: TaskMemory) -> None:
        """更新任务 Memory。"""
        self._save(memory)

    def append_step(self, task_id: str, step: StepRecord) -> None:
        """追加步骤记录。"""
        memory = self.get_or_create(task_id)
        memory.completed_steps.append(step)
        self._save(memory)

    def append_decision(self, task_id: str, decision: Decision) -> None:
        """追加决策记录。"""
        memory = self.get_or_create(task_id)
        memory.decisions.append(decision)
        self._save(memory)

    def append_artifact(self, task_id: str, artifact: ArtifactRef) -> None:
        """追加产物引用。"""
        memory = self.get_or_create(task_id)
        memory.artifacts.append(artifact)
        self._save(memory)

    def set_next_steps(self, task_id: str, next_steps: list[NextStep]) -> None:
        """设置下一步建议。"""
        memory = self.get_or_create(task_id)
        memory.next_steps = next_steps
        self._save(memory)

    def append_blocker(self, task_id: str, blocker: Blocker) -> None:
        """追加阻塞项。"""
        memory = self.get_or_create(task_id)
        memory.blockers.append(blocker)
        self._save(memory)

    def clear_blockers(self, task_id: str) -> None:
        """清除所有阻塞项。"""
        memory = self.get_or_create(task_id)
        memory.blockers.clear()
        self._save(memory)

    def set_verification(self, task_id: str, status: str, result: dict[str, Any]) -> None:
        """设置验收状态。"""
        memory = self.get_or_create(task_id)
        memory.verification_status = status
        memory.verification_result = result
        self._save(memory)

    def generate_next_steps(
        self, task_id: str, task_type: str, context: dict[str, Any] | None = None
    ) -> list[NextStep]:
        """根据任务类型自动生成下一步建议。

        这是 Loop Engineering 的 Self-prompting 机制的核心：
        上一轮跑完之后，不由人来想"下一步该问什么"，
        而是让系统根据已有进展，自己写下一轮要跑的 Prompt。
        """
        next_steps: list[NextStep] = []

        if task_type == "ODS":
            # ODS 节点创建完成后：推 DML → 配调度参数 → 验证
            next_steps.append(
                NextStep(
                    step_type="dml_push",
                    description="推送 DML 到 ODS 节点",
                    priority=1,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="schedule_config",
                    description="配置 ODS 节点调度参数",
                    priority=2,
                    context=context or {},
                )
            )

        elif task_type == "DWD":
            # DWD 节点创建完成后：推 DML → 配依赖 → 配调度 → 验证
            next_steps.append(
                NextStep(
                    step_type="dml_push",
                    description="推送 DML 到 DWD 节点",
                    priority=1,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="dependency_config",
                    description="配置 DWD 节点上游依赖",
                    priority=2,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="schedule_config",
                    description="配置 DWD 节点调度参数",
                    priority=3,
                    context=context or {},
                )
            )

        elif task_type == "DIM":
            # DIM 节点创建完成后：推 DML → 配依赖 → 配调度 → 验证
            next_steps.append(
                NextStep(
                    step_type="dml_push",
                    description="推送 DML 到 DIM 节点",
                    priority=1,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="dependency_config",
                    description="配置 DIM 节点上游依赖",
                    priority=2,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="schedule_config",
                    description="配置 DIM 节点调度参数",
                    priority=3,
                    context=context or {},
                )
            )

        elif task_type == "DWS":
            # DWS 节点创建完成后：推 DML → 配依赖 → 配调度 → 验证
            next_steps.append(
                NextStep(
                    step_type="dml_push",
                    description="推送 DML 到 DWS 节点",
                    priority=1,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="dependency_config",
                    description="配置 DWS 节点上游依赖",
                    priority=2,
                    context=context or {},
                )
            )
            next_steps.append(
                NextStep(
                    step_type="schedule_config",
                    description="配置 DWS 节点调度参数",
                    priority=3,
                    context=context or {},
                )
            )

        # 通用：最后一步是验证
        next_steps.append(
            NextStep(
                step_type="verification",
                description="运行闭环验收检查",
                priority=99,
                context=context or {},
            )
        )

        # 保存到 Memory
        self.set_next_steps(task_id, next_steps)

        logger.info(
            "任务 %s (类型=%s) 生成 %d 个下一步建议",
            task_id,
            task_type,
            len(next_steps),
        )

        return next_steps

    # ── 内部方法 ──

    def _save(self, memory: TaskMemory) -> None:
        """保存任务 Memory 到数据库。"""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()

        with SessionLocal() as db:
            model = db.get(TaskMemoryModel, memory.task_id)

            if not model:
                model = TaskMemoryModel(
                    task_id=memory.task_id,
                    session_id=memory.session_id,
                )
                db.add(model)

            # 更新字段
            model.session_id = memory.session_id
            model.completed_steps_json = json.dumps(
                [s.__dict__ for s in memory.completed_steps], ensure_ascii=False
            )
            model.current_step = memory.current_step
            model.decisions_json = json.dumps(
                [d.__dict__ for d in memory.decisions], ensure_ascii=False
            )
            model.artifacts_json = json.dumps(
                [a.__dict__ for a in memory.artifacts], ensure_ascii=False
            )
            model.next_steps_json = json.dumps(
                [n.__dict__ for n in memory.next_steps], ensure_ascii=False
            )
            model.blockers_json = json.dumps(
                [b.__dict__ for b in memory.blockers], ensure_ascii=False
            )
            model.verification_status = memory.verification_status
            model.verification_json = json.dumps(memory.verification_result, ensure_ascii=False)
            model.updated_at = now

            db.commit()

    def _model_to_memory(self, model: TaskMemoryModel) -> TaskMemory:
        """将 ORM 模型转换为 TaskMemory 数据结构。"""

        def _parse_list(data: str, cls: type) -> list:
            try:
                items = json.loads(data)
                return [cls(**item) for item in items]
            except (json.JSONDecodeError, TypeError):
                return []

        return TaskMemory(
            task_id=model.task_id,
            session_id=model.session_id,
            completed_steps=_parse_list(model.completed_steps_json, StepRecord),
            current_step=model.current_step,
            decisions=_parse_list(model.decisions_json, Decision),
            artifacts=_parse_list(model.artifacts_json, ArtifactRef),
            next_steps=_parse_list(model.next_steps_json, NextStep),
            blockers=_parse_list(model.blockers_json, Blocker),
            verification_status=model.verification_status,
            verification_result=json.loads(model.verification_json)
            if model.verification_json
            else {},
        )
