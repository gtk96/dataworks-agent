from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.core import ChatAgent, ChatResponse
from dataworks_agent.agent.executor.task_executor import ExecutionResult, StepResult
from dataworks_agent.agent.workflow_service import WorkflowResult


def test_chat_response_initialization():
    """测试 ChatResponse 初始化"""
    response = ChatResponse(message="test")
    assert response.message == "test"
    assert response.success is True
    assert response.data == {}
    assert response.error is None


def test_chat_response_with_error():
    """测试 ChatResponse 错误状态"""
    response = ChatResponse(message="error", success=False, error="something wrong")
    assert response.success is False
    assert response.error == "something wrong"


@pytest.mark.asyncio
async def test_chat_agent_empty_message():
    """测试 ChatAgent 空消息处理"""
    agent = ChatAgent()
    response = await agent.chat("")
    assert response.success is False
    assert "请输入你希望 Agent 达成" in response.message


@pytest.mark.asyncio
async def test_chat_agent_whitespace_message():
    """测试 ChatAgent 纯空格消息"""
    agent = ChatAgent()
    response = await agent.chat("   ")
    assert response.success is False
    assert "请输入你希望 Agent 达成" in response.message


@pytest.mark.asyncio
async def test_chat_agent_delegates_to_agent():
    """测试 ChatAgent 通过 NLU→Planner→Executor 链路处理"""
    agent = ChatAgent()

    response = await agent.chat("查询 ods_user")

    assert response.success is True
    assert "操作已完成" in response.message or "ods_user" in response.message
    assert "task_id" in response.data


@pytest.mark.asyncio
async def test_chat_agent_request_type_passed():
    """测试意图被正确解析并传递到规划器"""
    agent = ChatAgent()

    response = await agent.chat("建表 test_table")

    assert response.success is True
    assert "task_id" in response.data


@pytest.fixture
def agent():
    """创建 ChatAgent 并 mock TaskExecutor 以返回成功结果"""
    a = ChatAgent()

    def fake_execute(plan):
        return ExecutionResult(
            success=True,
            task_id=plan.task_id,
            step_results=[
                StepResult(step_id=s.step_id, tool=s.tool, success=True) for s in plan.steps
            ],
            errors=[],
        )

    a._task_executor.execute = fake_execute
    return a


@pytest.mark.asyncio
async def test_agent_chat_create_table(agent):
    """测试 Agent 处理创建表请求"""
    response = await agent.chat("创建ods_user表")
    assert response.success is True
    assert "ods_user" in response.message
    assert "task_id" in response.data


@pytest.mark.asyncio
async def test_agent_chat_query_lineage(agent):
    """测试 Agent 处理查询血缘请求"""
    response = await agent.chat("查询ods_user的血缘")
    assert response.success is True
    assert "ods_user" in response.message


@pytest.mark.asyncio
async def test_chat_agent_response_has_status_and_no_garbled_text():
    """Test Agent response includes status and has no garbled text."""
    query = chr(0x67E5) + chr(0x8BE2)
    agent = ChatAgent()

    response = await agent.chat(f"{query} ods_user")

    assert response.success is True
    assert response.data["status"]["task_id"] == response.data["task_id"]
    assert response.data["status"]["completed_steps"] >= 1
    assert "????" not in response.message
    assert "????" not in str(response.data)


@pytest.mark.asyncio
async def test_chat_agent_routes_bare_ask_data_to_auto_workflow():
    agent = ChatAgent()
    agent._workflow_service.execute = AsyncMock(
        return_value=WorkflowResult(
            success=True,
            message="query completed",
            workflow_type="ask_data",
            mode="dev_execute",
        )
    )

    response = await agent.chat(
        "\u4eca\u5929\u7684\u603b\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11"
    )

    assert response.success is True
    assert response.data["workflow_type"] == "ask_data"
    assert agent._workflow_service.execute.await_args.kwargs["execution_mode"] == "auto"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_action"),
    [
        ("\u9006\u5411\u5206\u6790 giikin_aliyun.tb_rp_ord_order_cnt_hi", "reverse_modeling"),
        ("\u68c0\u67e5\u6267\u884c\u5e95\u5ea7", "diagnose_issue"),
        ("\u6392\u67e5\u4efb\u52a1 nonexistent-task-id", "diagnose_issue"),
    ],
)
async def test_chat_agent_routes_workflow_without_request_type(message, expected_action):
    agent = ChatAgent()
    agent._workflow_service.execute = AsyncMock(
        return_value=WorkflowResult(
            success=True,
            message="ok",
            workflow_type=expected_action,
            mode="dev_execute",
        )
    )

    response = await agent.chat(message, execution_mode="auto")

    assert response.success is True
    assert response.data["workflow_type"] == expected_action
    assert response.data["intent"]["action"] == expected_action
    assert agent._workflow_service.execute.await_args.kwargs["action"] == expected_action
