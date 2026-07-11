from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.workflow_service import AgentWorkflowService
from dataworks_agent.state import app_state


@pytest.fixture(autouse=True)
def restore_app_state():
    names = [
        "_maxcompute_client",
        "_node_client",
        "_bff_client",
        "_openapi_client",
        "_official_mcp_client",
        "_publish_gate",
    ]
    before = {name: getattr(app_state, name, None) for name in names}
    yield
    for name, value in before.items():
        setattr(app_state, name, value)


@pytest.mark.asyncio
async def test_forward_plan_does_not_require_execution_clients():
    service = AgentWorkflowService()
    result = await service.execute(
        message="plan ods_shop_order dwd_shop_order dim_shop dws_shop_day",
        action="forward_modeling",
        params={"source_table": "orders", "datasource_name": "shop"},
        execution_mode="plan",
    )

    assert result.success is True
    assert result.mode == "plan"
    assert any(step["step"] == "create_ods_table_and_di_node" for step in result.steps)


@pytest.mark.asyncio
async def test_dev_execute_builds_all_layers(monkeypatch):
    service = AgentWorkflowService()
    app_state._maxcompute_client = object()
    app_state._node_client = object()
    service._execute_ods = AsyncMock(return_value={"success": True})
    service._deploy_warehouse_layer = AsyncMock(
        side_effect=lambda layer, source, target, granularity, minute: {
            "success": True,
            "ddl": f"create {target}",
            "sql": f"insert {target}",
            "node_uuid": f"node-{target}",
        }
    )

    result = await service.execute(
        message="execute ods_shop_order dwd_shop_order dim_shop dws_shop_day",
        action="forward_modeling",
        params={"source_table": "orders", "datasource_name": "shop"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert [item["layer"] for item in result.data["executed"]] == [
        "ODS",
        "DWD",
        "DIM",
        "DWS",
    ]
    service._execute_ods.assert_awaited_once()
    assert service._deploy_warehouse_layer.await_count == 3


@pytest.mark.asyncio
async def test_publish_request_is_created_after_dev_execution():
    service = AgentWorkflowService()
    app_state._maxcompute_client = object()
    app_state._node_client = object()
    service._execute_ods = AsyncMock(return_value={"success": True})
    service._deploy_warehouse_layer = AsyncMock(return_value={"success": True})
    gate = SimpleNamespace(
        interrupt_for_approval=AsyncMock(
            return_value=SimpleNamespace(request_id="pub-1", __dict__={"request_id": "pub-1"})
        )
    )
    app_state._publish_gate = gate

    result = await service.execute(
        message="execute ods_shop_order dwd_shop_order",
        action="forward_modeling",
        params={"source_table": "orders", "datasource_name": "shop"},
        execution_mode="dev_execute",
        publish=True,
    )

    assert result.success is True
    assert result.data["executed"]
    assert result.data["publish_gate"] == "approval_required"
    gate.interrupt_for_approval.assert_awaited_once()


def test_readonly_guard_rejects_write_sql():
    service = AgentWorkflowService()
    with pytest.raises(ValueError):
        service._validate_readonly_sql("INSERT INTO x SELECT * FROM y")


@dataclass
class Column:
    name: str
    type: str
    comment: str = ""


@pytest.mark.asyncio
async def test_reverse_model_reads_real_schema_mock():
    service = AgentWorkflowService()
    app_state._maxcompute_client = SimpleNamespace(
        get_table_schema=AsyncMock(
            return_value=SimpleNamespace(
                columns=[Column("id", "bigint")],
                partition_keys=[Column("dt", "string")],
            )
        )
    )
    app_state._bff_client = None

    result = await service.execute(
        message="reverse ods_shop_order",
        action="reverse_modeling",
        params={"table_name": "ods_shop_order"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["columns"][0]["name"] == "id"
