"""任务拆解器 - 将复杂任务拆解为可执行步骤"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class DecomposedStep:
    """拆解后的步骤"""

    description: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    """拆解结果"""

    steps: list[DecomposedStep]
    original_task: str


class TaskDecomposer:
    """任务拆解器"""

    # 复杂任务模式
    COMPLEX_PATTERNS: ClassVar[list[tuple[str, list[str]]]] = [
        (r"创建.*表.*并.*配置.*调度", ["create_table", "configure_schedule"]),
        (r"创建.*表.*并.*设置.*依赖", ["create_table", "add_dependency"]),
        (r"更新.*表.*并.*重新.*部署", ["update_table", "deploy_node"]),
    ]

    def decompose(self, task: str) -> DecompositionResult:
        """拆解任务"""
        task_lower = task.lower().strip()

        # 检查是否是复杂任务
        for pattern, subtasks in self.COMPLEX_PATTERNS:
            if re.search(pattern, task_lower):
                steps = []
                for i, subtask in enumerate(subtasks):
                    step = DecomposedStep(
                        description=f"子任务 {i + 1}: {subtask}",
                        tool=subtask,
                        depends_on=[f"step_{i - 1}"] if i > 0 else [],
                    )
                    steps.append(step)
                return DecompositionResult(steps=steps, original_task=task)

        # 简单任务，返回单步骤
        return DecompositionResult(
            steps=[DecomposedStep(description=task, tool="unknown")],
            original_task=task,
        )
