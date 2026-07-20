"""Read-only table schema inspection for the conversational Agent runtime."""

from __future__ import annotations

from typing import Any

from dataworks_agent.agent.tools.base import SideEffect, ToolContext, ToolResult
from dataworks_agent.state import app_state


class TableInspectionTool:
    name = "inspect_table"
    side_effect = SideEffect.READ

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        table_name = str(
            arguments.get("table_name")
            or (context.state.get("selected_resources") or {}).get("table")
            or ""
        ).strip()
        if not table_name:
            return ToolResult.failure(
                "请先选择要查看字段的数据表。",
                error_code="table_required",
            )
        if self._provider is not None:
            columns = await self._provider.get_columns(table_name)
        else:
            maxcompute = getattr(app_state, "_maxcompute_client", None)
            if maxcompute is None:
                return ToolResult.failure(
                    "表结构读取通道当前不可用，你可以稍后重试或选择其他表。",
                    error_code="table_inspection_unavailable",
                )
            schema = await maxcompute.get_table_schema(table_name)
            columns = [
                {
                    "name": str(column.name),
                    "type": str(column.type),
                    "comment": str(getattr(column, "comment", "") or ""),
                }
                for column in schema.columns
            ]
        if not columns:
            return ToolResult.failure(
                f"没有读到 {table_name} 的字段信息。",
                error_code="columns_not_found",
            )
        return ToolResult.ok(
            f"已读取 {table_name} 的 {len(columns)} 个字段。",
            data={"table_name": table_name, "columns": list(columns)},
        )
