"""Runtime API — Agent 运行时协议对象与生命周期。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


def _publish_gate():
    from dataworks_agent.runtime.publish_gate import PublishGate
    from dataworks_agent.state import app_state

    gate = getattr(app_state, "_publish_gate", None)
    if gate is None:
        gate = PublishGate()
        app_state._publish_gate = gate
    return gate


class SessionRequest(BaseModel):
    """会话请求。"""

    task_id: str = Field(..., description="任务 ID")
    task_type: str = Field(default="modeling", description="任务类型")


class RunRequest(BaseModel):
    """运行请求。"""

    session_id: str = Field(..., description="会话 ID")
    request_data: dict[str, Any] = Field(default_factory=dict, description="请求数据")
    actor: str = Field(default="", description="操作者")


class AgentRequest(BaseModel):
    """Agent 请求。"""

    request_type: str = Field(..., description="请求类型: modeling/query/clarification")
    content: str = Field(..., description="自然语言内容")
    context: dict[str, Any] = Field(default_factory=dict, description="上下文")
    user_id: str = Field(default="", description="用户 ID")


@router.post("/sessions")
async def create_session(body: SessionRequest):
    """创建会话。"""
    from dataworks_agent.runtime.service import RuntimeService

    service = RuntimeService()
    session = service.create_session(
        task_id=body.task_id,
        task_type=body.task_type,
    )

    return {
        "session_id": session.session_id,
        "task_id": session.task_id,
        "task_type": session.task_type,
        "status": session.status,
    }


@router.post("/runs")
async def start_run(body: RunRequest):
    """启动运行。"""
    from dataworks_agent.runtime.service import RuntimeService

    service = RuntimeService()
    run = await service.start_run(
        session_id=body.session_id,
        request=body.request_data,
        actor=body.actor,
    )

    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status.value,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """获取运行状态。"""
    from dataworks_agent.runtime.service import RuntimeService

    service = RuntimeService()
    run = await service.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")

    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status.value,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """取消运行。"""
    from dataworks_agent.runtime.service import RuntimeService

    service = RuntimeService()
    success = await service.cancel_run(run_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在或无法取消")

    return {"status": "ok", "run_id": run_id}


@router.post("/runs/{run_id}/interrupt")
async def interrupt_run(run_id: str, payload: dict[str, Any] | None = None):
    """中断运行（等待审批）。"""
    from dataworks_agent.runtime.service import RuntimeService

    if payload is None:
        payload = {}

    service = RuntimeService()
    success = await service.interrupt_run(run_id, payload)

    if not success:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在或无法中断")

    return {"status": "ok", "run_id": run_id}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, decision: dict[str, Any] | None = None):
    """恢复运行。"""
    from dataworks_agent.runtime.service import RuntimeService

    if decision is None:
        decision = {}

    service = RuntimeService()
    success = await service.resume_run(run_id, decision)

    if not success:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在或无法恢复")

    return {"status": "ok", "run_id": run_id}


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str):
    """重试运行。"""
    from dataworks_agent.runtime.service import RuntimeService

    service = RuntimeService()
    success = await service.retry_run(run_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在或无法重试")

    return {"status": "ok", "run_id": run_id}


@router.post("/agent")
async def process_agent(body: AgentRequest):
    """处理 Agent 请求。"""
    from dataworks_agent.runtime.agent import Agent
    from dataworks_agent.runtime.agent import AgentRequest as AgentRequestObj

    agent = Agent()
    request = AgentRequestObj(
        request_type=body.request_type,
        content=body.content,
        context=body.context,
        user_id=body.user_id,
    )
    response = await agent.process(request)

    return {
        "success": response.success,
        "response_type": response.response_type,
        "content": response.content,
        "data": response.data,
        "errors": response.errors,
        "needs_approval": response.needs_approval,
    }


@router.post("/forward-model")
async def forward_model(body: dict[str, Any]):
    """正向建模。"""
    from dataworks_agent.runtime.forward_flow import ForwardModelingFlow, ModelingRequest

    flow = ForwardModelingFlow()
    request = ModelingRequest(
        source_table=body.get("source_table", ""),
        target_layer=body.get("target_layer", ""),
        domain=body.get("domain", ""),
        entity=body.get("entity", ""),
        update_method=body.get("update_method", "day"),
        dry_run=body.get("dry_run", True),
    )
    result = await flow.execute(request)

    return {
        "success": result.success,
        "target_table": result.target_table,
        "ddl": result.ddl,
        "sql": result.sql,
        "node_uuid": result.node_uuid,
        "errors": result.errors,
        "steps": result.steps,
    }


@router.post("/reverse-model")
async def reverse_model(body: dict[str, Any]):
    """逆向建模。"""
    from dataworks_agent.runtime.reverse_flow import ReverseModelingFlow, ReverseModelingRequest

    flow = ReverseModelingFlow()
    request = ReverseModelingRequest(
        source_type=body.get("source_type", ""),
        source_value=body.get("source_value", ""),
    )
    result = await flow.execute(request)

    return {
        "success": result.success,
        "table_name": result.table_name,
        "layer": result.layer,
        "domain": result.domain,
        "columns": result.columns,
        "upstream_tables": result.upstream_tables,
        "errors": result.errors,
    }


@router.post("/attribution")
async def diagnose_attribution(body: dict[str, Any]):
    """指标归因诊断。"""
    from dataworks_agent.runtime.attribution import AnomalyReport, MetricAttributor

    attributor = MetricAttributor()
    report = AnomalyReport(
        report_id=body.get("report_id", ""),
        metric_id=body.get("metric_id", ""),
        expected_value=body.get("expected_value"),
        actual_value=body.get("actual_value"),
        context=body.get("context", {}),
    )
    result = await attributor.diagnose(report)

    return {
        "report_id": result.report_id,
        "metric_id": result.metric_id,
        "root_cause": result.root_cause.value if result.root_cause else None,
        "explanation": result.explanation,
        "resolved": result.resolved,
    }


@router.post("/self-heal")
async def self_heal(body: dict[str, Any]):
    """自愈流程。"""
    from dataworks_agent.runtime.self_heal import IssueReport, IssueType, SelfHealFlow

    flow = SelfHealFlow()
    issue = IssueReport(
        issue_id=body.get("issue_id", ""),
        issue_type=IssueType(body.get("issue_type", "schedule_failure")),
        source=body.get("source", ""),
        description=body.get("description", ""),
        context=body.get("context", {}),
    )
    proposal = await flow.diagnose(issue)
    result = await flow.execute(proposal)

    return {
        "proposal_id": proposal.proposal_id,
        "action": proposal.action.value,
        "requires_approval": proposal.requires_approval,
        "success": result.success,
        "message": result.message,
    }


@router.post("/publish-gate/interrupt")
async def publish_gate_interrupt(body: dict[str, Any]):
    """发布审批中断。"""
    request = await _publish_gate().interrupt_for_approval(
        run_id=body.get("run_id", ""),
        session_id=body.get("session_id", ""),
        table_name=body.get("table_name", ""),
        change_type=body.get("change_type", ""),
        payload=body.get("payload", {}),
    )

    return {
        "request_id": request.request_id,
        "status": request.status,
        "table_name": request.table_name,
    }


@router.get("/publish-gate/requests")
async def list_publish_requests():
    """列出待审批请求。"""
    requests = await _publish_gate().list_pending_requests()

    return {
        "requests": [
            {
                "request_id": r.request_id,
                "table_name": r.table_name,
                "change_type": r.change_type,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in requests
        ],
        "total": len(requests),
    }
