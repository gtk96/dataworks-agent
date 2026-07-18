from __future__ import annotations

import pytest

from dataworks_agent.agent.context_resolver import ContextResolver, DialogueAction, ResolvedTurn


def _context(with_interaction: bool = True) -> dict:
    interaction = {
        "interaction_id": "int_orders",
        "type": "single_select",
        "purpose": "select_table",
        "prompt": "请选择候选表",
        "options": [
            {
                "id": "detail",
                "label": "订单明细表",
                "value": "dw.dwd_order_detail",
                "payload": {"selected_resources": {"table": "dw.dwd_order_detail"}},
            },
            {
                "id": "summary",
                "label": "订单汇总表",
                "value": "dw.dws_order_summary",
                "payload": {"selected_resources": {"table": "dw.dws_order_summary"}},
            },
        ],
        "allow_custom_input": True,
        "custom_input_placeholder": "输入其他条件",
        "state_version": 4,
        "status": "pending",
    }
    return {
        "objective": "查找订单相关表",
        "action": "ask_data",
        "params": {"layer": "dwd"},
        "selected_resources": {},
        "pending_interaction": interaction if with_interaction else {},
        "last_assistant_turn": {"content": "我找到了订单明细表和订单汇总表。"},
        "state_version": 4,
    }


@pytest.mark.parametrize(
    ("message", "action"),
    [
        ("重新开始", DialogueAction.RESET),
        ("取消这个任务", DialogueAction.CANCEL),
        ("你好", DialogueAction.GREETING),
        ("什么意思", DialogueAction.EXPLAIN),
        ("继续", DialogueAction.CONTINUE),
        ("换成 DWS", DialogueAction.MODIFY),
    ],
)
async def test_classifies_contextual_short_turns(message, action):
    result = await ContextResolver().resolve(message, _context())

    assert result.dialogue_action is action


@pytest.mark.parametrize(
    ("message", "option_id"),
    [
        ("第一个", "detail"),
        ("第1个", "detail"),
        ("第二个", "summary"),
        ("第2个", "summary"),
        ("最后一个", "summary"),
    ],
)
async def test_maps_ordinal_to_server_option(message, option_id):
    result = await ContextResolver().resolve(message, _context())

    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer is not None
    assert result.interaction_answer.option_id == option_id
    assert result.interaction_answer.state_version == 4
    assert result.consume_interaction is True


@pytest.mark.parametrize("message", ["订单汇总表", "dw.dws_order_summary"])
async def test_matches_pending_option_by_label_or_value(message):
    result = await ContextResolver().resolve(message, _context())

    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer is not None
    assert result.interaction_answer.option_id == "summary"
    assert result.context_updates == {"selected_resources": {"table": "dw.dws_order_summary"}}


async def test_preserves_full_selected_identifier():
    context = _context(False)
    context["selected_resources"] = {"table": "dw.dws_order_summary"}

    result = await ContextResolver().resolve("用刚才那张表继续", context)

    assert result.dialogue_action is DialogueAction.REFER
    assert result.context_updates == {"selected_resources": {"table": "dw.dws_order_summary"}}
    assert result.resolved_references == ["dw.dws_order_summary"]
    assert "dw.dws_order_summary" in result.rewritten_message


async def test_known_dataworks_task_is_new_goal():
    result = await ContextResolver().resolve("查询订单表", _context(False))

    assert result.dialogue_action is DialogueAction.NEW_GOAL
    assert result.rewritten_message == "查询订单表"


async def test_known_dataworks_entity_is_new_goal():
    result = await ContextResolver().resolve("订单表", _context(False))

    assert result.dialogue_action is DialogueAction.NEW_GOAL


class FakeFallback:
    async def classify(self, message, context):
        return ResolvedTurn(
            dialogue_action=DialogueAction.MODIFY,
            rewritten_message=context["objective"] + "\n补充信息：最近七天",
            context_updates={"params": {"date_range": "last_7_days"}},
            resolver="llm",
            confidence=0.91,
        )


async def test_uses_high_confidence_semantic_fallback():
    result = await ContextResolver(FakeFallback()).resolve("再加上最近七天", _context(False))

    assert result.resolver == "llm"
    assert result.context_updates["params"]["date_range"] == "last_7_days"


class LowConfidenceFallback:
    async def classify(self, message, context):
        return ResolvedTurn(
            dialogue_action=DialogueAction.MODIFY,
            rewritten_message=message,
            resolver="llm",
            confidence=0.69,
        )


async def test_low_confidence_fallback_requires_clarification():
    result = await ContextResolver(LowConfidenceFallback()).resolve("再弄一下", _context(False))

    assert result.dialogue_action is DialogueAction.CLARIFY
    assert result.resolver == "deterministic"


async def test_ordinal_without_card_requires_clarification():
    result = await ContextResolver().resolve("第二个", _context(False))

    assert result.dialogue_action is DialogueAction.CLARIFY
    assert result.interaction_answer is None


async def test_explanation_preserves_pending_interaction():
    result = await ContextResolver().resolve("什么意思", _context())

    assert result.dialogue_action is DialogueAction.EXPLAIN
    assert result.consume_interaction is False
