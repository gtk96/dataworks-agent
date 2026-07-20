"""真实写入测试 — 在广告报告目录下创建测试节点，验证后清理。

严格约束:
  - 仅在已存在的 广告报告 目录下创建节点，禁止新建目录
  - 节点名带 e2e_test_ 前缀，便于识别和清理
  - 测试完成后删除测试节点
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALIYUN_ACCESS_KEY_ID"),
    reason="需要 ALIYUN_ACCESS_KEY_ID 环境变量",
)


def _init_clients():
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


TEST_NODE_NAME = "e2e_test_autonomous_verify"
TEST_FOLDER = "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS"


@pytest.mark.asyncio
async def test_01_verify_directory_exists():
    """验证目标目录已存在（禁止新建目录的前提）。"""
    _, _, adapter = _init_clients()
    evidence = await adapter.check_existing_directory(TEST_FOLDER)
    assert evidence is not None
    print(f"  目录存在: {TEST_FOLDER}")
    print(f"  目录证据: {evidence}")


@pytest.mark.asyncio
async def test_02_create_node_real():
    """在广告报告目录下创建测试节点。"""
    _, _, adapter = _init_clients()

    # 先检查是否已存在，存在则复用
    from dataworks_agent.naming.table_name import generate_node_path
    path = generate_node_path(TEST_FOLDER, TEST_NODE_NAME)
    existing_uuid = await adapter.get_node_uuid_by_path(path)

    if existing_uuid:
        print(f"  节点已存在，复用: {path} (uuid={existing_uuid})")
        node_uuid = existing_uuid
    else:
        evidence = await adapter.check_existing_directory(TEST_FOLDER)
        node_uuid = await adapter.create_node(
            name=TEST_NODE_NAME,
            path=path,
            language="odps-sql",
            directory_evidence=evidence,
        )
        assert node_uuid is not None, "节点创建失败"
        print(f"  节点创建成功: {path} (uuid={node_uuid})")

    # 验证节点能读取
    spec = await adapter._load_spec(node_uuid)
    assert spec is not None, "无法读取节点 spec"
    print(f"  节点 spec 读取成功: {list(spec.keys())}")

    return node_uuid


@pytest.mark.asyncio
async def test_03_configure_schedule_real():
    """为测试节点配置调度。"""
    _, _, adapter = _init_clients()

    # 先获取节点 uuid
    from dataworks_agent.naming.table_name import generate_node_path
    path = generate_node_path(TEST_FOLDER, TEST_NODE_NAME)
    node_uuid = await adapter.get_node_uuid_by_path(path)
    assert node_uuid is not None, "测试节点不存在"

    from dataworks_agent.naming.schedule import DAILY_SQL_PARAMETERS, generate_cron

    config = {
        "trigger": {
            "cron": generate_cron("day"),
            "cycleType": "Daily",
            "timezone": "Asia/Shanghai",
        },
        "script": {
            "parameters": DAILY_SQL_PARAMETERS,
        },
        "strategy": {
            "instanceMode": "Immediately",
            "rerunMode": "Allowed",
        },
    }

    success = await adapter.update_vertex(node_uuid, config)
    assert success, "调度配置失败"
    print(f"  调度配置成功: cron={config['trigger']['cron']}")

    # 验证调度已写入
    spec = await adapter._load_spec(node_uuid)
    trigger = spec.get("spec", {}).get("nodes", [{}])[0].get("trigger", {})
    assert trigger.get("cron") == config["trigger"]["cron"]
    print(f"  调度验证通过: {trigger}")


@pytest.mark.asyncio
async def test_04_read_node_real():
    """读取节点完整配置。"""
    _, _, adapter = _init_clients()

    from dataworks_agent.naming.table_name import generate_node_path
    path = generate_node_path(TEST_FOLDER, TEST_NODE_NAME)
    node_uuid = await adapter.get_node_uuid_by_path(path)
    assert node_uuid is not None

    spec = await adapter._load_spec(node_uuid)
    assert spec is not None

    nodes = spec.get("spec", {}).get("nodes", [])
    assert len(nodes) > 0
    node = nodes[0]
    print(f"  节点名称: {node.get('script', {}).get('path', 'N/A')}")
    print(f"  节点语言: {node.get('script', {}).get('language', 'N/A')}")
    print(f"  调度 cron: {node.get('trigger', {}).get('cron', 'N/A')}")
    print(f"  节点读取验证通过")


@pytest.mark.asyncio
async def test_05_cleanup_delete_node():
    """清理测试节点。"""
    _, _, adapter = _init_clients()

    from dataworks_agent.naming.table_name import generate_node_path
    path = generate_node_path(TEST_FOLDER, TEST_NODE_NAME)
    node_uuid = await adapter.get_node_uuid_by_path(path)

    if node_uuid:
        # 使用 OpenAPI 删除节点
        from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient
        api = adapter._api
        try:
            await api.delete_node(node_id=node_uuid)
            print(f"  测试节点已删除: {node_uuid}")
        except Exception as exc:
            print(f"  删除节点失败（可能需要手动清理）: {exc}")
    else:
        print("  测试节点不存在，无需清理")
