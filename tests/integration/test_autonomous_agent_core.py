"""Autonomous Agent 核心框架集成测试。

使用 MagicMock 模拟外部依赖，覆盖：
- ODS/DWD 任务规划
- 安全守卫拦截规则
- AutonomousAgent 主流程骨架
"""

from __future__ import annotations

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


def _mock_openapi_client():
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get_node.return_value = {"Node": {"Id": "999", "Name": "test_table"}}
    client.list_nodes.return_value = {"PagingInfo": {"Nodes": []}}
    client.create_node.return_value = {"NodeId": "999"}
    client.update_node.return_value = {"Success": True}
    return client


def _mock_modeling_engine():
    from unittest.mock import MagicMock

    engine = MagicMock()
    engine.create_task.return_value = "task_mock_001"
    return engine


# ── Planner 测试 ──


@pytest.mark.asyncio
async def test_planner_create_ods():
    """ODS 创建任务应包含 validate_params → generate_ddl → create_table → create_node → configure_schedule → verify。"""
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
    """DWD 创建任务应包含 discover_source_tables、generate_sql、configure_dependencies 等完整步骤链。"""
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
    """修改任务应包含 read_current → apply_change 步骤。"""
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
    """generate_plan 应根据意图字符串路由到正确的规划方法。"""
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    # ODS 意图
    task = planner.generate_plan("帮我创建一张 ODS 表", {"target_table": "ods_xxx"})
    assert task.task_type == TaskType.CREATE_ODS

    # DWD 意图
    task = planner.generate_plan("创建 dwd_order_detail", {"target_table": "dwd_order_detail"})
    assert task.task_type == TaskType.CREATE_DWD

    # 修改意图
    task = planner.generate_plan("修改节点 SQL", {"target_table": "dwd_xxx"})
    assert task.task_type == TaskType.MODIFY_TASK

    # 调度意图
    task = planner.generate_plan("配置调度周期", {"target_table": "dwd_xxx", "cron": "0 3 * * *"})
    assert task.task_type == TaskType.CONFIGURE_SCHEDULE

    # 依赖意图
    task = planner.generate_plan("设置上游依赖", {"target_table": "dwd_xxx"})
    assert task.task_type == TaskType.CONFIGURE_DEPENDENCY

    # 兜底：从 target_table 前缀推断
    task = planner.generate_plan("建表", {"target_table": "ods_auto_infer"})
    assert task.task_type == TaskType.CREATE_ODS

    task = planner.generate_plan("建表", {"target_table": "dwd_auto_infer"})
    assert task.task_type == TaskType.CREATE_DWD


@pytest.mark.asyncio
async def test_planner_generate_plan_unknown_raises():
    """无法识别的意图应抛出 ValueError。"""
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    with pytest.raises(ValueError, match="无法识别意图"):
        planner.generate_plan("帮我查一下天气", {"target_table": "not_a_table"})


# ── Security Guard 测试 ──


@pytest.mark.asyncio
async def test_security_guard_blocks_publish():
    """安全守卫应阻止发布意图。"""
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
    """安全守卫应阻止不在白名单内的业务文件夹。"""
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
    """广告报告目录下的操作应通过安全守卫。"""
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
    """未显式指定 business_folder 时不应阻断。"""
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
    """安全守卫应阻止 delete_node / offline 等破坏性节点操作。"""
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
    """不在允许列表中的数据源类型应被拦截。"""
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
    """在允许列表中的数据源类型应放行。"""
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    context = _make_context(allowed_data_sources=["odps", "mysql"])
    guard = AutonomousSecurityGuard(context)

    result = await guard.validate_request(
        TaskType.CREATE_ODS,
        {"target_table": "ods_xxx", "datasource_type": "mysql"},
    )
    assert result is True


# ── Executor 测试 ──


@pytest.mark.asyncio
async def test_executor_runs_placeholder_steps():
    """Executor 应能顺序执行占位步骤并返回成功。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    openapi_client = _mock_openapi_client()
    modeling_engine = _mock_modeling_engine()
    executor = AutonomousExecutor(openapi_client, modeling_engine)

    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS,
        description="测试 ODS 创建",
        params={"target_table": "ods_test"},
        plan=[
            {"step": "validate_params", "description": "校验参数"},
            {"step": "generate_ddl", "description": "生成 DDL"},
            {"step": "verify", "description": "验证"},
        ],
    )

    success = await executor.execute_task(task)
    assert success is True
    assert task.status == ExecutionStatus.EXECUTING
    assert len(task.step_results) == 3
    assert all(r.status == "completed" for r in task.step_results)


@pytest.mark.asyncio
async def test_executor_stops_on_failed_step():
    """当某一步骤返回 False 时，executor 应停止后续执行并标记失败。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

    openapi_client = _mock_openapi_client()
    modeling_engine = _mock_modeling_engine()
    executor = AutonomousExecutor(openapi_client, modeling_engine)

    call_count = {"n": 0}

    async def failing_step(task: AutonomousTask, step: dict[str, Any]) -> bool:
        call_count["n"] += 1
        return False

    # 用 mock 替换 execute_step 以注入失败
    original_execute_step = executor.execute_step
    executor.execute_step = failing_step  # type: ignore[assignment]

    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS,
        description="测试失败",
        params={"target_table": "ods_test"},
        plan=[
            {"step": "step1"},
            {"step": "step2"},
            {"step": "step3"},
        ],
    )

    success = await executor.execute_task(task)
    assert success is False
    assert task.status == ExecutionStatus.FAILED
    assert call_count["n"] == 1  # 应在第一步后停止


# ── Verifier 测试 ──


@pytest.mark.asyncio
async def test_verifier_ods_creation():
    """ODS 创建验证应返回 success=True 且包含 table_exists/node_exists/schedule_configured。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

    verifier = AutonomousVerifier(_mock_openapi_client())

    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS,
        description="测试 ODS 验证",
        params={"target_table": "ods_test"},
    )

    result = await verifier.verify_task(task)
    assert result.success is True
    check_names = [c["name"] for c in result.checks]
    assert "table_exists" in check_names
    assert "node_exists" in check_names
    assert "schedule_configured" in check_names
    assert task.status == ExecutionStatus.VERIFIED


@pytest.mark.asyncio
async def test_verifier_dwd_creation():
    """DWD 创建验证应额外检查 dependencies_configured。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

    verifier = AutonomousVerifier(_mock_openapi_client())

    task = AutonomousTask(
        task_type=TaskType.CREATE_DWD,
        description="测试 DWD 验证",
        params={"target_table": "dwd_test"},
    )

    result = await verifier.verify_task(task)
    assert result.success is True
    check_names = [c["name"] for c in result.checks]
    assert "dependencies_configured" in check_names
    assert "schedule_configured" in check_names


# ── AutonomousAgent 主流程测试 ──


@pytest.mark.asyncio
async def test_autonomous_agent_process_ods_request():
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
async def test_autonomous_agent_process_dwd_request():
    """完整流程：DWD 请求应包含 discover_source_tables 和 configure_dependencies 步骤。"""
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
async def test_autonomous_agent_retry_failed_task():
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

    # 手动标记失败以测试重试路径
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
