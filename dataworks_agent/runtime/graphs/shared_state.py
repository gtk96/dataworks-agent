"""LangGraph 共享状态定义。

所有 Agent 节点读写同一个 WorkflowState，替代原有的 SpecFile/SpecStore 机制。
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class WorkflowState(TypedDict):
    """Agent 间共享的状态字典。

    所有节点（Requirement, Modeling, Query, Diagnosis, Governance, Architecture）
    读写同一个 WorkflowState，不需要 SpecFile 传递。
    """

    # ── 对话历史（add_messages 自动合并，支持时间旅行） ──
    messages: NotRequired[list]

    # ── 业务上下文 ──
    objective: NotRequired[str]                    # 当前目标（用户原始需求）
    entities: NotRequired[list[str]]               # 涉及的表/指标/任务
    resolved_params: NotRequired[dict[str, Any]]   # 已确认的参数
    pending_decisions: NotRequired[list[dict]]     # 待确认的决策点

    # ── 产物引用 ──
    artifacts: NotRequired[dict[str, Any]]         # 已生成的产物（DDL/DML/节点ID）
    artifact_refs: NotRequired[list[str]]          # 产物引用列表

    # ── 决策链 ──
    decision_log: NotRequired[list[dict]]          # Agent 间决策记录

    # ── 执行状态 ──
    next_action: NotRequired[str]                  # 下一步动作（路由用）
    retry_count: NotRequired[int]                  # 重试计数（循环控制）
    score: NotRequired[float]                      # 验证分数（闭环控制）
    agent_name: NotRequired[str]                   # 当前执行 Agent 名称

    # ── 错误处理 ──
    errors: NotRequired[list[str]]                 # 执行错误列表
    error: NotRequired[str]                        # 最近错误
