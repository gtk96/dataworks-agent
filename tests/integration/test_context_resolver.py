from __future__ import annotations

import pytest
from pydantic import ValidationError

from dataworks_agent.agent.context_resolver import (
    ContextResolver,
    DialogueAction,
    LLMDialogueFallback,
    ResolvedTurn,
)


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


def _context_with_options(options: list[dict]) -> dict:
    context = _context()
    context["pending_interaction"]["options"] = options
    return context


async def test_exact_option_value_wins_over_prefix_substring_match():
    context = _context_with_options(
        [
            {
                "id": "order",
                "label": "订单表",
                "value": "dw.order",
                "payload": {"selected_resources": {"table": "dw.order"}},
            },
            {
                "id": "order_detail",
                "label": "订单明细表",
                "value": "dw.order_detail",
                "payload": {"selected_resources": {"table": "dw.order_detail"}},
            },
        ]
    )

    result = await ContextResolver().resolve("dw.order_detail", context)

    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer is not None
    assert result.interaction_answer.option_id == "order_detail"


async def test_exact_option_label_wins_over_shorter_label_substring():
    context = _context_with_options(
        [
            {"id": "order", "label": "订单", "value": "order", "payload": {}},
            {
                "id": "summary",
                "label": "订单汇总",
                "value": "summary",
                "payload": {},
            },
        ]
    )

    result = await ContextResolver().resolve("订单汇总", context)

    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer is not None
    assert result.interaction_answer.option_id == "summary"


async def test_unique_option_substring_match_is_allowed():
    result = await ContextResolver().resolve("我选择订单汇总表继续", _context())

    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer is not None
    assert result.interaction_answer.option_id == "summary"


@pytest.mark.parametrize(
    "options",
    [
        [
            {"id": "order", "label": "订单", "value": "order", "payload": {}},
            {
                "id": "summary",
                "label": "订单汇总",
                "value": "summary",
                "payload": {},
            },
        ],
        [
            {"id": "order", "label": "订单", "value": "dw.order", "payload": {}},
            {
                "id": "detail",
                "label": "明细",
                "value": "dw.order_detail",
                "payload": {},
            },
        ],
    ],
)
async def test_ambiguous_option_substring_requires_clarification(options):
    context = _context_with_options(options)
    message = "查看订单汇总数据" if options[1]["id"] == "summary" else "选择 dw.order_detail.v2"

    result = await ContextResolver().resolve(message, context)

    assert result.dialogue_action is DialogueAction.CLARIFY
    assert result.interaction_answer is None


@pytest.mark.parametrize(
    "option",
    [
        {"id": "continue", "label": "继续", "value": "next", "payload": {}},
        {"id": "continue", "label": "下一步", "value": "继续", "payload": {}},
    ],
)
async def test_pending_exact_option_wins_over_continue_action(option):
    context = _context_with_options([option])

    result = await ContextResolver().resolve("继续", context)

    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer is not None
    assert result.interaction_answer.option_id == "continue"


@pytest.mark.parametrize(
    ("message", "action"),
    [
        ("你好", DialogueAction.GREETING),
        ("什么意思", DialogueAction.EXPLAIN),
        ("继续", DialogueAction.CONTINUE),
    ],
)
async def test_unmatched_natural_action_preserves_pending_card(message, action):
    result = await ContextResolver().resolve(message, _context())

    assert result.dialogue_action is action
    assert result.consume_interaction is False


@pytest.mark.parametrize(
    ("message", "action"),
    [
        ("排查为什么订单表昨天少了数据", DialogueAction.NEW_GOAL),
        ("查询为什么这个节点失败", DialogueAction.NEW_GOAL),
        ("不要取消这个任务，继续执行", DialogueAction.CONTINUE),
    ],
)
async def test_business_goal_is_not_intercepted_by_cancel_or_explain(message, action):
    result = await ContextResolver().resolve(message, _context(False))

    assert result.dialogue_action is action


@pytest.mark.parametrize("message", ["第二个", "订单汇总表", "dw.dws_order_summary"])
async def test_stale_context_version_rejects_natural_option_answer(message):
    context = _context()
    context["state_version"] = 5

    result = await ContextResolver().resolve(message, context)

    assert result.dialogue_action is DialogueAction.CLARIFY
    assert result.interaction_answer is None


async def test_table_reference_only_includes_selected_table():
    context = _context(False)
    context["selected_resources"] = {
        "table": "dw.dws_order_summary",
        "node": "node_123456789",
        "task": "task_987654321",
    }

    result = await ContextResolver().resolve("用那张表继续", context)

    assert result.dialogue_action is DialogueAction.REFER
    assert result.context_updates == {"selected_resources": {"table": "dw.dws_order_summary"}}
    assert result.resolved_references == ["dw.dws_order_summary"]
    assert "dw.dws_order_summary" in result.rewritten_message
    assert "node_123456789" not in result.rewritten_message
    assert "task_987654321" not in result.rewritten_message


class RaisingFallback:
    async def classify(self, message, context):
        raise RuntimeError("classifier unavailable")


async def test_fallback_exception_safely_requires_clarification():
    result = await ContextResolver(RaisingFallback()).resolve("再弄一下", _context(False))

    assert result.dialogue_action is DialogueAction.CLARIFY
    assert result.interaction_answer is None


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_resolved_turn_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValidationError):
        ResolvedTurn(
            dialogue_action=DialogueAction.CLARIFY,
            rewritten_message="需要澄清",
            confidence=confidence,
        )


class StubClassifier:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error

    async def classify(self, message):
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    "result",
    [
        type(
            "Result", (), {"action": "ask_data", "params": ["not", "a", "dict"], "confidence": 0.9}
        )(),
        type("Result", (), {"action": "unknown", "params": {}, "confidence": 0.9})(),
    ],
)
async def test_llm_fallback_rejects_invalid_or_unknown_results(result):
    fallback = LLMDialogueFallback(StubClassifier(result=result))

    assert await fallback.classify("查询订单", _context(False)) is None


async def test_llm_fallback_exception_returns_none():
    fallback = LLMDialogueFallback(StubClassifier(error=RuntimeError("offline")))

    assert await fallback.classify("查询订单", _context(False)) is None
