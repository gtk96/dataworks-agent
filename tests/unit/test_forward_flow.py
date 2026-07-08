"""ForwardModelingFlow 单元测试 — 正向建模流程。"""

import pytest

from dataworks_agent.runtime.forward_flow import (
    ForwardModelingFlow,
    ModelingRequest,
    ModelingResult,
)


@pytest.fixture
def flow():
    """创建 ForwardModelingFlow 实例。"""
    return ForwardModelingFlow()


def test_build_target_table_daily(flow):
    """构建目标表名 — 日增量。"""
    request = ModelingRequest(
        source_table="ods_ord_order_hour",
        target_layer="DWD",
        domain="ord",
        entity="order_detail",
        update_method="day",
    )
    target = flow._build_target_table(request)
    assert target == "dwd_ord_order_detail_day"


def test_build_target_table_hourly(flow):
    """构建目标表名 — 小时增量。"""
    request = ModelingRequest(
        source_table="ods_ord_order_hour",
        target_layer="DWD",
        domain="ord",
        entity="order_detail",
        update_method="hourly",
    )
    target = flow._build_target_table(request)
    assert target == "dwd_ord_order_detail_hourly"


def test_generate_ddl(flow):
    """生成 DDL。"""
    request = ModelingRequest(
        source_table="ods_ord_order_hour",
        target_layer="DWD",
        domain="ord",
        entity="order_detail",
        update_method="day",
        columns=[{"name": "id", "type": "STRING"}, {"name": "name", "type": "STRING"}],
    )
    source_info = {"columns": []}
    ddl = flow._generate_ddl(request, "dwd_ord_order_detail_day", source_info)
    assert "CREATE TABLE dwd_ord_order_detail_day" in ddl
    assert "id STRING" in ddl


def test_generate_dml(flow):
    """生成 DML。"""
    request = ModelingRequest(
        source_table="ods_ord_order_hour",
        target_layer="DWD",
        domain="ord",
        entity="order_detail",
        update_method="day",
        columns=[{"name": "id"}, {"name": "name"}],
    )
    source_info = {"columns": []}
    sql = flow._generate_dml(request, "dwd_ord_order_detail_day", source_info)
    assert "INSERT OVERWRITE TABLE dwd_ord_order_detail_day" in sql
    assert "ods_ord_order_hour" in sql


@pytest.mark.asyncio
async def test_execute_dry_run(flow):
    """执行建模流程 — dry_run 模式。"""
    request = ModelingRequest(
        source_table="ods_ord_order_hour",
        target_layer="DWD",
        domain="ord",
        entity="order_detail",
        update_method="day",
        dry_run=True,
    )
    result = await flow.execute(request)
    assert result.success is True
    assert result.target_table == "dwd_ord_order_detail_day"
    assert len(result.steps) > 0


@pytest.mark.asyncio
async def test_execute_full(flow):
    """执行建模流程 — 完整模式。"""
    request = ModelingRequest(
        source_table="ods_ord_order_hour",
        target_layer="DWD",
        domain="ord",
        entity="order_detail",
        update_method="day",
    )
    result = await flow.execute(request)
    assert result.success is True
    assert result.node_uuid.startswith("node_")


def test_modeling_result_post_init():
    """ModelingResult 初始化。"""
    result = ModelingResult(success=True, task_id="task_001")
    assert result.task_id == "task_001"
    assert result.errors == []
