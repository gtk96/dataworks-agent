"""Read-only table discovery tool for the conversational Agent runtime."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from uuid import uuid4

from dataworks_agent.agent.context.metadata_provider import MetadataProvider
from dataworks_agent.agent.interaction import InteractionOption, PendingInteraction
from dataworks_agent.agent.tools.base import SideEffect, ToolContext, ToolResult


class TableDiscoveryTool:
    name = "find_table"
    side_effect = SideEffect.READ

    def __init__(self, provider: MetadataProvider | None = None) -> None:
        self._provider = provider or MetadataProvider()

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raw_keyword = str(arguments.get("keyword") or "").strip()
        keyword = self._normalize_keyword(raw_keyword)
        state_version = int(context.state.get("state_version") or 0) + 1
        if not keyword:
            return self._clarification(
                "请告诉我想找哪类数据表，例如“订单”“退款”或完整英文表名。",
                state_version,
                error_code="table_keyword_required",
            )

        layer = str(arguments.get("layer") or "").strip().lower()
        result = await self._provider.search_table(keyword, raw_keyword or keyword)
        candidates = list(result.candidates if result is not None else [])
        if layer:
            candidates = [item for item in candidates if self._layer(item) == layer]
        if not candidates:
            return self._clarification(
                f"没有找到“{keyword}”对应的可靠表候选。你可以补充业务域、分层或英文表名。",
                state_version,
                error_code="table_not_found",
            )
        if len(candidates) > 8 and not layer:
            return ToolResult.ok(
                f"找到 {len(candidates)} 张候选表，请先选择数据层。",
                data={
                    "keyword": keyword,
                    "interaction": self._layer_interaction(candidates, keyword, state_version),
                },
            )
        return ToolResult.ok(
            f"找到 {len(candidates[:8])} 张“{keyword}”候选表，请选择目标表。",
            data={
                "keyword": keyword,
                "candidates": candidates[:8],
                "interaction": self._table_interaction(candidates[:8], keyword, state_version),
            },
        )

    @staticmethod
    def _normalize_keyword(value: str) -> str:
        text = re.sub(r"^(?:请帮我|帮我|我想|我要|想要)", "", value.strip())
        text = re.sub(r"^(?:查找|搜索|查询|查看|找)", "", text).strip()
        text = re.sub(r"(?:相关的?)?(?:数据)?表$", "", text).strip()
        return "" if text in {"", "数据", "数据表", "表"} else text

    @staticmethod
    def _layer(item: dict[str, Any]) -> str:
        return str(item.get("layer") or "other").strip().lower() or "other"

    def _layer_interaction(
        self,
        candidates: list[dict[str, Any]],
        keyword: str,
        state_version: int,
    ) -> dict[str, Any]:
        counts = Counter(self._layer(item) for item in candidates)
        options = [
            InteractionOption(
                id=f"layer_{layer}",
                label=f"{layer.upper()}（{count}）",
                value=layer,
                description=f"只查看 {layer.upper()} 层候选",
                layer=layer,
                payload={
                    "params": {
                        "keyword": keyword,
                        "layer": layer,
                        "tool_name": self.name,
                    }
                },
            )
            for layer, count in counts.items()
        ]
        return PendingInteraction(
            interaction_id=f"int_{uuid4().hex[:12]}",
            purpose="select_layer",
            prompt=f"“{keyword}”候选较多，请先选择数据层。",
            options=options,
            custom_input_placeholder="也可以输入更具体的业务描述",
            state_version=state_version,
        ).model_dump()

    def _table_interaction(
        self,
        candidates: list[dict[str, Any]],
        keyword: str,
        state_version: int,
    ) -> dict[str, Any]:
        options: list[InteractionOption] = []
        for index, item in enumerate(candidates):
            full_name = str(item.get("full_name") or "").strip()
            if not full_name:
                continue
            layer = self._layer(item)
            comment = str(item.get("comment") or "").strip()
            options.append(
                InteractionOption(
                    id=f"table_{index + 1}",
                    label=comment or full_name,
                    value=full_name,
                    description=f"{full_name} · {layer.upper()}",
                    layer=layer,
                    payload={
                        "params": {"table_name": full_name},
                        "selected_resources": {"table": full_name},
                    },
                )
            )
        return PendingInteraction(
            interaction_id=f"int_{uuid4().hex[:12]}",
            purpose="select_table",
            prompt=f"请选择“{keyword}”对应的目标表。",
            options=options,
            custom_input_placeholder="输入其他关键词或完整 project.table",
            state_version=state_version,
        ).model_dump()

    @staticmethod
    def _clarification(message: str, state_version: int, *, error_code: str) -> ToolResult:
        interaction = PendingInteraction(
            interaction_id=f"int_{uuid4().hex[:12]}",
            type="free_text",
            purpose="refine_table_search",
            prompt=message,
            options=[],
            custom_input_placeholder="例如：订单 DWD 表，或 project.table",
            state_version=state_version,
        )
        return ToolResult.failure(
            message,
            error_code=error_code,
            data={"interaction": interaction.model_dump()},
        )
