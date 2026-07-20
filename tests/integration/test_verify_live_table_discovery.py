from dataworks_agent.scripts.verify_live_table_discovery import evaluate_evidence


def _health(*, bff_online: bool) -> dict:
    return {"capabilities": {"cookie_bff": {"online": bff_online}}}


def _turn(*, error: str | None, message: str, data: dict | None = None) -> dict:
    return {
        "label": "discovery",
        "response": {"error": error, "message": message, "data": data or {}},
    }


def test_offline_auth_failure_is_dependency_only_not_false_no_match() -> None:
    result = evaluate_evidence(
        health=_health(bff_online=False),
        capabilities={},
        transcript=[
            _turn(
                error="table_search_auth_required",
                message="当前表搜索鉴权不可用",
                data={"agent_mode": "recoverable_error", "provider": "cookie_bff"},
            )
        ],
        stream_events=[],
        persisted_events=[],
        canary=None,
    )

    assert result["classification"] == "dependency_only_no_canary"
    assert result["violations"] == []


def test_offline_provider_cannot_claim_authenticated_no_match() -> None:
    result = evaluate_evidence(
        health=_health(bff_online=False),
        capabilities={},
        transcript=[
            _turn(
                error=None,
                message="没有找到订单对应的可靠表候选",
                data={"agent_mode": "waiting_user", "discovery_status": "not_found"},
            )
        ],
        stream_events=[],
        persisted_events=[],
        canary=None,
    )

    assert "false_no_match_while_bff_offline" in result["violations"]


def test_configured_canary_must_be_returned_by_live_provider() -> None:
    result = evaluate_evidence(
        health=_health(bff_online=True),
        capabilities={},
        transcript=[
            _turn(
                error=None,
                message="找到候选表",
                data={
                    "agent_mode": "tool_result",
                    "provider": "maxcompute",
                    "candidates": [{"full_name": "dev.some_other_table"}],
                },
            )
        ],
        stream_events=[],
        persisted_events=[],
        canary="dev.expected_table",
    )

    assert "expected_canary_miss" in result["violations"]


def test_any_write_or_execution_unknown_evidence_fails() -> None:
    result = evaluate_evidence(
        health=_health(bff_online=True),
        capabilities={},
        transcript=[
            _turn(
                error="execution_unknown",
                message="结果不确定",
                data={"agent_mode": "execution_unknown"},
            )
        ],
        stream_events=[{"type": "tool.started", "data": {"tool": "create_node"}}],
        persisted_events=[
            {"event": "tool.started", "tool": "find_table", "side_effect": "write"},
            {"event": "tool.completed", "tool": "find_table", "uncertain_write": True},
        ],
        canary=None,
    )

    assert set(result["violations"]) >= {
        "execution_unknown_response",
        "forbidden_tool:create_node",
        "non_read_side_effect:find_table:write",
        "uncertain_write:find_table",
    }
