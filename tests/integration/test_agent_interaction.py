"""Structured Agent interaction integration coverage."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionExpiredError,
    PendingInteraction,
    build_interaction,
    resolve_interaction_answer,
)


def test_build_interaction_from_table_option_chips() -> None:
    pending = build_interaction(
        {
            "option_chips": [
                {
                    "type": "pick_table",
                    "id": "opt_0",
                    "label": "giikin_aliyun.tb_dwd_order",
                    "value": "giikin_aliyun.tb_dwd_order",
                    "layer": "dwd",
                },
                {
                    "type": "free_text",
                    "id": "opt_custom",
                    "label": "输入其它",
                    "placeholder": "project.table",
                },
            ],
            "clarifying_questions": ["请选择目标表"],
        },
        purpose="select_table",
        state_version=1,
    )

    assert pending is not None
    assert pending.prompt == "请选择目标表"
    assert pending.allow_custom_input is True
    assert pending.custom_input_placeholder == "project.table"
    assert pending.options[0].value == "giikin_aliyun.tb_dwd_order"
    assert pending.options[0].payload == {
        "params": {"table_name": "giikin_aliyun.tb_dwd_order"},
        "selected_resources": {"table": "giikin_aliyun.tb_dwd_order"},
    }


def test_build_interaction_from_next_actions() -> None:
    pending = build_interaction(
        {
            "next_actions": [
                {
                    "id": "dwd",
                    "label": "DWD",
                    "value": "dwd",
                    "payload": {"params": {"layer": "dwd"}},
                }
            ],
            "allow_custom_input": True,
            "custom_input_hint": "继续描述筛选条件",
        },
        purpose="select_layer",
        state_version=2,
    )

    assert pending is not None
    assert pending.options[0].id == "dwd"
    assert pending.options[0].payload == {"params": {"layer": "dwd"}}


def test_resolve_answer_uses_server_option_payload() -> None:
    pending = build_interaction(
        {
            "next_actions": [
                {
                    "id": "dwd",
                    "label": "DWD",
                    "payload": {"params": {"layer": "dwd"}},
                }
            ]
        },
        purpose="select_layer",
        state_version=2,
    )
    assert pending is not None

    result = resolve_interaction_answer(
        pending,
        InteractionAnswer(
            interaction_id=pending.interaction_id,
            option_id="dwd",
            state_version=2,
        ),
    )

    assert result == {"params": {"layer": "dwd"}}


def test_resolve_custom_answer() -> None:
    pending = PendingInteraction(
        interaction_id="int_1",
        type="free_text",
        purpose="select_table",
        prompt="请继续描述",
        allow_custom_input=True,
        state_version=4,
    )

    result = resolve_interaction_answer(
        pending,
        InteractionAnswer(
            interaction_id="int_1",
            custom_text="只要包含退款金额字段的 DWD 表",
            state_version=4,
        ),
    )

    assert result == {"custom_text": "只要包含退款金额字段的 DWD 表"}


def test_expired_interaction_is_rejected() -> None:
    pending = PendingInteraction(
        interaction_id="int_current",
        type="single_select",
        purpose="select_layer",
        prompt="请选择层级",
        state_version=5,
    )

    with pytest.raises(InteractionExpiredError):
        resolve_interaction_answer(
            pending,
            InteractionAnswer(
                interaction_id="int_old",
                custom_text="DWD",
                state_version=4,
            ),
        )


def test_answer_requires_exactly_one_answer_mode() -> None:
    with pytest.raises(ValidationError):
        InteractionAnswer(interaction_id="int_1", state_version=1)

    with pytest.raises(ValidationError):
        InteractionAnswer(
            interaction_id="int_1",
            option_id="opt_1",
            custom_text="other",
            state_version=1,
        )
