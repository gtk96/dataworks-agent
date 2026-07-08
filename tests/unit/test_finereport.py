"""FineReportAdapter 单元测试 — 帆软报表接入。"""

import pytest

from dataworks_agent.runtime.finereport import (
    FineReportAdapter,
    FineReportContext,
    FineReportResponse,
)


@pytest.fixture
def adapter():
    """创建 FineReportAdapter 实例。"""
    return FineReportAdapter()


@pytest.mark.asyncio
async def test_handle_report_context(adapter):
    """处理报表上下文。"""
    context = FineReportContext(
        report_id="report_001",
        report_name="订单报表",
        metric_id="order_count",
    )
    result = await adapter.handle_report_context(context)

    assert isinstance(result, FineReportResponse)
    assert result.report_id == "report_001"
    assert result.error == ""


@pytest.mark.asyncio
async def test_get_caliber_info(adapter):
    """获取口径信息。"""
    info = await adapter._get_caliber_info("nonexistent_metric")
    assert info["metric_id"] == "nonexistent_metric"
    assert info["caliber"] == ""


def test_fine_report_context_post_init():
    """FineReportContext 初始化。"""
    context = FineReportContext(report_id="report_001")
    assert context.report_id == "report_001"
    assert context.dimensions == {}


def test_fine_report_response_post_init():
    """FineReportResponse 初始化。"""
    response = FineReportResponse(report_id="report_001")
    assert response.report_id == "report_001"
    assert response.error == ""
