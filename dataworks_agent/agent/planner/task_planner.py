"""Task planner for DataWorks Agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.planner.task_graph import TaskGraph

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    """Task step."""

    step_id: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    phase: str = "execute"
    risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "params": self.params,
            "depends_on": self.depends_on,
            "title": self.title or self.tool,
            "description": self.description,
            "phase": self.phase,
            "risk": self.risk,
        }


@dataclass
class TaskPlan:
    """Task plan."""

    task_id: str
    steps: list[TaskStep] = field(default_factory=list)
    intent: Intent | None = None
    summary: str = ""
    assumptions: list[str] = field(default_factory=list)
    needs_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "summary": self.summary,
            "assumptions": self.assumptions,
            "needs_confirmation": self.needs_confirmation,
            "steps": [step.to_dict() for step in self.steps],
        }


TASK_TEMPLATES: dict[str, dict[str, Any]] = {
    "create_table": {
        "summary": "Create table and DataWorks node proposal",
        "assumptions": ["Dry-run/proposal first; publish still needs approval."],
        "steps": [
            {"tool": "create_holo_table", "params": ["table_name", "layer", "source_table"], "title": "Prepare source/Holo structure", "phase": "design"},
            {"tool": "create_mc_table", "params": ["table_name", "source_table"], "title": "Draft MaxCompute DDL", "phase": "design"},
            {"tool": "create_node", "params": ["table_name", "layer"], "title": "Draft DataWorks node", "phase": "orchestrate"},
            {"tool": "push_dml", "params": ["table_name", "source_table"], "title": "Draft DML and dependencies", "phase": "orchestrate", "risk": "medium"},
        ],
    },
    "query_lineage": {
        "summary": "Query lineage and impact scope",
        "assumptions": ["Use Cookie fallback for downstream lineage when AK/SK metadata permission is unavailable."],
        "steps": [
            {"tool": "query_lineage", "params": ["table_name", "depth"], "title": "Query lineage", "phase": "inspect"},
            {"tool": "summarize_lineage_impact", "params": ["table_name", "depth"], "title": "Summarize impact scope", "phase": "inspect"},
        ],
    },
    "check_status": {
        "summary": "Check current task status",
        "assumptions": ["When task_id is omitted, use latest Agent task in memory."],
        "steps": [
            {"tool": "check_task_status", "params": ["task_id"], "title": "Read execution status", "phase": "inspect"},
        ],
    },
    "ods_dwd_modeling": {
        "summary": "Conversational ODS to DWD modeling proposal",
        "assumptions": [
            "Generate dry-run/preview artifacts before online writes.",
            "ODS execution route is selected by source type; DWD preview reuses deterministic generators when metadata is sufficient.",
            "Publish and online writes require Publish Gate approval.",
        ],
        "steps": [
            {"tool": "analyze_ods_dwd_requirement", "params": ["goal", "table_name", "source_table", "source_type", "datasource_name", "oss_path", "ods_table", "dwd_table", "granularity", "schedule_cycle", "schedule_minute", "domain"], "title": "Understand ODS+DWD goal", "phase": "understand"},
            {"tool": "classify_ods_source", "params": ["goal", "source_table", "source_type", "datasource_name", "oss_path", "ods_table", "granularity"], "title": "Select ODS route", "phase": "plan"},
            {"tool": "plan_ods_pipeline", "params": ["goal", "source_table", "source_type", "datasource_name", "oss_path", "ods_table", "granularity", "schedule_minute", "domain"], "title": "Plan ODS pipeline", "phase": "plan", "risk": "medium"},
            {"tool": "preview_dwd_artifacts", "params": ["goal", "table_name", "source_table", "source_type", "datasource_name", "oss_path", "ods_table", "dwd_table", "granularity", "schedule_cycle", "domain"], "title": "Preview DWD artifacts", "phase": "draft", "risk": "medium"},
            {"tool": "plan_ods_dwd_dependencies", "params": ["goal", "table_name", "source_table", "source_type", "datasource_name", "oss_path", "ods_table", "dwd_table", "granularity", "schedule_minute"], "title": "Plan ODS+DWD dependencies", "phase": "orchestrate"},
            {"tool": "validate_guardrails", "params": ["table_name", "dwd_table", "ods_table", "layer"], "title": "Validate guardrails", "phase": "guardrail"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name", "ods_table", "dwd_table"], "title": "Recommend next actions", "phase": "next"},
        ],
    },
    "forward_modeling": {
        "summary": "Goal-driven forward modeling proposal",
        "assumptions": ["Generate artifacts in dry-run mode before any DataWorks write.", "Publish requires approval."],
        "steps": [
            {"tool": "analyze_requirement", "params": ["goal", "table_name", "source_table", "layer", "domain", "schedule_cycle"], "title": "Understand modeling goal", "phase": "understand"},
            {"tool": "forward_modeling_dry_run", "params": ["goal", "table_name", "source_table", "layer", "domain", "schedule_cycle"], "title": "Generate modeling dry-run", "phase": "draft", "risk": "medium"},
            {"tool": "validate_guardrails", "params": ["table_name", "layer"], "title": "Validate guardrails", "phase": "guardrail"},
            {"tool": "draft_execution_artifacts", "params": ["goal", "table_name", "source_table", "layer"], "title": "Package artifacts", "phase": "draft", "risk": "medium"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name"], "title": "Recommend next actions", "phase": "next"},
        ],
    },
    "reverse_modeling": {
        "summary": "Reverse modeling inspection proposal",
        "assumptions": ["Inspect existing tables and draft candidates only."],
        "steps": [
            {"tool": "reverse_modeling_inspect", "params": ["goal", "table_name", "source_table", "layer"], "title": "Inspect existing model", "phase": "inspect"},
            {"tool": "validate_guardrails", "params": ["table_name", "layer"], "title": "Validate guardrails", "phase": "guardrail"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name"], "title": "Recommend next actions", "phase": "next"},
        ],
    },
    "diagnose_issue": {
        "summary": "Diagnose task or data issue and propose recovery",
        "assumptions": ["Diagnostics are read-only until an explicit recovery action is approved."],
        "steps": [
            {"tool": "check_task_status", "params": ["task_id"], "title": "Read task status", "phase": "inspect"},
            {"tool": "diagnose_self_heal", "params": ["goal", "task_id", "table_name"], "title": "Diagnose issue", "phase": "inspect"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name"], "title": "Recommend recovery", "phase": "next"},
        ],
    },
    "metric_attribution": {
        "summary": "Metric attribution diagnosis proposal",
        "assumptions": ["Use semantic metadata and lineage; do not send production row data to LLM."],
        "steps": [
            {"tool": "diagnose_metric_attribution", "params": ["goal", "metric_id", "table_name"], "title": "Diagnose metric attribution", "phase": "inspect"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name"], "title": "Recommend next actions", "phase": "next"},
        ],
    },
    "publish_review": {
        "summary": "Publish Gate review proposal",
        "assumptions": ["Direct online publish is blocked until approval."],
        "steps": [
            {"tool": "validate_guardrails", "params": ["table_name", "layer"], "title": "Validate publish guardrails", "phase": "guardrail", "risk": "medium"},
            {"tool": "publish_gate_review", "params": ["goal", "table_name", "layer"], "title": "Prepare Publish Gate review", "phase": "guardrail", "risk": "high"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name"], "title": "Recommend approval path", "phase": "next"},
        ],
    },
    "agent_workflow": {
        "summary": "End-to-end DataWorks Agent workflow",
        "assumptions": ["Plan and validate in dry-run/proposal mode first.", "AK/SK and Cookie fallback coexist by capability matrix."],
        "steps": [
            {"tool": "analyze_requirement", "params": ["goal", "table_name", "source_table", "layer", "domain", "schedule_cycle"], "title": "Understand goal", "phase": "understand"},
            {"tool": "collect_context", "params": ["goal", "table_name", "source_table", "layer"], "title": "Collect context", "phase": "inspect"},
            {"tool": "plan_dataworks_workflow", "params": ["goal", "table_name", "source_table", "layer"], "title": "Plan workflow", "phase": "plan"},
            {"tool": "validate_guardrails", "params": ["table_name", "layer"], "title": "Validate guardrails", "phase": "guardrail"},
            {"tool": "draft_execution_artifacts", "params": ["goal", "table_name", "source_table", "layer"], "title": "Draft artifacts", "phase": "draft", "risk": "medium"},
            {"tool": "recommend_next_actions", "params": ["goal", "table_name"], "title": "Recommend next actions", "phase": "next"},
        ],
    },
}

DATAWORKS_KEYWORDS = (
    "dataworks", "数仓", "建模", "模型", "调度", "节点", "血缘", "依赖", "治理", "质量", "异常", "指标", "口径", "发布", "上线", "ddl", "dml", "ods_", "dwd_", "dws_", "dim_", "dmr_", "ads_",
)


class TaskPlanner:
    """Task planner."""

    def plan(self, intent: Intent) -> TaskPlan:
        task_id = f"task_{intent.action}_{abs(hash(intent.raw_text)) % 10000}"

        if intent.action == "unknown":
            steps = self._llm_plan(intent.raw_text)
            if steps:
                return TaskPlan(
                    task_id=task_id,
                    steps=steps,
                    intent=intent,
                    summary="Fallback DataWorks Agent plan",
                    assumptions=["No fixed template matched; use safe dry-run workflow."],
                    needs_confirmation=True,
                )
            logger.info("Unknown intent, empty plan: %s", intent.raw_text)
            return TaskPlan(
                task_id=task_id,
                steps=[],
                intent=intent,
                summary="No executable intent recognized",
                assumptions=["Need DataWorks target, table name, or action."],
                needs_confirmation=True,
            )

        template = TASK_TEMPLATES.get(intent.action, {"steps": []})
        steps = self._steps_from_template(template, intent)

        graph = self._build_dependency_graph(steps)
        if not graph.validate():
            logger.warning("Detected cyclic dependencies; using linear order")

        return TaskPlan(
            task_id=task_id,
            steps=steps,
            intent=intent,
            summary=template.get("summary", "DataWorks Agent plan"),
            assumptions=list(template.get("assumptions", [])),
            needs_confirmation=bool(intent.is_negated or intent.confidence < 0.5),
        )

    def _steps_from_template(self, template: dict[str, Any], intent: Intent) -> list[TaskStep]:
        steps: list[TaskStep] = []
        for i, step_def in enumerate(template.get("steps", [])):
            params = {p: intent.params.get(p) for p in step_def.get("params", []) if intent.params.get(p) is not None}
            steps.append(
                TaskStep(
                    step_id=f"step_{i}",
                    tool=step_def["tool"],
                    params=params,
                    depends_on=[f"step_{i - 1}"] if i > 0 else [],
                    title=step_def.get("title", step_def["tool"]),
                    description=step_def.get("description", ""),
                    phase=step_def.get("phase", "execute"),
                    risk=step_def.get("risk", "low"),
                )
            )
        return steps

    def _llm_plan(self, task_description: str) -> list[TaskStep]:
        """Return fallback planning steps for DataWorks-shaped unknown goals.

        A true LLM planner can be wired here later through dataworks_agent.llm.service
        and RowDataGuard. Until then, use a deterministic safe workflow so relevant
        goals do not collapse into an empty plan.
        """
        text = task_description.lower()
        if not any(keyword in text for keyword in DATAWORKS_KEYWORDS):
            return []
        intent = Intent(
            action="agent_workflow",
            params={"goal": task_description},
            confidence=0.45,
            raw_text=task_description,
            is_negated=False,
        )
        return self._steps_from_template(TASK_TEMPLATES["agent_workflow"], intent)

    def _build_dependency_graph(self, steps: list[TaskStep]) -> TaskGraph:
        graph = TaskGraph()
        for step in steps:
            graph.add_node(step.step_id, tool=step.tool)
        for step in steps:
            for dep in step.depends_on:
                graph.add_edge(dep, step.step_id)
        return graph
