"""LangGraph Guardrails — 条件路由守卫。

替代原有的 intent_confirm.py + closed_loop_verifier.py。
用 LangGraph 的 conditional edges 表达业务规则。
"""

from __future__ import annotations

from dataworks_agent.runtime.graphs.shared_state import WorkflowState


def require_table_name(state: WorkflowState) -> bool:
    """Guardrail: 建模类操作必须有表名。"""
    next_action = state.get("next_action", "")
    entities = state.get("entities", [])
    if next_action in ("create_table", "modeling", "forward_modeling", "reverse_modeling"):
        # 表名通常包含下划线或特定前缀（如 ods_, dwd_, dim_）
        return any("_" in e or e.startswith(("ods_", "dwd_", "dim_", "dws_")) for e in entities)
    return True


def require_objective(state: WorkflowState) -> bool:
    """Guardrail: 必须有明确目标。"""
    return bool(state.get("objective", "").strip())


def needs_approval(state: WorkflowState) -> bool:
    """Guardrail: 发布操作需要人工审批。"""
    next_action = state.get("next_action", "")
    return next_action in ("deploy", "publish", "create_deployment")


def should_retry(state: WorkflowState) -> str:
    """闭环验证后的路由决策。替代 ClosedLoopVerifier。

    Returns:
        "ship" — 验证通过，交付结果
        "repair" — 验证失败，可重试
        "escalate" — 验证失败，超过最大重试次数
    """
    score = state.get("score", 0.0)
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if score >= 0.9:
        return "ship"
    if retry_count >= max_retries:
        return "escalate"
    return "repair"


def route_next_action(state: WorkflowState) -> str:
    """基于 next_action 路由到正确的节点。替代 coordinator._decompose_task。

    Returns:
        下一个节点的名称（必须是 StateGraph 中注册的节点名）。
    """
    next_action = state.get("next_action", "")
    routing_map: dict[str, str] = {
        "requirement": "requirement",
        "architecture": "architecture",
        "ddl_gen": "ddl_generation",
        "governance_check": "governance",
        "dml_gen": "dml_generation",
        "node_create": "node_creation",
        "query": "query",
        "diagnosis": "diagnosis",
        "deploy": "deploy",
        "ship": "ship",
        "escalate": "escalate",
    }
    return routing_map.get(next_action, "requirement")
