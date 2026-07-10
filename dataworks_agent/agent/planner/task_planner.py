"""任务规划器"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.planner.task_graph import TaskGraph


@dataclass
class TaskStep:
    """任务步骤"""
    step_id: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    """任务计划"""
    task_id: str
    steps: list[TaskStep] = field(default_factory=list)
    intent: Intent | None = None


# 任务模板
TASK_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "create_table": [
        {"tool": "create_holo_table", "params": ["table_name", "layer"]},
        {"tool": "create_mc_table", "params": ["table_name"]},
        {"tool": "create_node", "params": ["table_name", "layer"]},
        {"tool": "push_dml", "params": ["table_name"]},
    ],
    "query_lineage": [
        {"tool": "query_lineage", "params": ["table_name"]},
    ],
    "check_status": [
        {"tool": "check_task_status", "params": ["task_id"]},
    ],
}


class TaskPlanner:
    """任务规划器"""

    def plan(self, intent: Intent) -> TaskPlan:
        """根据意图生成任务计划"""
        task_id = f"task_{intent.action}_{hash(intent.raw_text) % 10000}"

        if intent.action == "unknown":
            return TaskPlan(task_id=task_id, steps=[], intent=intent)

        template = TASK_TEMPLATES.get(intent.action, [])
        steps: list[TaskStep] = []

        for i, step_def in enumerate(template):
            params = {
                p: intent.params.get(p)
                for p in step_def["params"]
                if p in intent.params
            }
            step = TaskStep(
                step_id=f"step_{i}",
                tool=step_def["tool"],
                params=params,
                depends_on=[f"step_{i-1}"] if i > 0 else [],
            )
            steps.append(step)

        return TaskPlan(task_id=task_id, steps=steps, intent=intent)
