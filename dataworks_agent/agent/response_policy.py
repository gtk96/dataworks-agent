"""Central response shaping for continuous Agent conversations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from dataworks_agent.agent.interaction import build_interaction


class ConversationMeta(BaseModel):
    """Stable conversation metadata returned alongside Agent responses."""

    conversation_id: str = ""
    active_goal: str = ""
    action: str = ""
    status: str = "idle"
    state_version: int = 0
    selected_resources: dict[str, Any] = Field(default_factory=dict)


ENTRY_OPTIONS = [
    {
        "id": "ask_data",
        "type": "action",
        "label": "智能问数",
        "value": "我想进行智能问数",
        "description": "查询已确认口径的数据",
    },
    {
        "id": "find_table",
        "type": "action",
        "label": "查找数据表",
        "value": "我想查找数据表",
        "description": "搜索现有数据资产",
    },
    {
        "id": "modeling",
        "type": "action",
        "label": "数仓建模",
        "value": "我想进行数仓建模",
        "description": "生成可审计的建模方案",
    },
    {
        "id": "diagnose",
        "type": "action",
        "label": "异常排查",
        "value": "我想排查任务异常",
        "description": "诊断节点和依赖状态",
    },
]


class ResponsePolicy:
    """Build consistent text-plus-card responses without mutating workflow data."""

    def greeting(self, context: dict[str, Any], *, state_version: int) -> dict[str, Any]:
        pending = deepcopy(context.get("pending_interaction") or {})
        if pending:
            return {"interaction": pending}
        return self._build_entry_interaction("你想先做哪件事？", "choose_entry", state_version)

    def explain(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        pending = deepcopy(context.get("pending_interaction") or {})
        descriptions = [
            f"{item.get('label')}：{item.get('description')}"
            for item in pending.get("options") or []
            if isinstance(item, dict) and item.get("description")
        ]
        if descriptions:
            message = "；".join(descriptions)
        else:
            previous = str((context.get("last_assistant_turn") or {}).get("content") or "").strip()
            message = (
                f"上一条的意思是：{previous}"
                if previous
                else "我目前没有可解释的上一条内容，请补充你想了解的内容。"
            )
        return message, {"interaction": pending or None}

    def clarify(self, *, state_version: int) -> dict[str, Any]:
        return self._build_entry_interaction(
            "我还不能确定你指的是哪一步，请选择或补充说明。",
            "clarify_request",
            state_version,
        )

    def normalize_workflow_data(
        self,
        data: dict[str, Any],
        *,
        purpose: str,
        state_version: int,
    ) -> dict[str, Any]:
        normalized = deepcopy(data)
        raw_options = normalized.get("option_chips") or normalized.get("next_actions") or []
        option_chips: list[dict[str, Any]] = []
        for index, item in enumerate(raw_options):
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("value") or "").strip()
                is_custom_input = bool(
                    item.get("type") == "free_text" or item.get("requires_custom_input")
                )
                if label or is_custom_input:
                    option_chips.append(deepcopy(item))
                continue
            if item is None:
                continue
            label = str(item).strip()
            if not label:
                continue
            option_chips.append(
                {
                    "id": f"action_{index}",
                    "type": "action",
                    "label": label,
                    "value": label,
                    "payload": {"value": label},
                }
            )

        normalized["option_chips"] = option_chips
        if isinstance(normalized.get("interaction"), dict) or option_chips:
            interaction = build_interaction(
                normalized,
                purpose=purpose,
                state_version=state_version,
            )
            normalized["interaction"] = interaction.model_dump() if interaction else None
        else:
            normalized["interaction"] = None
        return normalized

    def _build_entry_interaction(
        self,
        prompt: str,
        purpose: str,
        state_version: int,
    ) -> dict[str, Any]:
        data = {
            "interaction_prompt": prompt,
            "interaction_purpose": purpose,
            "option_chips": deepcopy(ENTRY_OPTIONS),
            "allow_custom_input": True,
            "custom_input_hint": "也可以直接描述你的目标",
        }
        interaction = build_interaction(data, purpose=purpose, state_version=state_version)
        return {"interaction": interaction.model_dump() if interaction else None}

    def conversation_meta(self, conversation_id: str, context: dict[str, Any]) -> dict[str, Any]:
        return ConversationMeta(
            conversation_id=conversation_id,
            active_goal=str(context.get("objective") or ""),
            action=str(context.get("action") or ""),
            status=str(context.get("task_status") or "idle"),
            state_version=int(context.get("state_version") or 0),
            selected_resources=deepcopy(context.get("selected_resources") or {}),
        ).model_dump()
