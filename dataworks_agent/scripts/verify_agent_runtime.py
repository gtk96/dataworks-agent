"""Assertion-based deterministic verification for the conversational Agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.run_coordinator import AgentRunCoordinator
from dataworks_agent.agent.run_models import AgentRunRequest, RunEvent
from dataworks_agent.agent.tools.registry import ToolRegistry
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool
from dataworks_agent.agent.tools.table_inspection import TableInspectionTool
from tests.support.agent_runtime import DeterministicNoWriteProvider


async def verify(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    graph = ConversationGraph(str(output / "conversation-checkpoints.db"))
    provider = DeterministicNoWriteProvider()
    runtime = AgentRunCoordinator(
        conversation_graph=graph,
        tools=ToolRegistry([TableDiscoveryTool(provider), TableInspectionTool(provider)]),
    )
    transcript: list[dict[str, Any]] = []
    events: list[RunEvent] = []

    async def turn(conversation_id: str, message: str):
        response = await runtime.run(
            AgentRunRequest(conversation_id, message),
            emit=events.append,
        )
        transcript.append(
            {
                "conversation_id": conversation_id,
                "message": message,
                "response": {
                    "message": response.message,
                    "success": response.success,
                    "data": response.data,
                    "error": response.error,
                },
            }
        )
        return response

    try:
        candidates = await turn("verify-primary", "找订单表")
        assert candidates.data["interaction"]["purpose"] == "select_table"
        explained = await turn("verify-primary", "什么意思")
        assert explained.data["interaction"]["purpose"] == "select_table"
        selected = await turn("verify-primary", "第二个")
        assert selected.data["conversation"]["selected_resources"]["table"] == (
            "dw.dws_orders_summary"
        )
        columns = await turn("verify-primary", "查看字段")
        assert len(columns.data["columns"]) == 2

        versions: list[int] = []
        for _ in range(10):
            found = await turn("verify-50", "找订单表")
            versions.append(found.data["conversation"]["state_version"])
            explained = await turn("verify-50", "什么意思")
            versions.append(explained.data["conversation"]["state_version"])
            selected = await turn("verify-50", "第一个")
            versions.append(selected.data["conversation"]["state_version"])
            inspected = await turn("verify-50", "查看字段")
            versions.append(inspected.data["conversation"]["state_version"])
            greeting = await turn("verify-50", "你好")
            versions.append(greeting.data["conversation"]["state_version"])

        assert len(versions) == 50
        assert versions == sorted(versions)
        assert len(set(versions)) == 50
        assert sum(event.type == "response.completed" for event in events) == 54
        provider.assert_no_writes()

        (output / "conversation-transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output / "backend-events.jsonl").write_text(
            "".join(json.dumps(event.to_dict(), ensure_ascii=False) + "\n" for event in events),
            encoding="utf-8",
        )
        (output / "no-write-proof.json").write_text(
            json.dumps(
                {
                    "verified": True,
                    "call_count": len(provider.calls),
                    "side_effects": sorted({call["side_effect"] for call in provider.calls}),
                    "calls": provider.calls,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (output / "summary.md").write_text(
            "# Backend Agent Runtime Verification\n\n"
            f"- Turns: {len(transcript)}\n"
            f"- Events: {len(events)}\n"
            f"- Tool calls: {len(provider.calls)}\n"
            "- Write-capable calls: 0\n"
            "- Result: PASS\n",
            encoding="utf-8",
        )
    finally:
        await graph.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(verify(args.output.resolve()))


if __name__ == "__main__":
    main()
