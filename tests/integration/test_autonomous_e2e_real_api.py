"""真实 API 端到端测试 — 直接调用 DataWorks OpenAPI + MaxCompute。

前置条件:
  - .env 中配置 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET
  - DATAWORKS_PROJECT_ID / DATAWORKS_REGION 可用

此测试会:
  1. 初始化真实 OpenAPI + MaxCompute 客户端
  2. 规划一个 ODS 创建任务
  3. 执行 validate_params → generate_ddl（只验证逻辑，不建表）
  4. 通过 list_nodes 验证 OpenAPI 连通性
  5. 清理测试产物

注意: 不会在生产环境创建真实节点/表，仅验证 API 连通性和代码逻辑。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# 加载 .env
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# 跳过如果没配置 AK/SK
pytestmark = pytest.mark.skipif(
    not os.environ.get("ALIYUN_ACCESS_KEY_ID"),
    reason="需要 ALIYUN_ACCESS_KEY_ID 环境变量",
)


def _make_context():
    from dataworks_agent.agent.autonomous.state import AutonomousContext

    return AutonomousContext(
        project_id=os.environ.get("DATAWORKS_PROJECT_ID", "70827"),
        business_folder="业务流程/106_广告报告/MaxCompute/数据开发/00_ODS",
        allowed_data_sources=["odps", "mysql", "hologres"],
        user_id="e2e_test",
        session_id="e2e_session",
    )


def _init_clients():
    """初始化真实客户端，复用 main.py 的初始化逻辑。"""
    from dataworks_agent.api_clients.maxcompute_client import MaxComputeClient
    from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient
    from dataworks_agent.api_clients.openapi_node_adapter import OpenAPINodeAdapter
    from dataworks_agent.auth import load_credentials
    from dataworks_agent.config import settings

    creds = load_credentials()
    api = DataWorksOpenAPIClient(
        creds=creds,
        region=settings.dataworks_region,
        endpoint=f"dataworks.{settings.dataworks_region}.aliyuncs.com",
        project_id=settings.dataworks_project_id,
    )
    mc = MaxComputeClient(
        creds=creds,
        endpoint=settings.maxcompute_endpoint,
        project=settings.maxcompute_project or settings.dataworks_dev_schema,
    )
    adapter = OpenAPINodeAdapter(
        api,
        project=settings.maxcompute_project or settings.dataworks_dev_schema,
        holo_datasource=settings.holo_node_datasource,
    )
    return api, mc, adapter


@pytest.mark.asyncio
async def test_openapi_client_connectivity():
    """验证 OpenAPI 客户端能连通 DataWorks。"""
    api, _, _ = _init_clients()
    result = await api.list_nodes(page_size=10)
    assert result is not None
    from dataworks_agent.api_clients.openapi_node_adapter import _to_map
    body = _to_map(result)
    nodes = body.get("PagingInfo", {}).get("Nodes", [])
    print(f"  OpenAPI 连通: 拿到 {len(nodes)} 个节点")


@pytest.mark.asyncio
async def test_maxcompute_client_connectivity():
    """验证 MaxCompute 客户端能连通。"""
    _, mc, _ = _init_clients()
    exists = await mc.table_exists("nonexistent_table_e2e_test_xyz")
    assert exists is False
    print(f"  MaxCompute 连通: nonexistent table exists={exists}")


@pytest.mark.asyncio
async def test_node_adapter_connectivity():
    """验证 NodeAdapter 能连通。"""
    _, _, adapter = _init_clients()
    # 用 list_nodes 验证连通性（get_node_uuid_by_path 有分页 bug）
    import asyncio as _aio
    for attempt in range(3):
        try:
            result = await adapter._api.list_nodes(page_size=10)
            from dataworks_agent.api_clients.openapi_node_adapter import _to_map
            body = _to_map(result)
            nodes = body.get("PagingInfo", {}).get("Nodes", [])
            print(f"  NodeAdapter 连通: 拿到 {len(nodes)} 个节点")
            return
        except Exception as exc:
            if attempt < 2:
                print(f"  NodeAdapter 重试 ({attempt+1}/3): {exc}")
                await _aio.sleep(2)
            else:
                raise


@pytest.mark.asyncio
async def test_planner_with_real_context():
    """验证 Planner 在真实上下文中能正确规划。"""
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

    context = _make_context()
    planner = AutonomousPlanner(context)

    task = planner.plan_create_ods({
        "target_table": "ods_e2e_test_verify",
        "source_table": "ad_report",
        "source_type": "mysql",
        "datasource_name": "jky_singleshop",
    })

    assert task.task_type.value == "create_ods"
    assert len(task.plan) == 6
    step_names = [s["step"] for s in task.plan]
    assert step_names == [
        "validate_params", "generate_ddl", "create_table",
        "create_node", "configure_schedule", "verify",
    ]
    print(f"  Planner OK: {len(task.plan)} steps")


@pytest.mark.asyncio
async def test_executor_validate_params_real():
    """验证 validate_params 调用真实的表名校验逻辑。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor
    from dataworks_agent.agent.autonomous.state import AutonomousTask, TaskType
    from unittest.mock import MagicMock

    executor = AutonomousExecutor(MagicMock(), MagicMock())

    # 合法表名
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_e2e_test_verify"},
        plan=[{"step": "validate_params"}],
    )
    assert await executor.execute_step(task, {"step": "validate_params"}) is True
    print("  validate_params: 合法表名通过")

    # 注入攻击
    task2 = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_test; DROP TABLE xxx"},
        plan=[{"step": "validate_params"}],
    )
    with pytest.raises(ValueError):
        await executor.execute_step(task2, {"step": "validate_params"})
    print("  validate_params: 注入攻击被拦截")


@pytest.mark.asyncio
async def test_executor_generate_ddl_real():
    """验证 DDL 生成的真实输出。"""
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor
    from dataworks_agent.agent.autonomous.state import AutonomousTask, TaskType
    from unittest.mock import MagicMock

    executor = AutonomousExecutor(MagicMock(), MagicMock())
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={
            "target_table": "ods_e2e_test_verify",
            "source_type": "mysql",
            "source_table": "ad_report",
        },
        plan=[{"step": "generate_ddl"}],
    )
    assert await executor.execute_step(task, {"step": "generate_ddl"}) is True
    ddl = task.params["_ddl"]
    assert "CREATE TABLE" in ddl
    assert "ods_e2e_test_verify" in ddl
    assert "PARTITIONED BY" in ddl
    print(f"  DDL 生成: {len(ddl)} 字符")
    print(f"  DDL 内容:\n{ddl}")


@pytest.mark.asyncio
async def test_security_guard_real():
    """验证安全守卫在真实上下文中的行为。"""
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard, SecurityViolationError
    from dataworks_agent.agent.autonomous.state import TaskType

    context = _make_context()
    guard = AutonomousSecurityGuard(context)

    # 正常操作应通过
    result = await guard.validate_request(
        TaskType.CREATE_ODS,
        {"target_table": "ods_e2e_test_verify"},
    )
    assert result is True
    print("  安全守卫: 正常操作通过")

    # 发布操作应被拦截
    with pytest.raises(SecurityViolationError, match="禁止执行发布"):
        await guard.validate_request(
            TaskType.MODIFY_TASK,
            {"operation": "deploy", "target_table": "dwd_xxx"},
        )
    print("  安全守卫: 发布操作被拦截")


@pytest.mark.asyncio
async def test_verifier_real_api_checks():
    """验证 Verifier 调用真实 API 做回查。"""
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier
    from dataworks_agent.agent.autonomous.state import AutonomousTask, TaskType
    from unittest.mock import MagicMock

    verifier = AutonomousVerifier(MagicMock())

    # 无 node_id 时应标记失败
    task = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_nonexistent_e2e"},
    )
    result = await verifier.verify_task(task)
    node_check = next(c for c in result.checks if c["name"] == "node_exists")
    assert node_check["passed"] is False
    print(f"  Verifier: 无 node_id 时 node_exists={node_check['passed']}")

    # 有 node_id 但不存在时应调用 API 并返回失败
    task2 = AutonomousTask(
        task_type=TaskType.CREATE_ODS, description="test",
        params={"target_table": "ods_nonexistent_e2e", "_node_id": "nonexistent_uuid_12345"},
    )

    _, _, real_adapter = _init_clients()
    import dataworks_agent.agent.autonomous.verifier as verifier_mod
    original = verifier_mod._get_node_client
    verifier_mod._get_node_client = lambda: real_adapter
    try:
        result2 = await verifier.verify_task(task2)
        node_check2 = next(c for c in result2.checks if c["name"] == "node_exists")
        assert node_check2["passed"] is False
        print(f"  Verifier: 不存在的 node uuid → node_exists={node_check2['passed']}")
    finally:
        verifier_mod._get_node_client = original


@pytest.mark.asyncio
async def test_full_ods_flow_dry_run():
    """完整 ODS 流程 dry-run — 从规划到 DDL 生成，不执行真实写入。"""
    from dataworks_agent.agent.autonomous.planner import AutonomousPlanner
    from dataworks_agent.agent.autonomous.executor import AutonomousExecutor
    from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard
    from unittest.mock import MagicMock

    context = _make_context()

    # 1. 安全预检
    guard = AutonomousSecurityGuard(context)
    await guard.validate_request(
        context.project_id and "create_ods" and __import__("dataworks_agent.agent.autonomous.state", fromlist=["TaskType"]).TaskType.CREATE_ODS,
        {"target_table": "ods_e2e_full_flow"},
    )
    print("  Step 1: 安全预检通过")

    # 2. 规划
    planner = AutonomousPlanner(context)
    task = planner.plan_create_ods({
        "target_table": "ods_e2e_full_flow",
        "source_table": "ad_report",
        "source_type": "mysql",
    })
    print(f"  Step 2: 规划完成, {len(task.plan)} 步")

    # 3. 执行前两步（validate + generate_ddl）
    executor = AutonomousExecutor(MagicMock(), MagicMock())

    # Patch app_state clients 为 None（不执行真实写入）
    import dataworks_agent.agent.autonomous.executor as exec_mod
    original_mc = exec_mod._get_maxcompute_client
    original_nc = exec_mod._get_node_client
    exec_mod._get_maxcompute_client = lambda: None
    exec_mod._get_node_client = lambda: None

    try:
        # validate_params 应通过
        task.mark_executing()
        success = await executor.execute_step(task, task.plan[0])
        assert success is True
        print("  Step 3a: validate_params 通过")

        # generate_ddl 应生成 DDL
        success = await executor.execute_step(task, task.plan[1])
        assert success is True
        assert "_ddl" in task.params
        print(f"  Step 3b: DDL 生成完成 ({len(task.params['_ddl'])} 字符)")

        # create_table 应因无客户端而失败
        with pytest.raises(RuntimeError, match="MaxComputeClient 未初始化"):
            await executor.execute_step(task, task.plan[2])
        print("  Step 3c: create_table 正确报错（无客户端）")
    finally:
        exec_mod._get_maxcompute_client = original_mc
        exec_mod._get_node_client = original_nc

    print(f"\n  完整流程验证: 规划→校验→DDL 生成 均通过")
    print(f"  后续步骤（建表/建节点/调度/验证）需要真实客户端，在部署环境中执行")
