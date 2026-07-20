"""Assert the live web Agent's table-discovery behavior without performing writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

_CANARY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_TOOLS = {
    "create_node",
    "update_node",
    "delete_node",
    "deploy_node",
    "deploy_nodes",
    "publish",
    "execute_ddl",
    "create_folder",
    "create_package",
}
_AUTH_CODES = {"cookie_auth_required", "cookie_decrypt_failed"}


def _capability(health: dict[str, Any], capabilities: dict[str, Any], name: str) -> dict[str, Any]:
    health_caps = health.get("capabilities") or {}
    direct_caps = capabilities.get("capabilities") or capabilities
    value = health_caps.get(name) or direct_caps.get(name) or {}
    return value if isinstance(value, dict) else {}


def _candidate_names(response: dict[str, Any]) -> list[str]:
    data = response.get("data") or {}
    names = [
        str(item.get("full_name") or "")
        for item in data.get("candidates") or []
        if isinstance(item, dict)
    ]
    interaction = data.get("interaction") or {}
    for option in interaction.get("options") or []:
        if not isinstance(option, dict):
            continue
        params = (option.get("payload") or {}).get("params") or {}
        name = str(params.get("table_name") or "")
        if name:
            names.append(name)
    return list(dict.fromkeys(name for name in names if name))


def evaluate_evidence(
    *,
    health: dict[str, Any],
    capabilities: dict[str, Any],
    transcript: list[dict[str, Any]],
    stream_events: list[dict[str, Any]],
    persisted_events: list[dict[str, Any]],
    canary: str | None,
) -> dict[str, Any]:
    """Return a deterministic verdict over already-collected read-only evidence."""

    violations: list[str] = []
    discovery_turn = next((item for item in transcript if item.get("label") == "discovery"), {})
    discovery = discovery_turn.get("response") or {}
    discovery_data = discovery.get("data") or {}
    candidate_names = _candidate_names(discovery)
    discovery_error = str(discovery.get("error") or "")
    discovery_message = str(discovery.get("message") or "")
    discovery_status = str(discovery_data.get("discovery_status") or "")
    bff = _capability(health, capabilities, "cookie_bff")
    bff_online = bool(bff.get("online"))
    bff_status = str(bff.get("status") or "")
    no_match = discovery_status == "not_found" or "没有找到" in discovery_message

    if no_match and not bff_online:
        violations.append("false_no_match_while_bff_offline")
    if not canary and bff_status in _AUTH_CODES and discovery_error != "table_search_auth_required":
        violations.append("auth_failure_not_preserved")

    for item in transcript:
        response = item.get("response") or {}
        data = response.get("data") or {}
        if (
            response.get("error") == "execution_unknown"
            or data.get("agent_mode") == "execution_unknown"
        ):
            violations.append("execution_unknown_response")

    for event in [*stream_events, *persisted_events]:
        data = event.get("data") if isinstance(event.get("data"), dict) else event
        event_type = str(event.get("type") or event.get("event") or "")
        tool = str(data.get("tool") or "")
        if tool in _FORBIDDEN_TOOLS:
            violations.append(f"forbidden_tool:{tool}")
        if event_type == "tool.started":
            side_effect = str(data.get("side_effect") or "")
            if side_effect and side_effect != "read":
                violations.append(f"non_read_side_effect:{tool}:{side_effect}")
        if data.get("uncertain_write") is True:
            violations.append(f"uncertain_write:{tool}")
        if data.get("write_boundary_crossed") is True:
            violations.append("write_boundary_crossed")

    expected_canary = canary or ""
    if canary:
        if expected_canary not in candidate_names:
            violations.append("expected_canary_miss")
        classification = "live_candidate_success" if not violations else "failed"
    else:
        classification = "dependency_only_no_canary" if not violations else "failed"

    providers = sorted(
        {
            str(data.get("provider") or "")
            for event in [*stream_events, *persisted_events]
            for data in [event.get("data") if isinstance(event.get("data"), dict) else event]
            if data.get("provider")
        }
        | ({str(discovery_data.get("provider"))} if discovery_data.get("provider") else set())
    )
    return {
        "passed": not violations,
        "classification": classification,
        "canary": expected_canary or None,
        "candidate_names": candidate_names,
        "providers": providers,
        "bff_online": bff_online,
        "bff_status": bff_status,
        "violations": list(dict.fromkeys(violations)),
    }


async def _json(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    response = await client.get(path)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object from {path}")
    return payload


async def _turn(
    client: httpx.AsyncClient,
    *,
    conversation_id: str,
    label: str,
    message: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    async with client.stream(
        "POST",
        "/agent/runs/stream",
        json={
            "message": message,
            "conversation_id": conversation_id,
            "execution_mode": "auto",
            "initialize_data": True,
            "publish": False,
        },
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.strip():
                events.append(json.loads(line))
    completed = [event for event in events if event.get("type") == "response.completed"]
    if len(completed) != 1:
        raise RuntimeError(f"{label}: expected one response.completed, got {len(completed)}")
    agent_response = (completed[0].get("data") or {}).get("response") or {}
    return (
        {"label": label, "request": {"message": message}, "response": agent_response},
        events,
    )


async def verify(
    *,
    base_url: str,
    output: Path,
    canary: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    conversation_id = f"live-verify-{uuid4().hex[:16]}"
    transcript: list[dict[str, Any]] = []
    stream_events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(timeout_seconds),
        trust_env=False,
    ) as client:
        health = await _json(client, "/api/health")
        capabilities = await _json(client, "/agent/capabilities?force=true")
        table_keyword = canary.split(".", 1)[1] if canary else "订单"
        turns = [
            ("greeting", "你好"),
            ("discovery", f"找 {table_keyword} 表"),
            ("explain", "什么意思"),
        ]
        if not canary:
            turns.extend([("new_goal", "找退款表"), ("greeting_after", "你好")])
        for label, message in turns:
            turn, events = await _turn(
                client,
                conversation_id=conversation_id,
                label=label,
                message=message,
            )
            transcript.append(turn)
            stream_events.extend(events)
        persisted = await _json(
            client, f"/api/logs/conversations?conversation_id={conversation_id}&limit=5000"
        )
        messages = await _json(
            client, f"/agent/messages?conversation_id={conversation_id}&limit=50"
        )

    persisted_events = list(persisted.get("events") or [])
    verdict = evaluate_evidence(
        health=health,
        capabilities=capabilities,
        transcript=transcript,
        stream_events=stream_events,
        persisted_events=persisted_events,
        canary=canary,
    )
    artifacts = {
        "health.json": health,
        "capabilities.json": capabilities,
        "conversation-transcript.json": transcript,
        "stream-events.json": stream_events,
        "persisted-events.json": persisted_events,
        "conversation-state.json": messages,
        "write-audit.json": {
            "verified": verdict["passed"],
            "forbidden_tools": sorted(_FORBIDDEN_TOOLS),
            "violations": verdict["violations"],
        },
        "verdict.json": verdict,
    }
    for filename, payload in artifacts.items():
        (output / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    timestamp = datetime.now(UTC).isoformat()
    (output / "summary.md").write_text(
        "# Live Table Discovery Verification\n\n"
        f"- Checked at: {timestamp}\n"
        f"- Base URL: {base_url}\n"
        f"- Conversation: {conversation_id}\n"
        f"- Classification: {verdict['classification']}\n"
        f"- Canary: {verdict['canary'] or 'not configured'}\n"
        f"- Providers: {', '.join(verdict['providers']) or 'none observed'}\n"
        f"- Candidate names: {', '.join(verdict['candidate_names']) or 'none'}\n"
        f"- Violations: {', '.join(verdict['violations']) or 'none'}\n"
        f"- Result: {'PASS' if verdict['passed'] else 'FAIL'}\n",
        encoding="utf-8",
    )
    if not verdict["passed"]:
        raise RuntimeError("Live verification failed: " + ", ".join(verdict["violations"]))
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--canary")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    canary = str(args.canary or "").strip() or None
    if canary and not _CANARY_RE.fullmatch(canary):
        parser.error("--canary must use project.table with safe identifiers")
    verdict = asyncio.run(
        verify(
            base_url=args.base_url,
            output=args.output.resolve(),
            canary=canary,
            timeout_seconds=args.timeout_seconds,
        )
    )
    print(json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()
