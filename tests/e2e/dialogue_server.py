"""Deterministic no-write FastAPI server used only by browser acceptance."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["AGENT_ACCEPTANCE_MODE"] = "deterministic"
os.environ.setdefault("COOKIE_ENCRYPTION_KEY", "acceptance-only-key")

from dataworks_agent.agent.capabilities import CapabilityState  # noqa: E402
from dataworks_agent.agent.conversation_graph import ConversationGraph  # noqa: E402
from dataworks_agent.agent.core import ChatAgent  # noqa: E402
from dataworks_agent.agent.run_coordinator import AgentRunCoordinator  # noqa: E402
from dataworks_agent.agent.tools.registry import ToolRegistry  # noqa: E402
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool  # noqa: E402
from dataworks_agent.agent.tools.table_inspection import TableInspectionTool  # noqa: E402
from dataworks_agent.routers import agent as agent_router  # noqa: E402
from tests.support.agent_runtime import DeterministicNoWriteProvider  # noqa: E402

DB_PATH = Path(os.environ.get("AGENT_ACCEPTANCE_DB", ROOT / ".runtime" / "acceptance.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
provider = DeterministicNoWriteProvider()


def build_agent() -> ChatAgent:
    graph = ConversationGraph(str(DB_PATH))
    chat_agent = ChatAgent()
    chat_agent._conversation_graph = graph
    chat_agent._run_coordinator = AgentRunCoordinator(
        conversation_graph=graph,
        tools=ToolRegistry(
            [TableDiscoveryTool(provider), TableInspectionTool(provider)]
        ),
    )
    return chat_agent


class DeterministicCapabilities:
    async def snapshot_dict(self, *, force: bool = False):
        del force
        checked_at = "2026-07-20T00:00:00+00:00"
        return {
            "agent_runtime": CapabilityState(True, True, "deterministic acceptance", checked_at).to_dict(),
            "ak_sk": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "openapi": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "maxcompute": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "node_adapter": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "cookie_bff": CapabilityState(True, True, "deterministic metadata", checked_at).to_dict(),
            "cdp_9222": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "official_mcp": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "table_search": CapabilityState(True, True, "deterministic metadata", checked_at).to_dict(),
            "ida_query": CapabilityState(False, False, "disabled in acceptance", checked_at).to_dict(),
            "llm": CapabilityState(True, False, "model_not_found (simulated)", checked_at).to_dict(),
        }


agent_router._agent = build_agent()
agent_router.capability_registry = DeterministicCapabilities()

app = FastAPI()
app.include_router(agent_router.router, prefix="/agent")


@app.get("/api/health")
async def health():
    return {"status": "degraded", "checks": {}, "mode": "deterministic-no-write"}


@app.post("/acceptance/degrade")
async def degrade(payload: dict):
    provider.fail_search = bool(payload.get("enabled"))
    return {"enabled": provider.fail_search}


@app.post("/acceptance/restart")
async def restart():
    old = agent_router._agent
    await old._conversation_graph.aclose()
    agent_router._agent = build_agent()
    return {"restarted": True}


@app.get("/acceptance/evidence")
async def evidence():
    return {
        "mode": "deterministic-no-write",
        "calls": provider.calls,
        "write_calls": [call for call in provider.calls if call["side_effect"] != "read"],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18085, log_level="info")
