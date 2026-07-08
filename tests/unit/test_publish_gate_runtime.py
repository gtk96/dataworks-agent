"""PublishGate Runtime 单元测试 — interrupt/resume 审批闸口。"""

import pytest

from dataworks_agent.runtime.publish_gate import PublishGate, PublishRequest


@pytest.fixture
def gate():
    """创建 PublishGate 实例。"""
    return PublishGate()


@pytest.mark.asyncio
async def test_interrupt_for_approval(gate):
    """中断运行等待审批。"""
    request = await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={"ddl": "CREATE TABLE ..."},
    )

    assert request.request_id.startswith("pub_")
    assert request.run_id == "run_001"
    assert request.table_name == "dwd_ord_order_day"
    assert request.change_type == "create"
    assert request.status == "pending"


@pytest.mark.asyncio
async def test_approve_request(gate):
    """批准发布请求。"""
    request = await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={},
    )

    result = await gate.approve_request(
        request_id=request.request_id,
        reviewer="admin",
        comment="LGTM",
    )

    assert result is not None
    assert result.status == "approved"
    assert result.reviewer == "admin"
    assert result.review_comment == "LGTM"


@pytest.mark.asyncio
async def test_reject_request(gate):
    """拒绝发布请求。"""
    request = await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={},
    )

    result = await gate.reject_request(
        request_id=request.request_id,
        reviewer="admin",
        comment="需要修改",
    )

    assert result is not None
    assert result.status == "rejected"
    assert result.review_comment == "需要修改"


@pytest.mark.asyncio
async def test_get_request(gate):
    """获取发布请求。"""
    request = await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={},
    )

    retrieved = await gate.get_request(request.request_id)
    assert retrieved is not None
    assert retrieved.request_id == request.request_id


@pytest.mark.asyncio
async def test_list_pending_requests(gate):
    """列出待审批请求。"""
    await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={},
    )

    await gate.interrupt_for_approval(
        run_id="run_002",
        session_id="sess_002",
        table_name="dwd_ord_order_hour",
        change_type="update",
        payload={},
    )

    pending = await gate.list_pending_requests()
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_resume_after_approval(gate):
    """审批通过后恢复执行。"""
    request = await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={"ddl": "CREATE TABLE ..."},
        context={"actor": "test_user"},
    )

    await gate.approve_request(
        request_id=request.request_id,
        reviewer="admin",
    )

    result = await gate.resume_after_approval(request.request_id)
    assert result is not None
    assert result["run_id"] == "run_001"
    assert result["table_name"] == "dwd_ord_order_day"
    assert result["approved_by"] == "admin"


@pytest.mark.asyncio
async def test_resume_not_approved(gate):
    """未批准的请求不能恢复。"""
    request = await gate.interrupt_for_approval(
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_ord_order_day",
        change_type="create",
        payload={},
    )

    result = await gate.resume_after_approval(request.request_id)
    assert result is None


def test_publish_request_post_init():
    """PublishRequest 初始化。"""
    request = PublishRequest(
        request_id="",
        run_id="run_001",
        session_id="sess_001",
        table_name="dwd_test",
        change_type="create",
    )
    assert request.created_at != ""
