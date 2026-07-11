import pytest

from dataworks_agent.agent.core import ChatAgent, ChatResponse
from dataworks_agent.agent.executor.task_executor import ExecutionResult, StepResult


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
    assert "请输入您的需求" in response.message


@pytest.mark.asyncio
async def test_chat_agent_whitespace_message():
    """测试 ChatAgent 纯空格消息"""
    agent = ChatAgent()
    response = await agent.chat("   ")
    assert response.success is False
    assert "请输入您的需求" in response.message


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
