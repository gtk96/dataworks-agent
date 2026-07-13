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


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_agent_keeps_structured_business_query_for_followups():
    agent = ChatAgent()
    first_frame = {
        "metric_id": "ad_spend_amt",
        "metric_name": "\u5e7f\u544a\u82b1\u8d39",
        "dimensions": ["platform"],
        "filters": {"family": "\u91d1\u72ee\u5bb6\u65cf"},
        "time_range": {
            "kind": "today",
            "start": "2026-07-13",
            "end": "2026-07-13",
        },
    }
    second_frame = {
        **first_frame,
        "dimensions": [],
        "filters": {"family": "\u91d1\u72ee\u5bb6\u65cf", "platform": "facebook"},
    }
    agent._workflow_service.understand_business_query = lambda message: (
        first_frame if "\u5e7f\u544a\u82b1\u8d39" in message else None
    )
    agent._workflow_service.refine_business_query = lambda message, previous: (
        second_frame if message == "\u53ea\u770b Facebook" and previous == first_frame else None
    )
    agent._workflow_service.execute = AsyncMock(
        side_effect=[
            WorkflowResult(
                success=True,
                message="first query completed",
                workflow_type="ask_data",
                mode="dev_execute",
                data={"semantic_plan": {"business_query": first_frame}},
            ),
            WorkflowResult(
                success=True,
                message="follow-up completed",
                workflow_type="ask_data",
                mode="dev_execute",
                data={"semantic_plan": {"business_query": second_frame}},
            ),
        ]
    )

    first = await agent.chat(
        "\u91d1\u72ee\u5bb6\u65cf\u4eca\u5929\u5404\u5e73\u53f0\u5e7f\u544a\u82b1\u8d39\u662f\u591a\u5c11\uff1f",
        conversation_id="conversation-1",
    )
    second = await agent.chat("\u53ea\u770b Facebook", conversation_id="conversation-1")

    assert first.success is True
    assert second.success is True
    assert agent._workflow_service.execute.await_args_list[1].kwargs["action"] == "ask_data"
    assert (
        agent._workflow_service.execute.await_args_list[1].kwargs["params"]["business_query"]
        == second_frame
    )


@pytest.mark.asyncio
async def test_chat_agent_keeps_pending_workflow_context_for_short_followup() -> None:
    agent = ChatAgent()
    conversation_id = "oss-followup"
    first = await agent.chat(
        "oss 数据源 sample_material_report 建模处理",
        execution_mode="auto",
        conversation_id=conversation_id,
    )
    assert first.data["agent_mode"] == "needs_context"

    agent._workflow_service.execute = AsyncMock(
        return_value=WorkflowResult(
            success=True,
            message="continued",
            workflow_type="forward_modeling",
            mode="dev_execute",
        )
    )
    followup = (
        "oss://oss-cn-shenzhen-internal.aliyuncs.com/example-data-bucket/"
        "ads/data/sample_material_report/ 字段是 json"
    )
    second = await agent.chat(
        followup,
        execution_mode="auto",
        conversation_id=conversation_id,
    )

    assert second.success is True
    sent = agent._workflow_service.execute.await_args.kwargs
    assert "sample_material_report" in sent["message"]
    assert followup in sent["message"]
    assert sent["params"]["source_type"] == "oss"
    assert sent["params"]["file_format"] == "json"
    assert sent["params"]["oss_path"] == followup.removesuffix(" 字段是 json")
    assert await agent._conversation_graph.pending_objective(conversation_id) == ""
