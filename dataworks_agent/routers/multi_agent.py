"""多 Agent 协调 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/multi-agent", tags=["multi-agent"])


class IntentRequest(BaseModel):
    intent: str
    params: dict[str, object] = {}


def _build_coordinator():
    from dataworks_agent.agent.multi_agent.coordinator import AgentCoordinator
    from dataworks_agent.agent.multi_agent.diagnosis_agent import DiagnosisAgent
    from dataworks_agent.agent.multi_agent.governance_agent import GovernanceAgent
    from dataworks_agent.agent.multi_agent.modeling_agent import ModelingAgent
    from dataworks_agent.agent.multi_agent.query_agent import QueryAgent

    return AgentCoordinator([ModelingAgent(), DiagnosisAgent(), QueryAgent(), GovernanceAgent()])


@router.post("/route")
async def route_intent(req: IntentRequest):
    coordinator = _build_coordinator()
    agent = await coordinator.route_task(req.intent, req.params, None)
    return {
        "agent_type": agent.agent_type if agent else None,
        "available_agents": coordinator.list_available_agents(),
    }


@router.get("/agents")
async def list_agents():
    coordinator = _build_coordinator()
    return {"agents": coordinator.list_available_agents()}
