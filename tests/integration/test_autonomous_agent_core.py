"""Autonomous Agent 核心框架集成测试。

使用 MagicMock 模拟 app_state 上的真实客户端，覆盖：
- ODS/DWD 任务规划
- 安全守卫拦截规则
- Executor 真实步骤执行（mock MaxCompute / OpenAPI）
- Verifier 真实验证（mock MaxCompute / OpenAPI）
- AutonomousAgent 主流程
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dataworks_agent.agent.autonomous.agent import AutonomousAgent
from dataworks_agent.agent.autonomous.security_guard import SecurityViolationError
from dataworks_agent.agent.autonomous.state import (
    AutonomousContext,
    AutonomousTask,
    ExecutionStatus,
    TaskType,
)


def _make_context(
    business_folder: str = "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS",
    allowed_data_sources: list[str] | None = None,
) -> AutonomousContext:
    return AutonomousContext(
        project_id="12345",
        business_folder=business_folder,
        allowed_data_sources=allowed_data_sources or ["odps", "mysql", "hologres"],
        user_id="test_user",
        session_id="test_session",
    )


def _mock_maxcompute_client() -> MagicMock:
    mc = MagicMock()
    mc.table_exists = AsyncMock(return_value=True)
    mc.execute_ddl = AsyncMock(return_value=MagicMock(success=True, instance_id="inst_001", error=None))
    return mc


def _mock_node_client() -> MagicMock:
    nc = MagicMock()
    nc.get_node_uuid_by_path = AsyncMock(return_value=None)
    nc.check_existing_directory = AsyncMock(return_value={"path": "业务流程/106_广告报告", "uuid": "dir_001"})
    nc.create_node = AsyncMock(return_value="node_uuid_001")
    nc.update_vertex = AsyncMock(return_value=True)
    nc.update_node = AsyncMock(return_value=True)
    nc._load_spec = AsyncMock(return_value={
        "spec": {
            "nodes": [{"trigger": {"cron": "0 2 * * *"}, "strategy": {"instanceMode": "Immediately"}}],
            "flow": [{"depends": [{"type": "Normal", "output": "dataworks.ods_test"}]}],
        }
    })
    nc._save_spec = AsyncMock(return_value=True)
    return nc


def _mock_openapi_client() -> MagicMock:
    client = MagicMock()
    client.get_node = AsyncMock(return_value={"Node": {"Id": "999", "Name": "test_table"}})
    client.list_nodes = AsyncMock(return_value={"PagingInfo": {"Nodes": []}})
    client.list_node_dependencies = AsyncMock(return_value={"PagingInfo": {"Nodes": []}})
    return client


def _mock_modeling_engine() -> MagicMock:
    engine = MagicMock()
    engine.create_task = AsyncMock(return_value="task_mock_001")
    return engine


@pytest.fixture(autouse=True)
def mock_app_state():
    """Mock app_state 上的所有真实客户端。"""
    mc = _mock_maxcompute_client()
    nc = _mock_node_client()
    oc = _mock_openapi_client()

    with patch("dataworks_agent.agent.autonomous.executor._get_maxcompute_client", return_value=mc), \
         patch("dataworks_agent.agent.autonomous.executor._get_node_client", return_value=nc), \
         patch("dataworks_agent.agent.autonomous.executor._get_openapi_client", return_value=oc), \
         patch("dataworks_agent.agent.autonomous.verifier._get_maxcompute_client", return_value=mc), \
         patch("dataworks_agent.agent.autonomous.verifier._get_node_client", return_value=nc):
        yield {"mc": mc, "nc": nc, "oc": oc}


# ── Planner 测试 ──


@pytest.mark.asyncio
async def test_planner_create_ods():
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    params = {
        "target_table": "ods_ad_report_daily",
        "source_table": "ad_report",
        "source_type": "mysql",
        "datasource_name": "jky_singleshop",
    }
    task = planner.plan_create_ods(params)

    assert task.task_type == TaskType.CREATE_ODS
    assert "ods_ad_report_daily" in task.description
    assert len(task.plan) == 6
    step_names = [s["step"] for s in task.plan]
    assert step_names == [
        "validate_params",
        "generate_ddl",
        "create_table",
        "create_node",
        "configure_schedule",
        "verify",
    ]
    assert task.status == ExecutionStatus.PLANNED


@pytest.mark.asyncio
async def test_planner_create_dwd():
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    params = {
        "target_table": "dwd_ad_report_detail_di",
        "source_table": "ods_ad_report_daily",
        "domain": "mkt",
        "entity": "ad_report",
        "update_method": "day",
    }
    task = planner.plan_create_dwd(params)

    assert task.task_type == TaskType.CREATE_DWD
    assert "dwd_ad_report_detail_di" in task.description
    assert len(task.plan) == 9
    step_names = [s["step"] for s in task.plan]
    assert "discover_source_tables" in step_names
    assert "generate_ddl" in step_names
    assert "generate_sql" in step_names
    assert "create_table" in step_names
    assert "create_node" in step_names
    assert "configure_dependencies" in step_names
    assert "configure_schedule" in step_names
    assert "verify" in step_names


@pytest.mark.asyncio
async def test_planner_modify_task():
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    params = {"target_table": "dwd_ad_report_detail_di", "new_sql": "SELECT 1"}
    task = planner.plan_modify_task(params)

    assert task.task_type == TaskType.MODIFY_TASK
    step_names = [s["step"] for s in task.plan]
    assert "read_current" in step_names
    assert "apply_change" in step_names


@pytest.mark.asyncio
async def test_planner_generate_plan_by_intent():
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    task = planner.generate_plan("帮我创建一张 ODS 表", {"target_table": "ods_xxx"})
    assert task.task_type == TaskType.CREATE_ODS

    task = planner.generate_plan("创建 dwd_order_detail", {"target_table": "dwd_order_detail"})
    assert task.task_type == TaskType.CREATE_DWD

    task = planner.generate_plan("修改节点 SQL", {"target_table": "dwd_xxx"})
    assert task.task_type == TaskType.MODIFY_TASK

    task = planner.generate_plan("配置调度周期", {"target_table": "dwd_xxx", "cron": "0 3 * * *"})
    assert task.task_type == TaskType.CONFIGURE_SCHEDULE

    task = planner.generate_plan("设置上游依赖", {"target_table": "dwd_xxx"})
    assert task.task_type == TaskType.CONFIGURE_DEPENDENCY

    task = planner.generate_plan("建表", {"target_table": "ods_auto_infer"})
    assert task.task_type == TaskType.CREATE_ODS

    task = planner.generate_plan("建表", {"target_table": "dwd_auto_infer"})
    assert task.task_type == TaskType.CREATE_DWD


@pytest.mark.asyncio
async def test_planner_generate_plan_unknown_raises():
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    with pytest.raises(ValueError, match="无法识别意图"):
        planner.generate_plan("帮我查一下天气", {"target_table": "not_a_table"})


# ── Security Guard 测试 ──


@pytest.mark.asyncio
async def test_security_guard_blocks_publish():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context()
    guard = AutonomousSecurityGuard(context)

    with pytest.raises(SecurityViolationError, match="禁止执行发布"):
        await guard.validate_request(
            TaskType.MODIFY_TASK,
            {"operation": "deploy", "target_table": "dwd_xxx"},
        )


@pytest.mark.asyncio
async def test_security_guard_blocks_new_directory():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context()
    guard = AutonomousSecurityGuard(context)

    with pytest.raises(SecurityViolationError, match="不在允许范围内"):
        await guard.validate_request(
            TaskType.CREATE_ODS,
            {
                "target_table": "ods_xxx",
                "business_folder": "业务流程/其他域/MaxCompute/数据开发/00_ODS",
            },
        )


@pytest.mark.asyncio
async def test_security_guard_allows_approved_folder():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context()
    guard = AutonomousSecurityGuard(context)

    result = await guard.validate_request(
        TaskType.CREATE_ODS,
        {
            "target_table": "ods_ad_report_daily",
            "business_folder": "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS",
        },
    )
    assert result is True


@pytest.mark.asyncio
async def test_security_guard_allows_without_explicit_folder():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context()
    guard = AutonomousSecurityGuard(context)

    result = await guard.validate_request(
        TaskType.CREATE_ODS,
        {"target_table": "ods_ad_report_daily"},
    )
    assert result is True


@pytest.mark.asyncio
async def test_security_guard_blocks_destructive_node_op():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context()
    guard = AutonomousSecurityGuard(context)

    with pytest.raises(SecurityViolationError):
        await guard.validate_request(
            TaskType.MODIFY_TASK,
            {"operation": "DELETE_NODE", "target_table": "dwd_xxx"},
        )


@pytest.mark.asyncio
async def test_security_guard_blocks_disallowed_datasource():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context(allowed_data_sources=["odps"])
    guard = AutonomousSecurityGuard(context)

    with pytest.raises(SecurityViolationError, match="不在允许列表"):
        await guard.validate_request(
            TaskType.CREATE_ODS,
            {"target_table": "ods_xxx", "datasource_type": "postgresql"},
        )


@pytest.mark.asyncio
async def test_security_guard_allows_allowed_datasource():
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context(allowed_data_sources=["odps", "mysql"])
    guard = AutonomousSecurityGuard(context)

    result = await guard.validate_request(
        TaskType.CREATE_ODS,
        {"target_table": "ods_xxx", "datasource_type": "mysql"},
    )
    assert result is True


# ── Executor 测试（真实逻辑 + mock 客户端） ──


@pytest.mark.asyncio
async def test_executor_validate_params():
    """validate_params 应调用 assert_safe_table_name 和 validate_table_name。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test_table"},
        plan=[{"step": "validate_params"}],
    )
    assert await executor.execute_step(task, {"step": "validate_params"}) is True


@pytest.mark.asyncio
async def test_executor_validate_params_missing_target():
    """validate_params 缺少 target_table 应抛出 ValueError。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={},
        plan=[{"step": "validate_params"}],
    )
    with pytest.raises(ValueError, match="缺少 target_table"):
        await executor.execute_step(task, {"step": "validate_params"})


@pytest.mark.asyncio
async def test_executor_validate_params_injection_guard():
    """validate_params 应拦截注入攻击（B3）。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test; DROP TABLE"},
        plan=[{"step": "validate_params"}],
    )
    with pytest.raises(ValueError):
        await executor.execute_step(task, {"step": "validate_params"})


@pytest.mark.asyncio
async def test_executor_generate_ddl():
    """generate_ddl 应生成 DDL 并存入 task.params['_ddl']。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test_table", "source_type": "mysql", "source_table": "test_src"},
        plan=[{"step": "generate_ddl"}],
    )
    assert await executor.execute_step(task, {"step": "generate_ddl"}) is True
    assert "_ddl" in task.params
    assert "CREATE TABLE" in task.params["_ddl"]
    assert "ods_test_table" in task.params["_ddl"]


@pytest.mark.asyncio
async def test_executor_create_table(mock_app_state):
    """create_table 应调用 MaxComputeClient.execute_ddl。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test", "_ddl": "CREATE TABLE test (id BIGINT)"},
        plan=[{"step": "create_table"}],
    )
    assert await executor.execute_step(task, {"step": "create_table"}) is True
    assert task.params.get("_table_created") is True
    mock_app_state["mc"].execute_ddl.assert_called_once()


@pytest.mark.asyncio
async def test_executor_create_table_no_client():
    """create_table 无 MaxComputeClient 应抛出 RuntimeError。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    with patch("dataworks_agent.agent.autonomous.executor._get_maxcompute_client", return_value=None):
        executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
        task = AutonomousTask(
            task_type=TaskType.CREATE_ODS, description="test",
            params={"target_table": "ods_test", "_ddl": "CREATE TABLE test (id BIGINT)"},
            plan=[{"step": "create_table"}],
        )
        with pytest.raises(RuntimeError, match="MaxComputeClient 未初始化"):
            await executor.execute_step(task, {"step": "create_table"})


@pytest.mark.asyncio
async def test_executor_create_node(mock_app_state):
    """create_node 应调用 OpenAPINodeAdapter.create_node。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test", "business_folder": "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS"},
        plan=[{"step": "create_node"}],
    )
    assert await executor.execute_step(task, {"step": "create_node"}) is True
    assert task.params.get("_node_id") == "node_uuid_001"
    mock_app_state["nc"].create_node.assert_called_once()


@pytest.mark.asyncio
async def test_executor_create_node_reuses_existing(mock_app_state):
    """create_node 路径已存在时应复用 UUID。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    mock_app_state["nc"].get_node_uuid_by_path = AsyncMock(return_value="existing_uuid")
    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test", "business_folder": "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS"},
        plan=[{"step": "create_node"}],
    )
    assert await executor.execute_step(task, {"step": "create_node"}) is True
    assert task.params.get("_node_id") == "existing_uuid"
    mock_app_state["nc"].create_node.assert_not_called()


@pytest.mark.asyncio
async def test_executor_configure_schedule(mock_app_state):
    """configure_schedule 应调用 update_vertex 配置 cron。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test", "_node_id": "node_001", "granularity": "day"},
        plan=[{"step": "configure_schedule"}],
    )
    assert await executor.execute_step(task, {"step": "configure_schedule"}) is True
    assert task.params.get("_schedule_configured") is True
    mock_app_state["nc"].update_vertex.assert_called_once()


@pytest.mark.asyncio
async def test_executor_configure_dependencies(mock_app_state):
    """configure_dependencies 应读取 spec 并添加上游依赖。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    task = AutonomousTask(
        task_type=TaskType.CREATE_DWD, description="test",
        params={
            "target_table": "dwd_test",
            "_node_id": "node_001",
            "_upstream_tables": ["ods_source_a", "ods_source_b"],
        },
        plan=[{"step": "configure_dependencies"}],
    )
    assert await executor.execute_step(task, {"step": "configure_dependencies"}) is True
    assert task.params.get("_dependencies_configured") is True
    mock_app_state["nc"]._save_spec.assert_called_once()


@pytest.mark.asyncio
async def test_executor_stops_on_failed_step():
    """当某一步骤返回 False 时，executor 应停止后续执行并标记失败。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    executor = AutonomousExecutor(_mock_openapi_client(), _mock_modeling_engine())
    call_count = {"n": 0}

    async def failing_step(task: AutonomousTask, step: dict[str, Any]) -> bool:
        call_count["n"] += 1
        return False

    executor.execute_step = failing_step  # type: ignore[assignment]

    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test"},
        plan=[{"step": "step1"}, {"step": "step2"}, {"step": "step3"}],
    )

    success = await executor.execute_task(task)
    assert success is False
    assert task.status == ExecutionStatus.FAILED
    assert call_count["n"] == 1


# ── Verifier 测试（真实逻辑 + mock 客户端） ──


@pytest.mark.asyncio
async def test_verifier_ods_creation_all_present(mock_app_state):
    """ODS 创建验证：表存在、节点存在、调度已配置 → 全部通过。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

    verifier = AutonomousVerifier(_mock_openapi_client())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test", "_node_id": "node_001"},
    )

    result = await verifier.verify_task(task)
    assert result.success is True
    check_names = [c["name"] for c in result.checks]
    assert "table_exists" in check_names
    assert "node_exists" in check_names
    assert "schedule_configured" in check_names
    assert task.status == ExecutionStatus.VERIFIED


@pytest.mark.asyncio
async def test_verifier_ods_creation_table_missing(mock_app_state):
    """ODS 创建验证：表不存在 → 失败。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

    mock_app_state["mc"].table_exists = AsyncMock(return_value=False)
    verifier = AutonomousVerifier(_mock_openapi_client())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test", "_node_id": "node_001"},
    )

    result = await verifier.verify_task(task)
    assert result.success is False
    table_check = next(c for c in result.checks if c["name"] == "table_exists")
    assert table_check["passed"] is False


@pytest.mark.asyncio
async def test_verifier_dwd_creation(mock_app_state):
    """DWD 创建验证应包含 dependencies_configured。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

    verifier = AutonomousVerifier(_mock_openapi_client())
    task = AutonomousTask(
        task_type=TaskType.CREATE_DWD, description="test",
        params={"target_table": "dwd_test", "_node_id": "node_001"},
    )

    result = await verifier.verify_task(task)
    assert result.success is True
    check_names = [c["name"] for c in result.checks]
    assert "dependencies_configured" in check_names
    assert "schedule_configured" in check_names


@pytest.mark.asyncio
async def test_verifier_no_node_id():
    """无 node_id 时验证应标记 node_exists 为失败。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

    verifier = AutonomousVerifier(_mock_openapi_client())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test"},
    )

    result = await verifier.verify_task(task)
    node_check = next(c for c in result.checks if c["name"] == "node_exists")
    assert node_check["passed"] is False


# ── AutonomousAgent 主流程测试 ──


@pytest.mark.asyncio
async def test_autonomous_agent_process_ods_request(mock_app_state):
    """完整流程：ODS 请求应经过规划→安全预检→执行→验证。"""
    agent = AutonomousAgent(
        context=_make_context(),
        openapi_client=_mock_openapi_client(),
        modeling_engine=_mock_modeling_engine(),
    )

    task = await agent.process_request(
        "帮我创建 ODS 表",
        {
            "target_table": "ods_ad_report_daily",
            "source_table": "ad_report",
            "source_type": "mysql",
        },
    )

    assert task.task_type == TaskType.CREATE_ODS
    assert task.status == ExecutionStatus.VERIFIED
    assert task.error_message is None
    assert task.verification_result is not None
    assert task.verification_result["success"] is True


@pytest.mark.asyncio
async def test_autonomous_agent_process_dwd_request(mock_app_state):
    """完整流程：DWD 请求应包含 discover_source_tables 和 configure_dependencies。"""
    agent = AutonomousAgent(
        context=_make_context(),
        openapi_client=_mock_openapi_client(),
        modeling_engine=_mock_modeling_engine(),
    )

    task = await agent.process_request(
        "创建 dwd_ad_report_detail_di",
        {
            "target_table": "dwd_ad_report_detail_di",
            "source_table": "ods_ad_report_daily",
            "domain": "mkt",
            "entity": "ad_report",
            "update_method": "day",
        },
    )

    assert task.task_type == TaskType.CREATE_DWD
    assert task.status == ExecutionStatus.VERIFIED
    assert len(task.step_results) == 9


@pytest.mark.asyncio
async def test_autonomous_agent_security_violation_returns_failed_task():
    """安全守卫拦截时，Agent 应返回 FAILED 状态的 task 而非抛异常。"""
    agent = AutonomousAgent(
        context=_make_context(),
        openapi_client=_mock_openapi_client(),
        modeling_engine=_mock_modeling_engine(),
    )

    task = await agent.process_request(
        "发布节点",
        {"operation": "deploy", "target_table": "dwd_xxx"},
    )

    assert task.status == ExecutionStatus.FAILED
    assert "安全守卫拦截" in task.error_message


@pytest.mark.asyncio
async def test_autonomous_agent_retry_failed_task(mock_app_state):
    """重试失败任务应重新执行步骤并尝试验证。"""
    agent = AutonomousAgent(
        context=_make_context(),
        openapi_client=_mock_openapi_client(),
        modeling_engine=_mock_modeling_engine(),
    )

    task = await agent.process_request(
        "帮我创建 ODS 表",
        {"target_table": "ods_retry_test"},
    )
    assert task.status == ExecutionStatus.VERIFIED

    task.mark_failed("模拟失败")
    retried = await agent.retry_task(task)

    assert retried.status == ExecutionStatus.VERIFIED
    assert retried.error_message is None


@pytest.mark.asyncio
async def test_autonomous_agent_unrecognized_intent_raises():
    """无法识别的意图应抛出 ValueError。"""
    agent = AutonomousAgent(
        context=_make_context(),
        openapi_client=_mock_openapi_client(),
        modeling_engine=_mock_modeling_engine(),
    )

    with pytest.raises(ValueError, match="无法识别意图"):
        await agent.process_request("今天天气不错", {})


@pytest.mark.asyncio
async def test_autonomous_agent_folder_violation_returns_failed():
    """跨文件夹请求应被安全守卫拦截并标记为失败。"""
    agent = AutonomousAgent(
        context=_make_context(),
        openapi_client=_mock_openapi_client(),
        modeling_engine=_mock_modeling_engine(),
    )

    task = await agent.process_request(
        "帮我创建 ODS 表",
        {
            "target_table": "ods_xxx",
            "business_folder": "业务流程/非广告报告/数据开发/00_ODS",
        },
    )

    assert task.status == ExecutionStatus.FAILED
    assert "安全守卫拦截" in task.error_message
