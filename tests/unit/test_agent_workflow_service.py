import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from dataworks_agent.agent.workflow_service import AgentWorkflowService, WorkflowResult
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel, TaskStepLogModel
from dataworks_agent.governance.closed_loop_verifier import (
    VerificationResult,
    VerificationStatus,
)
from dataworks_agent.runtime.loop import RepairResult
from dataworks_agent.semantic.album_context import AlbumTable, DataAlbumContext
from dataworks_agent.semantic.query_planner import MetricQueryPlan
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
        "_cdp_client",
    ]
    before = {name: getattr(app_state, name, None) for name in names}
    cookie_health = app_state.cookie_health
    yield
    for name, value in before.items():
        setattr(app_state, name, value)
    app_state.cookie_health = cookie_health


def _effective_order_album_contexts() -> list[DataAlbumContext]:
    return [
        DataAlbumContext(
            album_id=888,
            name="订单",
            description="订单主题",
            categories=["订单"],
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dws_ord_order_si_crt_df",
                    comment="订单指标汇总表，保存订单相关高度汇总数据",
                    entity_guid="odps.giikin_aliyun.tb_dws_ord_order_si_crt_df",
                    qualified_name="maxcompute-table.giikin_aliyun.tb_dws_ord_order_si_crt_df",
                    relation_id=8836,
                ),
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dwd_ord_gk_order_info_crt_df",
                    comment="订单表-按照创建时间存储",
                    entity_guid="odps.giikin_aliyun.tb_dwd_ord_gk_order_info_crt_df",
                    qualified_name="maxcompute-table.giikin_aliyun.tb_dwd_ord_gk_order_info_crt_df",
                    relation_id=8837,
                ),
            ],
        )
    ]


def _wire_effective_order_semantics(service: AgentWorkflowService) -> None:
    service._album_context_resolver.resolve = AsyncMock(
        return_value=_effective_order_album_contexts()
    )
    service._validate_semantic_plan_metadata = AsyncMock(
        side_effect=lambda plan: plan.metadata_validation.update(
            {"status": "passed", "channel": "test", "required_fields": []}
        )
    )


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
    assert all(step["status"] in {"planned", "required_only_for_publish"} for step in result.steps)
    assert any(step["step"] == "create_ods_table_and_source_node" for step in result.steps)
    assert not {
        "credential_and_cookie_health",
        "official_mcp_health",
    }.intersection(step["step"] for step in result.steps)


@pytest.mark.asyncio
async def test_dev_execute_builds_all_layers():
    service = AgentWorkflowService()
    app_state._maxcompute_client = object()
    app_state._node_client = object()
    service._official_datasource_preflight = AsyncMock(return_value={"status": "completed"})
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
    assert [item["layer"] for item in result.data["executed"]] == ["ODS", "DWD", "DIM", "DWS"]
    assert (
        next(step for step in result.steps if step["step"] == "create_ods_table_and_source_node")[
            "status"
        ]
        == "completed"
    )
    assert (
        next(step for step in result.steps if step["step"] == "publish_gate")["status"] == "skipped"
    )
    service._execute_ods.assert_awaited_once()
    assert service._deploy_warehouse_layer.await_count == 3


@pytest.mark.asyncio
async def test_publish_request_is_created_after_dev_execution():
    service = AgentWorkflowService()
    app_state._maxcompute_client = object()
    app_state._node_client = object()
    service._official_datasource_preflight = AsyncMock(return_value={"status": "completed"})
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
    assert result.data["publish_gate"] == "approval_required"
    assert (
        next(step for step in result.steps if step["step"] == "publish_gate")["status"]
        == "approval_required"
    )
    gate.interrupt_for_approval.assert_awaited_once()


def test_readonly_guard_rejects_write_sql():
    service = AgentWorkflowService()
    with pytest.raises(ValueError):
        service._validate_readonly_sql("INSERT INTO x SELECT * FROM y")


def test_query_limit_is_added_and_clamped():
    service = AgentWorkflowService()
    assert "LIMIT 100" in service._enforce_query_limit("SELECT * FROM sample")
    assert "LIMIT 100" in service._enforce_query_limit("SELECT * FROM sample LIMIT 10000")
    assert "LIMIT 5" in service._enforce_query_limit("SELECT * FROM sample LIMIT 5")


@pytest.mark.asyncio
async def test_ask_data_plan_never_submits_query():
    service = AgentWorkflowService()
    mc = SimpleNamespace(submit_query=AsyncMock(), wait_and_fetch=AsyncMock())
    app_state._maxcompute_client = mc

    result = await service.execute(
        message="查数 ods_shop_order 前几条",
        action="ask_data",
        params={},
        execution_mode="plan",
    )

    assert result.success is True
    assert result.data["query"]["executed"] is False
    assert "LIMIT 100" in result.data["query"]["sql"]
    mc.submit_query.assert_not_awaited()
    mc.wait_and_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_ask_data_dev_execute_runs_bounded_query():
    service = AgentWorkflowService()
    instance = object()
    mc = SimpleNamespace(
        submit_query=AsyncMock(return_value=instance),
        wait_and_fetch=AsyncMock(
            return_value=SimpleNamespace(columns=["id"], rows=[[index] for index in range(150)])
        ),
    )
    app_state._maxcompute_client = mc

    result = await service.execute(
        message="查数 ```sql\nSELECT * FROM sample LIMIT 10000\n```",
        action="ask_data",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["query"]["executed"] is True
    assert len(result.data["query"]["rows"]) == 100
    submitted_sql = mc.submit_query.await_args.args[0]
    assert "LIMIT 100" in submitted_sql
    mc.wait_and_fetch.assert_awaited_once_with(instance)


@pytest.mark.asyncio
async def test_ask_data_permission_denied_preserves_sql_artifact():
    service = AgentWorkflowService()
    app_state._bff_client = None
    app_state._maxcompute_client = SimpleNamespace(
        submit_query=AsyncMock(
            side_effect=RuntimeError("NoPermission: no privilege odps:CreateInstance")
        ),
        wait_and_fetch=AsyncMock(),
    )

    result = await service.execute(
        message="查数 ods_shop_order 前几条",
        action="ask_data",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is False
    assert result.steps[-1]["status"] == "blocked"
    assert result.data["query"]["executed"] is False
    assert result.artifacts[0]["type"] == "query_sql"
    assert "odps:CreateInstance" in result.errors[0]
    app_state._maxcompute_client.wait_and_fetch.assert_not_awaited()


def test_declarative_business_question_routes_to_ask_data():
    service = AgentWorkflowService()
    assert (
        service._route_action(
            "\u4eca\u5929\u5404\u5bb6\u65cf\u7684\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11",
            "unknown",
        )
        == "ask_data"
    )


@pytest.mark.asyncio
async def test_declarative_business_question_uses_album_semantic_plan():
    service = AgentWorkflowService()
    _wire_effective_order_semantics(service)
    sql = await service._build_readonly_sql(
        "\u4eca\u5929\u5404\u5bb6\u65cf\u7684\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11"
    )
    assert "giikin_aliyun.tb_dws_ord_order_si_crt_df" in sql


@pytest.mark.asyncio
async def test_business_query_album_semantics_uses_certified_effective_order_table():
    service = AgentWorkflowService()
    _wire_effective_order_semantics(service)
    sql = await service._build_readonly_sql("查一下今天各家族的有效订单数")

    assert "giikin_aliyun.tb_dws_ord_order_si_crt_df" in sql
    assert "family_name" in sql
    assert "SUM(effect_order_cnt) AS effective_order_cnt" in sql
    assert "GROUP BY pt, family_name" in sql


@pytest.mark.asyncio
async def test_ask_data_falls_back_to_cookie_bff_when_ak_sk_cannot_query():
    service = AgentWorkflowService()
    _wire_effective_order_semantics(service)
    app_state._maxcompute_client = SimpleNamespace(
        submit_query=AsyncMock(side_effect=RuntimeError("NoPermission: odps:CreateInstance")),
        wait_and_fetch=AsyncMock(),
    )
    app_state._bff_client = SimpleNamespace(
        execute_sql=AsyncMock(side_effect=["job-main", "job-reconcile"]),
        wait_job=AsyncMock(return_value=True),
        get_query_result=AsyncMock(
            side_effect=[
                {
                    "headerList": [
                        {"name": "data_date"},
                        {"name": "family_name"},
                        {"name": "effective_order_cnt"},
                    ],
                    "bodyList": [["20260712", "吉喵云", "6560"]],
                },
                {
                    "headerList": [
                        {"name": "data_date"},
                        {"name": "family_name"},
                        {"name": "effective_order_cnt"},
                    ],
                    "bodyList": [["20260712", "吉喵云", "6560"]],
                },
            ]
        ),
        last_error=None,
    )

    result = await service.execute(
        message="查一下今天各家族的有效订单数",
        action="ask_data",
        params={},
        execution_mode="auto",
    )

    assert result.success is True
    assert result.mode == "dev_execute"
    assert result.data["query"]["executed"] is True
    assert result.data["query"]["execution_channel"] == "cookie_bff"
    assert result.data["verification"]["status"] == "passed"
    assert result.steps[-1]["step"] == "closed_loop_verification"
    assert result.data["query"]["rows"] == [["20260712", "吉喵云", "6560"]]
    assert result.data["reconciliation"]["passed"] is True
    assert app_state._bff_client.execute_sql.await_count == 2
    assert app_state._bff_client.wait_job.await_count == 2
    assert app_state._bff_client.get_query_result.await_count == 2


@pytest.mark.asyncio
async def test_explicit_plan_business_query_never_executes_any_channel():
    service = AgentWorkflowService()
    app_state._maxcompute_client = SimpleNamespace(
        submit_query=AsyncMock(), wait_and_fetch=AsyncMock()
    )
    app_state._bff_client = SimpleNamespace(execute_sql=AsyncMock())

    result = await service.execute(
        message="查一下今天各家族的有效订单数",
        action="ask_data",
        params={},
        execution_mode="plan",
    )

    assert result.success is True
    assert result.mode == "plan"
    assert result.data["query"]["executed"] is False
    app_state._maxcompute_client.submit_query.assert_not_awaited()
    app_state._bff_client.execute_sql.assert_not_awaited()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message_part"),
    [
        ("NoSuchObject: table not found", "未找到表"),
        ("NoPermission: no privilege odps:Describe", "无权读取"),
    ],
)
async def test_reverse_model_returns_structured_blocked_result(error, message_part):
    service = AgentWorkflowService()
    app_state._maxcompute_client = SimpleNamespace(
        get_table_schema=AsyncMock(side_effect=RuntimeError(error))
    )

    result = await service.execute(
        message="逆向分析 ods_missing",
        action="reverse_modeling",
        params={"table_name": "ods_missing"},
        execution_mode="plan",
    )

    assert result.success is False
    assert result.steps == [{"step": "read_maxcompute_schema", "status": "blocked"}]
    assert message_part in result.message
    assert result.data["clarifying_questions"]
    assert result.data["next_actions"]


@pytest.mark.asyncio
async def test_reverse_node_prefers_official_mcp(monkeypatch):
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.settings.dataworks_project_id", 123)
    service = AgentWorkflowService()
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "GetNode":
            return {
                "Node": {
                    "Id": "node-1",
                    "Spec": '{"spec":{"nodes":[{"script":{"content":"SELECT * FROM ods_a"}}]}}',
                }
            }
        return {"PagingInfo": {"Nodes": [{"Id": "parent-1"}]}}

    app_state._official_mcp_client = SimpleNamespace(
        call_tool=call_tool,
        status=SimpleNamespace(to_dict=lambda: {"enabled": True, "connected": True}),
    )
    app_state._openapi_client = None

    result = await service.execute(
        message="逆向分析节点 node-1",
        action="reverse_modeling",
        params={"node_id": "node-1"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["metadata_sources"]["official_mcp"] == "completed"
    assert result.data["dependencies"][0]["Id"] == "parent-1"
    assert [name for name, _ in calls] == ["GetNode", "ListNodeDependencies"]


@pytest.mark.asyncio
async def test_reverse_node_falls_back_to_openapi():
    service = AgentWorkflowService()
    app_state._official_mcp_client = SimpleNamespace(
        call_tool=AsyncMock(side_effect=RuntimeError("mcp unavailable")),
        status=SimpleNamespace(to_dict=lambda: {"enabled": True, "connected": False}),
    )
    app_state._openapi_client = SimpleNamespace(
        get_node=AsyncMock(
            return_value={
                "Node": {
                    "Id": "node-2",
                    "Spec": '{"spec":{"nodes":[{"script":{"content":"SELECT 1"}}]}}',
                }
            }
        ),
        list_node_dependencies=AsyncMock(
            return_value={"PagingInfo": {"Nodes": [{"Id": "parent-2"}]}}
        ),
    )

    result = await service.execute(
        message="逆向分析节点 node-2",
        action="reverse_modeling",
        params={"node_id": "node-2"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["metadata_sources"]["openapi"] == "fallback"
    assert result.data["dependencies"][0]["Id"] == "parent-2"


@pytest.mark.asyncio
async def test_diagnose_failed_task_returns_successful_proposal():
    service = AgentWorkflowService()
    task_id = f"diag_{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        db.add(
            ModelingTaskModel(
                task_id=task_id,
                status="failed",
                source_table="ods_shop_order",
                target_table="dwd_shop_order",
                error_message="upstream timeout",
            )
        )
        db.add(
            TaskStepLogModel(
                task_id=task_id,
                step_name="deploy_node",
                status="failed",
                error="node deploy failed",
            )
        )
        db.commit()
    try:
        result = await service.execute(
            message=f"排查任务 {task_id} 的失败原因",
            action="diagnose_issue",
            params={"task_id": task_id},
            execution_mode="dev_execute",
        )
    finally:
        with SessionLocal() as db:
            db.query(TaskStepLogModel).filter(TaskStepLogModel.task_id == task_id).delete()
            db.query(ModelingTaskModel).filter(ModelingTaskModel.task_id == task_id).delete()
            db.commit()

    assert result.success is True
    assert result.data["diagnosed_task_status"] == "failed"
    assert result.data["health_degraded"] is True
    assert result.data["recovery_proposal"]["action"] == "retry"
    assert "node deploy failed" in result.errors


@pytest.mark.asyncio
async def test_diagnose_instance_reads_official_mcp_evidence():
    service = AgentWorkflowService()

    async def call_tool(name, arguments):
        if name == "GetTaskInstance":
            return {"TaskInstance": {"Id": arguments["Id"], "Status": "Failed"}}
        if name == "GetTaskInstanceLog":
            return {"Log": "ODPS-0130071"}
        raise AssertionError(name)

    app_state._official_mcp_client = SimpleNamespace(
        call_tool=call_tool,
        status=SimpleNamespace(to_dict=lambda: {"enabled": True, "connected": True}),
    )
    result = await service.execute(
        message="排查 DataWorks 实例 12345 的失败原因",
        action="diagnose_issue",
        params={"instance_id": "12345"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["evidence_sources"]["official_mcp_instance"] == "completed"
    assert result.data["diagnosed_task_status"] == "Failed"
    assert result.data["task_instance_log"]["Log"] == "ODPS-0130071"


@pytest.mark.asyncio
async def test_official_datasource_preflight_calls_list_datasources(monkeypatch):
    service = AgentWorkflowService()
    call = AsyncMock(return_value=({"DataSources": []}, None))
    service._official_call = call
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.settings.dataworks_project_id", 123)

    result = await service._official_datasource_preflight("shop")

    assert result["status"] == "completed"
    call.assert_awaited_once_with(
        "ListDataSources",
        {"ProjectId": 123, "Name": "shop", "EnvType": "Dev", "PageSize": 10, "PageNumber": 1},
    )


@pytest.mark.asyncio
async def test_execute_ods_routes_di(monkeypatch):
    from dataworks_agent.services.ods_di.pipeline import DIPipeline

    service = AgentWorkflowService()
    app_state._bff_client = object()
    app_state._node_client = object()
    app_state._maxcompute_client = object()
    run = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(DIPipeline, "run", run)

    result = await service._execute_ods(
        message="",
        params={},
        source_type="postgres",
        datasource="shop",
        source_table="orders",
        target_table="ods_shop_order",
        granularity="hour",
        schedule_minute=3,
        initialize=True,
    )

    assert result["success"] is True
    assert run.await_args.kwargs["source_type"] == "postgres"
    assert run.await_args.kwargs["with_initialization"] is True


@pytest.mark.asyncio
async def test_execute_ods_routes_hologres(monkeypatch):
    from dataworks_agent.services.ods_holo import HoloOdsPipeline

    service = AgentWorkflowService()
    app_state._bff_client = object()
    app_state._node_client = object()
    app_state._maxcompute_client = object()
    run = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(HoloOdsPipeline, "run", run)

    result = await service._execute_ods(
        message="",
        params={"script_path": "业务流程/100_订单信息/Hologres/数据开发/00_ODS"},
        source_type="hologres",
        datasource="public",
        source_table="orders",
        target_table="ods_shop_order",
        granularity="hour",
        schedule_minute=1,
        initialize=False,
    )

    assert result["success"] is True
    assert run.await_args.kwargs["holo_schema"] == "public"
    assert run.await_args.kwargs["target_table"] == "ods_shop_order"


@pytest.mark.asyncio
async def test_execute_ods_routes_oss_without_publish(monkeypatch):
    from dataworks_agent.services.ods_oss import OssImportPipeline

    service = AgentWorkflowService()
    app_state._node_client = object()
    app_state._maxcompute_client = object()
    service._ensure_oss_table = AsyncMock(
        return_value={"status": "created", "ddl": "CREATE TABLE x"}
    )
    run = AsyncMock(return_value={"success": True, "steps": {}})
    monkeypatch.setattr(OssImportPipeline, "run", run)

    result = await service._execute_ods(
        message="字段 id bigint",
        params={"oss_path": "oss://bucket/orders.csv"},
        source_type="oss",
        datasource=None,
        source_table="",
        target_table="ods_shop_order",
        granularity="day",
        schedule_minute=1,
        initialize=False,
    )

    assert result["success"] is True
    assert run.await_args.kwargs["publish"] is False
    assert run.await_args.kwargs["target_table"] == "ods_shop_order"
    assert result["steps"]["ensure_table"]["ddl"] == "CREATE TABLE x"


@pytest.mark.asyncio
async def test_ensure_oss_table_places_comment_before_partitions():
    service = AgentWorkflowService()
    mc = SimpleNamespace(
        table_exists=AsyncMock(return_value=False),
        execute_ddl=AsyncMock(return_value=SimpleNamespace(success=True, error=None)),
    )
    app_state._maxcompute_client = mc

    result = await service._ensure_oss_table(
        "ods_oss_sample_day",
        "day",
        [{"name": "json_data", "type": "string"}],
        oss_path="oss://bucket/path/",
        file_format="json",
    )

    assert result["status"] == "created"
    ddl = mc.execute_ddl.await_args.args[0]
    assert ") COMMENT 'OSS Agent generated' PARTITIONED BY (`dt` STRING);" in ddl
    assert "PARTITIONED BY (`dt` STRING) COMMENT" not in ddl


@pytest.mark.asyncio
async def test_execute_ods_routes_realtime_without_publish(monkeypatch):
    from dataworks_agent.services.ods_realtime import RealtimeSyncPipeline

    service = AgentWorkflowService()
    app_state._node_client = object()
    app_state._maxcompute_client = object()
    service._ensure_table_from_source = AsyncMock(
        return_value={
            "status": "created",
            "ddl": "CREATE TABLE x",
            "columns": [Column("id", "bigint")],
        }
    )
    run = AsyncMock(return_value={"success": True, "steps": {}})
    monkeypatch.setattr(RealtimeSyncPipeline, "run", run)

    result = await service._execute_ods(
        message="",
        params={},
        source_type="realtime",
        datasource="shop",
        source_table="orders",
        target_table="ods_shop_order",
        granularity="hour",
        schedule_minute=2,
        initialize=False,
    )

    assert result["success"] is True
    service._ensure_table_from_source.assert_awaited_once_with(
        "shop__orders_delta", "ods_shop_order", "hour"
    )
    assert run.await_args.kwargs["publish"] is False
    assert run.await_args.kwargs["target_table"] == "ods_shop_order"
    assert run.await_args.kwargs["sync_rows"] == [{"dst_table": "shop__orders_delta"}]
    assert "FROM shop__orders_delta" in run.await_args.kwargs["select_dml"]


def test_execution_artifacts_include_nested_ods_ddl():
    artifacts = AgentWorkflowService._execution_artifacts(
        [
            {
                "layer": "ODS",
                "table": "ods_shop_order",
                "result": {"sql": "INSERT", "steps": {"ensure_table": {"ddl": "CREATE TABLE"}}},
            }
        ]
    )
    assert {item["type"] for item in artifacts} == {"sql", "ddl"}


def test_capability_status_includes_cookie_health():
    app_state.cookie_health = "healthy"
    assert AgentWorkflowService().capability_status()["cookie_health"] == "healthy"


def test_capability_status_reports_partial_cookie_degradation():
    app_state.cookie_health = "expired"
    app_state._bff_client = object()
    app_state._cdp_client = object()

    status = AgentWorkflowService().capability_status()

    assert status["cookie_health"] == "degraded"
    assert status["cookie_mcp_health"] == "expired"


@pytest.mark.asyncio
async def test_cookie_plan_returns_channel_steps():
    service = AgentWorkflowService()
    app_state.cookie_health = "expired"
    app_state._bff_client = object()
    app_state._cdp_client = object()

    result = await service.execute(
        message="检查 Cookie 状态",
        action="cookie_manage",
        params={},
        execution_mode="plan",
    )

    assert result.success is True
    assert {step["step"] for step in result.steps} == {
        "check_ak_sk",
        "check_official_mcp",
        "check_cookie_bff",
        "check_cdp_9222",
    }
    assert "部分降级" in result.message


@pytest.mark.asyncio
async def test_effective_order_plan_requires_data_album_membership():
    service = AgentWorkflowService()
    _wire_effective_order_semantics(service)

    plan = await service._build_query_plan(
        "\u67e5\u4e00\u4e0b\u4eca\u5929\u5404\u5bb6\u65cf\u7684\u6709\u6548\u8ba2\u5355\u6570"
    )

    assert plan.table == "giikin_aliyun.tb_dws_ord_order_si_crt_df"
    assert plan.albums[0]["name"] == "订单"
    assert plan.selected_dimensions == ["家族"]
    service._album_context_resolver.resolve.assert_awaited_once()
    service._validate_semantic_plan_metadata.assert_awaited_once_with(plan)


@pytest.mark.asyncio
async def test_complex_question_injects_data_album_metadata_into_llm_prompt(monkeypatch):
    from dataworks_agent.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    service = AgentWorkflowService()
    service._album_context_resolver.resolve = AsyncMock(
        return_value=[
            DataAlbumContext(
                album_id=888,
                name="\u8ba2\u5355",
                description="\u8ba2\u5355\u4e3b\u9898",
                categories=["\u8ba2\u5355\u4fe1\u606f"],
                tables=[
                    AlbumTable(
                        project="giikin_aliyun",
                        name="tb_dws_ord_order_si_crt_df",
                        comment="\u8ba2\u5355\u6307\u6807\u6c47\u603b\u8868",
                        remark="\u6309\u8ba2\u5355\u65e5\u671f\u5206\u533a",
                    )
                ],
            )
        ]
    )
    llm = SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content="SELECT 1 AS order_cnt"))
    )

    with patch("dataworks_agent.llm.service.LLMService.from_settings", return_value=llm):
        sql = await service._build_readonly_sql("\u8ba2\u5355\u8f6c\u5316\u8d8b\u52bf\u5982\u4f55")

    assert sql == "SELECT 1 AS order_cnt"
    context = llm.complete.await_args.args[0]
    metadata = "\n".join(part.content for part in context.parts if part.kind == "metadata")
    assert "Album: \u8ba2\u5355" in metadata
    assert "giikin_aliyun.tb_dws_ord_order_si_crt_df" in metadata
    assert "never infer metric formulas" in metadata


@pytest.mark.asyncio
async def test_complex_question_keeps_original_llm_path_when_album_context_is_empty(monkeypatch):
    from dataworks_agent.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    service = AgentWorkflowService()
    service._album_context_resolver.resolve = AsyncMock(return_value=[])
    llm = SimpleNamespace(complete=AsyncMock(return_value=SimpleNamespace(content="SELECT 1")))

    with patch("dataworks_agent.llm.service.LLMService.from_settings", return_value=llm):
        sql = await service._build_readonly_sql("\u672a\u77e5\u4e1a\u52a1\u95ee\u9898")

    assert sql == "SELECT 1"
    context = llm.complete.await_args.args[0]
    assert all(part.kind != "metadata" for part in context.parts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "今天的总有效订单是多少",
        "查一下今日总有效订单数",
        "今天有效订单有多少",
        "今日的有效订单是多少",
    ],
)
async def test_total_effective_order_phrasings_use_album_semantics_without_llm(question):
    service = AgentWorkflowService()
    _wire_effective_order_semantics(service)

    sql = await service._build_readonly_sql(question)

    assert "giikin_aliyun.tb_dws_ord_order_si_crt_df" in sql
    assert "SUM(effect_order_cnt) AS total_effective_order_cnt" in sql
    assert "pt AS data_date" in sql
    assert "GROUP BY pt" in sql
    assert "total_effective_order_cnt" in sql


@pytest.mark.asyncio
async def test_total_effective_order_query_prefers_cookie_before_maxcompute():
    service = AgentWorkflowService()
    _wire_effective_order_semantics(service)
    app_state._maxcompute_client = SimpleNamespace(
        submit_query=AsyncMock(side_effect=AssertionError("production query must prefer Cookie")),
        wait_and_fetch=AsyncMock(),
    )
    app_state._bff_client = SimpleNamespace(
        execute_sql=AsyncMock(side_effect=["job-total", "job-reconcile"]),
        wait_job=AsyncMock(return_value=True),
        get_query_result=AsyncMock(
            side_effect=[
                {
                    "headerList": [
                        {"name": "data_date"},
                        {"name": "total_effective_order_cnt"},
                    ],
                    "bodyList": [["20260712", "62782"]],
                },
                {
                    "headerList": [
                        {"name": "data_date"},
                        {"name": "total_effective_order_cnt"},
                    ],
                    "bodyList": [["20260712", "62782"]],
                },
            ]
        ),
        last_error=None,
    )

    result = await service.execute(
        message="今天的总有效订单是多少",
        action="ask_data",
        params={},
        execution_mode="auto",
    )

    assert result.success is True
    assert result.data["query"]["execution_channel"] == "cookie_bff"
    assert "62,782" in result.message
    assert result.data["reconciliation"]["passed"] is True
    assert "20260712" in result.message
    app_state._maxcompute_client.submit_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_cookie_auth_failure_refreshes_once_then_succeeds():
    service = AgentWorkflowService()
    bff = SimpleNamespace()
    query_once = AsyncMock(side_effect=[RuntimeError("CSRF token expired"), (["value"], [[1]])])
    service._run_cookie_bff_query_once = query_once
    refresh = AsyncMock(return_value={"status": "refreshed"})
    service._refresh_cookie_auth = refresh
    app_state._bff_client = bff

    columns, rows = await service._run_cookie_bff_query("SELECT 1")

    assert columns == ["value"]
    assert rows == [[1]]
    assert query_once.await_count == 2
    refresh.assert_awaited_once_with(bff)


@pytest.mark.asyncio
async def test_cookie_refresh_failure_does_not_retry_forever():
    service = AgentWorkflowService()
    bff = SimpleNamespace()
    query_once = AsyncMock(side_effect=RuntimeError("cookie expired"))
    service._run_cookie_bff_query_once = query_once
    service._refresh_cookie_auth = AsyncMock(
        return_value={"status": "failed", "detail": "Chrome 9222 unavailable"}
    )
    app_state._bff_client = bff

    with pytest.raises(RuntimeError, match="Chrome 9222 unavailable"):
        await service._run_cookie_bff_query("SELECT 1")

    assert query_once.await_count == 1
    service._refresh_cookie_auth.assert_awaited_once_with(bff)


@pytest.mark.asyncio
async def test_unknown_metric_without_llm_returns_clarification_not_failure(monkeypatch):
    service = AgentWorkflowService()
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.settings.llm_api_key", "")
    service._album_context_resolver.resolve = AsyncMock(
        return_value=[
            DataAlbumContext(
                album_id=8,
                name="订单",
                tables=[AlbumTable(project="giikin_aliyun", name="tb_dws_order_metric")],
            )
        ]
    )

    result = await service.execute(
        message="今天的净贡献订单是多少",
        action="ask_data",
        params={},
        execution_mode="auto",
    )

    assert result.success is True
    assert result.data["needs_clarification"] is True
    assert result.data["query"]["executed"] is False
    assert result.data["album_candidates"][0]["tables"][0]["table"] == (
        "giikin_aliyun.tb_dws_order_metric"
    )
    assert all(step["status"] != "failed" for step in result.steps)


@pytest.mark.asyncio
async def test_reverse_model_permission_denied_falls_back_to_cookie_ddl():
    service = AgentWorkflowService()
    app_state._maxcompute_client = SimpleNamespace(
        get_table_schema=AsyncMock(side_effect=RuntimeError("NoPermission: odps:Describe"))
    )
    app_state._bff_client = SimpleNamespace(
        get_creation_ddl=AsyncMock(
            return_value="""CREATE TABLE giikin_aliyun.tb_order (
  id BIGINT COMMENT '订单ID',
  amount DECIMAL(18,2)
)
PARTITIONED BY (pt STRING);"""
        ),
        list_lineage=AsyncMock(return_value={"nodes": []}),
    )

    result = await service.execute(
        message="逆向分析 giikin_aliyun.tb_order",
        action="reverse_modeling",
        params={"table_name": "giikin_aliyun.tb_order"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["metadata_channel"] == "cookie_bff"
    assert result.data["maxcompute_fallback_reason"] == "MaxCompute permission denied"
    assert result.errors == []
    assert result.data["columns"][0]["name"] == "id"
    app_state._bff_client.get_creation_ddl.assert_awaited_once_with("odps.giikin_aliyun.tb_order")


@pytest.mark.asyncio
async def test_reverse_model_without_maxcompute_uses_cookie_ddl():
    service = AgentWorkflowService()
    app_state._maxcompute_client = None
    app_state._bff_client = SimpleNamespace(
        get_creation_ddl=AsyncMock(return_value="CREATE TABLE giikin_dev.tb_order (id BIGINT);"),
        list_lineage=AsyncMock(return_value={"nodes": []}),
    )

    result = await service.execute(
        message="逆向分析 giikin_dev.tb_order",
        action="reverse_modeling",
        params={"table_name": "giikin_dev.tb_order"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["metadata_channel"] == "cookie_bff"


@pytest.mark.asyncio
async def test_diagnose_missing_task_is_warning_not_completed():
    service = AgentWorkflowService()
    task_id = f"missing_{uuid.uuid4().hex[:10]}"

    result = await service.execute(
        message=f"排查任务 {task_id}",
        action="diagnose_issue",
        params={"task_id": task_id},
        execution_mode="dev_execute",
    )

    log_step = next(step for step in result.steps if step["step"] == "task_and_step_logs")
    assert result.success is True
    assert result.data["task_found"] is False
    assert log_step["status"] == "warning"
    assert "不会伪装成定位成功" in result.message


@pytest.mark.asyncio
async def test_diagnose_without_target_is_explicit_health_check():
    service = AgentWorkflowService()

    result = await service.execute(
        message="检查执行底座",
        action="diagnose_issue",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert "执行底座健康检查" in result.message
    log_step = next(step for step in result.steps if step["step"] == "task_and_step_logs")
    assert log_step["status"] == "skipped"


@pytest.mark.asyncio
async def test_full_chain_without_target_names_generates_all_layers():
    service = AgentWorkflowService()

    result = await service.execute(
        message="把数据源 shop 的源表 orders 建成 ODS 到 DWD DIM DWS 全链路",
        action="forward_modeling",
        params={"source_table": "orders", "datasource_name": "shop"},
        execution_mode="plan",
    )

    generated = result.data["generated_tables"]
    assert result.success is True
    assert set(generated) == {"ods", "dwd", "dim", "dws"}
    assert generated["ods"].startswith("ods_")
    assert generated["dwd"].startswith("dwd_")
    assert generated["dim"].startswith("dim_")
    assert generated["dws"].startswith("dws_")
    assert any(step["step"] == "create_dws_tables_nodes_schedule" for step in result.steps)


@pytest.mark.asyncio
async def test_effective_order_query_is_blocked_when_album_does_not_contain_metric_asset():
    service = AgentWorkflowService()
    service._album_context_resolver.resolve = AsyncMock(
        return_value=[
            DataAlbumContext(
                album_id=888,
                name="订单",
                tables=[AlbumTable(project="giikin_aliyun", name="tb_dwd_other")],
            )
        ]
    )
    service._validate_semantic_plan_metadata = AsyncMock(
        side_effect=lambda plan: plan.metadata_validation.update(
            {"status": "passed", "channel": "test", "required_fields": []}
        )
    )
    app_state._bff_client = SimpleNamespace(execute_sql=AsyncMock())
    app_state._maxcompute_client = SimpleNamespace(submit_query=AsyncMock())

    result = await service.execute(
        message="今天的总有效订单是多少",
        action="ask_data",
        params={},
        execution_mode="auto",
    )

    assert result.success is True
    assert result.data["needs_clarification"] is True
    assert result.data["query"]["executed"] is False
    assert "未在声明的数据专辑资产中直接命中" in result.message
    service._validate_semantic_plan_metadata.assert_not_awaited()
    app_state._bff_client.execute_sql.assert_not_awaited()
    app_state._maxcompute_client.submit_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_loop_retries_transient_failure_until_verified():
    service = AgentWorkflowService()
    service._start_loop_event_log = lambda client_ip, workflow_type: (None, "")
    service._execute_once = AsyncMock(
        side_effect=[
            WorkflowResult(
                False,
                "query timed out",
                "ask_data",
                "dev_execute",
                errors=["gateway timeout"],
            ),
            WorkflowResult(
                True,
                "query verified",
                "ask_data",
                "dev_execute",
                data={
                    "query": {"executed": True, "rows": [[1]]},
                    "verification": {
                        "status": "passed",
                        "checks": [{"name": "execution", "passed": True}],
                    },
                },
            ),
        ]
    )
    service._repair_loop = AsyncMock(return_value=RepairResult(True, "retry_transient", "retry"))

    result = await service.execute(
        message="count orders today",
        action="ask_data",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["loop"]["iteration_count"] == 2
    assert result.data["loop"]["stop_reason"] == "verified_success"
    assert result.data["evaluation"]["verified_success"] is True
    assert service._execute_once.await_count == 2


@pytest.mark.asyncio
async def test_standard_oss_flow_stops_after_verified_publish_gate_boundary():
    service = AgentWorkflowService()
    service._start_loop_event_log = lambda client_ip, workflow_type: (None, "")
    standard_steps = [
        {"step": step, "status": "completed"}
        for step in (
            "inspect_oss_directory",
            "profile_json_sample",
            "dmr_pub_column_check",
            "create_dev_tables_cookie",
            "create_ods_sql_node_cookie",
            "configure_ods_schedule_cookie",
            "create_dwd_sql_node_cookie",
            "configure_dwd_schedule_cookie",
            "configure_ods_to_dwd_dependency_cookie",
        )
    ] + [
        {"step": "create_prod_tables", "status": "approval_required"},
        {"step": "publish_gate", "status": "skipped"},
    ]
    service._execute_once = AsyncMock(
        return_value=WorkflowResult(
            True,
            "standard OSS flow completed",
            "forward_modeling",
            "dev_execute",
            steps=standard_steps,
            data={
                "standard": "tiktok_smart_plus_material_report",
                "dev_tables": {
                    "ods": "giikin_develop.ods_report",
                    "dwd": "giikin_develop.dwd_report",
                },
                "prod_tables": {
                    "ods": {"status": "approval_required"},
                    "dwd": {"status": "approval_required"},
                },
                "ods_pipeline": {"success": True},
                "dwd_pipeline": {"success": True},
                "publish_gate": "not_requested",
            },
        )
    )

    result = await service.execute(
        message="???? TikTok Smart Plus material report OSS",
        action="forward_modeling",
        params={"source_type": "oss"},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["loop"]["stop_reason"] == "verified_success"
    assert result.data["loop"]["iteration_count"] == 1
    assert result.data["evaluation"]["verified_success"] is True
    service._execute_once.assert_awaited_once()



@pytest.mark.asyncio
async def test_loop_prevents_raw_success_without_outcome_evidence():
    service = AgentWorkflowService()
    service._start_loop_event_log = lambda client_ip, workflow_type: (None, "")
    service._execute_once = AsyncMock(
        return_value=WorkflowResult(
            True,
            "query returned",
            "ask_data",
            "dev_execute",
            data={"query": {"executed": True, "rows": [[1]]}},
        )
    )

    result = await service.execute(
        message="count orders today",
        action="ask_data",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is False
    assert result.data["evaluation"]["verified_success"] is False
    assert result.data["evaluation"]["false_success_prevented"] is True
    assert result.data["loop"]["stop_reason"] == "non_retryable"
    assert "Loop" in result.errors[-1]


@pytest.mark.asyncio
async def test_draft_business_metric_returns_precise_knowledge_clarification(monkeypatch):
    service = AgentWorkflowService()
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.settings.llm_api_key", "")
    service._album_context_resolver.resolve = AsyncMock(
        return_value=[
            DataAlbumContext(
                album_id=330,
                name="物流成本",
                tables=[
                    AlbumTable(
                        project="giikin_aliyun",
                        name="tb_dwd_fin_order_logistics_cost_df",
                        comment="订单物流成本表",
                    )
                ],
            )
        ]
    )

    result = await service.execute(
        message="今天物流成本多少？",
        action="ask_data",
        params={},
        execution_mode="auto",
    )

    assert result.success is True
    assert result.data["needs_clarification"] is True
    assert result.data["query"]["executed"] is False
    assert result.data["knowledge_matches"][0]["id"] == "logistics_cost_amt"
    assert result.data["knowledge_matches"][0]["album_evidence"][0]["album_id"] == 330
    assert "模型计算" in result.data["clarifying_questions"][0]
    assert "LLM_API_KEY" not in result.message
    assert "目标表" not in result.message
    assert result.data["loop"]["stop_reason"] != "verified_success"


@pytest.mark.asyncio
async def test_generic_cost_question_returns_three_business_metric_choices(monkeypatch):
    service = AgentWorkflowService()
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.settings.llm_api_key", "")
    service._album_context_resolver.resolve = AsyncMock(return_value=[])

    result = await service.execute(
        message="今天花费多少？",
        action="ask_data",
        params={},
        execution_mode="auto",
    )

    assert [item["id"] for item in result.data["knowledge_matches"]] == [
        "ad_spend_amt",
        "logistics_cost_amt",
        "purchase_cost_amt",
    ]
    assert result.data["query"]["executed"] is False
    assert "多个待确认的经营指标" in result.message


def _ask_data_mismatch_result() -> WorkflowResult:
    return WorkflowResult(
        False,
        "query executed but reconciliation mismatched",
        "ask_data",
        "dev_execute",
        data={
            "query": {"executed": True, "rows": [[232]]},
            "reconciliation": {"status": "mismatch", "passed": False},
            "verification": {
                "status": "failed",
                "checks": [
                    {"name": "metadata_contract", "passed": True},
                    {"name": "result_reconciliation", "passed": False},
                ],
            },
        },
    )


@pytest.mark.asyncio
async def test_loop_waits_for_freshness_lag_then_requeries_until_verified(monkeypatch):
    service = AgentWorkflowService()
    service._start_loop_event_log = lambda client_ip, workflow_type: (None, "")
    service._execute_once = AsyncMock(
        side_effect=[
            _ask_data_mismatch_result(),
            WorkflowResult(
                True,
                "query verified",
                "ask_data",
                "dev_execute",
                data={
                    "query": {"executed": True, "rows": [[485]]},
                    "reconciliation": {"status": "passed", "passed": True},
                    "verification": {
                        "status": "passed",
                        "checks": [
                            {"name": "metadata_contract", "passed": True},
                            {"name": "result_reconciliation", "passed": True},
                        ],
                    },
                },
            ),
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.asyncio.sleep", sleep)

    result = await service.execute(
        message="today effective orders for Golden Lion family",
        action="ask_data",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is True
    assert result.data["loop"]["iteration_count"] == 2
    assert result.data["loop"]["stop_reason"] == "verified_success"
    assert result.data["loop"]["iterations"][0]["repair"]["action"] == "wait_for_metric_refresh"
    assert service._execute_once.await_count == 2
    sleep.assert_awaited_once_with(2.0)


@pytest.mark.asyncio
async def test_loop_bounds_persistent_freshness_mismatch_without_false_success(monkeypatch):
    service = AgentWorkflowService()
    service._start_loop_event_log = lambda client_ip, workflow_type: (None, "")
    service._execute_once = AsyncMock(side_effect=lambda **kwargs: _ask_data_mismatch_result())
    sleep = AsyncMock()
    monkeypatch.setattr("dataworks_agent.agent.workflow_service.asyncio.sleep", sleep)

    result = await service.execute(
        message="today effective orders for Golden Lion family",
        action="ask_data",
        params={},
        execution_mode="dev_execute",
    )

    assert result.success is False
    assert result.data["loop"]["iteration_count"] == 3
    assert result.data["loop"]["stop_reason"] == "repeated_action"
    assert result.data["evaluation"]["verified_success"] is False
    assert result.data["evaluation"]["false_success_prevented"] is False
    assert service._execute_once.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [2.0, 4.0]


@pytest.mark.asyncio
async def test_query_success_allows_multirow_certified_trend():
    service = AgentWorkflowService()
    plan = MetricQueryPlan(
        sql="SELECT spend_date AS data_date, SUM(ad_spend) AS total_ad_spend_amt",
        metric_id="ad_spend_amt",
        metric_name="ad spend",
        metric_version=1,
        table="giikin_aliyun.tb_dwd_fin_ad_spend_di",
        selected_dimensions=[],
        caliber={
            "measure": {
                "column": "ad_spend",
                "alias": "ad_spend_amt",
                "aggregation": "sum",
                "unit": "CNY",
            }
        },
        business_query={
            "query_type": "trend",
            "time_range": {
                "kind": "range",
                "start": "2026-07-11",
                "end": "2026-07-13",
            },
        },
    )
    service._reconcile_metric_result = AsyncMock(
        return_value={"required": True, "passed": True, "status": "passed"}
    )
    service._closed_loop_verifier.verify = AsyncMock(
        return_value=VerificationResult(
            task_id="trend-check",
            task_type="ASK_DATA",
            status=VerificationStatus.PASSED,
            passed_count=8,
        )
    )

    result = await service._query_success(
        plan,
        [],
        ["data_date", "total_ad_spend_amt"],
        [["2026-07-11", 100], ["2026-07-12", 200], ["2026-07-13", 300]],
        "cookie_bff",
    )

    assert result.success is True
    assert result.data["query"]["row_count"] == 3
    assert "metric result is not unique" not in result.errors
    assert "2026-07-11" in result.message
    assert result.steps[-1]["step"] == "closed_loop_verification"


@pytest.mark.asyncio
async def test_oss_modeling_auto_mode_requests_real_source_context() -> None:
    service = AgentWorkflowService()

    result = await service.execute(
        message="oss 数据源 sample_material_report 建模处理",
        action="agent_workflow",
        params={
            "source_type": "oss",
            "datasource_name": "sample_material_report",
        },
        execution_mode="auto",
    )

    assert result.success is True
    assert result.mode == "dev_execute"
    assert result.data["needs_clarification"] is True
    assert result.data["missing_context"] == ["oss_path"]
    assert "oss://" in result.data["clarifying_questions"][0]
    assert result.steps == [
        {
            "step": "confirm_oss_path_format_and_schema",
            "status": "needs_context",
            "phase": "understand",
        }
    ]


@pytest.mark.asyncio
async def test_oss_modeling_auto_mode_executes_full_dev_chain_when_context_is_complete() -> None:
    service = AgentWorkflowService()
    app_state._maxcompute_client = object()
    app_state._node_client = object()
    service._official_datasource_preflight = AsyncMock(return_value={"status": "completed"})
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
        message=(
            "oss 数据源 sample_material_report 建模处理 "
            "oss://bucket/tiktok/material.csv，CSV，"
            "字段 material_id bigint, spend decimal(18,2)"
        ),
        action="agent_workflow",
        params={
            "source_type": "oss",
            "datasource_name": "sample_material_report",
            "oss_path": "oss://bucket/tiktok/material.csv",
            "columns": [
                {"name": "material_id", "type": "bigint"},
                {"name": "spend", "type": "decimal(18,2)"},
            ],
        },
        execution_mode="auto",
    )

    assert result.success is True
    assert result.mode == "dev_execute"
    assert set(result.data["generated_tables"]) == {"ods", "dwd", "dim", "dws"}
    assert [item["layer"] for item in result.data["executed"]] == ["ODS", "DWD", "DIM", "DWS"]
    service._execute_ods.assert_awaited_once()
    assert service._deploy_warehouse_layer.await_count == 3


@pytest.mark.asyncio
async def test_oss_schema_discovery_blocker_is_context_not_execution_failure() -> None:
    service = AgentWorkflowService()
    app_state._maxcompute_client = object()
    app_state._node_client = object()
    service._official_datasource_preflight = AsyncMock(return_value={"status": "completed"})
    service._execute_ods = AsyncMock(
        return_value={
            "success": False,
            "needs_context": True,
            "message": "OSS 源已识别，但字段探测需要补充上下文。",
            "clarifying_question": "请授予 OSS 最小读权限后继续。",
            "missing_context": ["oss_read_permission_or_columns"],
            "schema_discovery": {
                "success": False,
                "location": {
                    "endpoint": "oss-cn-shenzhen-internal.aliyuncs.com",
                    "bucket": "example-data-bucket",
                    "object_key": "ads/data/sample_material_report",
                },
                "file_format": "json",
                "error_code": "accessdenied",
                "error": "AccessDenied",
                "next_action": "授予 ListObjects/GetObject 最小读权限",
            },
        }
    )

    result = await service.execute(
        message=(
            "oss 数据源 sample_material_report 建模处理 "
            "oss://oss-cn-shenzhen-internal.aliyuncs.com/example-data-bucket/"
            "ads/data/sample_material_report/ 字段是 json"
        ),
        action="agent_workflow",
        params={
            "source_type": "oss",
            "datasource_name": "sample_material_report",
            "oss_path": (
                "oss://oss-cn-shenzhen-internal.aliyuncs.com/example-data-bucket/"
                "ads/data/sample_material_report/"
            ),
            "file_format": "json",
        },
        execution_mode="auto",
    )

    assert result.success is True
    assert result.data["needs_clarification"] is True
    assert result.data["executed"] == []
    assert result.data["attempted"] == [
        {"layer": "ODS", "table": "ods_oss_sample_material_report_day"}
    ]
    assert result.data["source_discovery"]["error_code"] == "accessdenied"
    assert all("non_retryable" not in error for error in result.errors)
    assert (
        next(step for step in result.steps if step["step"] == "discover_source_schema")["status"]
        == "needs_context"
    )
    assert (
        next(step for step in result.steps if step["step"] == "create_ods_table_and_source_node")[
            "status"
        ]
        == "skipped"
    )


@pytest.mark.asyncio
async def test_oss_explicit_columns_without_format_has_no_write_side_effect() -> None:
    service = AgentWorkflowService()
    service._ensure_oss_table = AsyncMock()

    result = await service._execute_ods(
        message="oss://bucket/path/ 字段 id bigint",
        params={
            "oss_path": "oss://bucket/path/",
            "columns": [{"name": "id", "type": "bigint"}],
        },
        source_type="oss",
        datasource="sample",
        source_table="sample",
        target_table="ods_oss_sample_day",
        granularity="day",
        schedule_minute=0,
        initialize=False,
    )

    assert result["success"] is False
    assert result["needs_context"] is True
    assert result["missing_context"] == ["file_format"]
    assert result["schema_discovery"]["error_code"] == "format_required"
    service._ensure_oss_table.assert_not_awaited()
