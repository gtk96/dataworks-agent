"""Hologres ODS node pipeline used by conversational workflows."""

from __future__ import annotations

from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import generate_cron, get_cycle_type
from dataworks_agent.services.ods_holo.column_resolver import load_holo_ods_columns
from dataworks_agent.services.ods_holo.dml_generator import (
    OdsMetadataMissingError,
    build_holo_ods_dml,
)
from dataworks_agent.services.ods_holo.ensure_table import ensure_holo_table


class HoloOdsPipeline:
    """Build a MaxCompute ODS table and a DataWorks HOLOGRES_SQL draft node."""

    def __init__(
        self,
        bff_client: Any,
        mcp_pool: Any,
        *,
        node_client: Any,
        mc_client: Any,
    ) -> None:
        self._bff = bff_client
        self._mcp = mcp_pool
        self._nodes = node_client
        self._mc = mc_client

    async def run(
        self,
        *,
        holo_schema: str,
        source_table: str,
        target_table: str,
        granularity: str = "hour",
        script_path: str = settings.holo_ods_node_path,
        schedule_minute: int = 1,
        where_mode: str = "auto",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": True,
            "target_table": target_table,
            "steps": {},
        }
        resolved = await load_holo_ods_columns(
            self._bff, self._mcp, holo_schema, source_table, granularity
        )
        source_columns = resolved.get("source_columns") or []
        ensure_result = await ensure_holo_table(
            self._bff,
            self._mcp,
            holo_schema=holo_schema,
            source_table=source_table,
            target_table=target_table,
            granularity=granularity,
            source_columns=source_columns,
            mc=self._mc,
        )
        result["steps"]["ensure_table"] = ensure_result
        if ensure_result.get("status") == "failed":
            result["success"] = False
            return result

        try:
            built = await build_holo_ods_dml(
                self._bff,
                self._mcp,
                holo_schema=holo_schema,
                source_table=source_table,
                target_table=target_table,
                granularity=granularity,
                where_mode=where_mode,
            )
        except OdsMetadataMissingError as exc:
            result["success"] = False
            result["steps"]["build_dml"] = {"status": "failed", "error": str(exc)}
            return result

        dml = built["dml"]
        parameters = built.get("parameters") or []
        node_path = generate_node_path(script_path, target_table)
        existing_uuid = await self._nodes.get_node_uuid_by_path(node_path)
        node_uuid = existing_uuid or await self._nodes.create_node(
            target_table, node_path, language="holo"
        )
        if not node_uuid:
            result["success"] = False
            result["steps"]["create_node"] = {
                "status": "failed",
                "error": getattr(self._nodes, "last_error", "create_node failed"),
            }
            return result
        if not await self._nodes.update_node(node_uuid, dml):
            result["success"] = False
            result["steps"]["create_node"] = {"status": "failed", "error": "update_node failed"}
            return result

        schedule_granularity = "hour" if granularity == "min" else granularity
        cron = generate_cron(schedule_granularity, minute=schedule_minute)
        cycle_type = get_cycle_type(schedule_granularity)
        scheduled = await self._nodes.update_vertex(
            node_uuid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": cron,
                    "cycleType": cycle_type,
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": parameters},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
            },
        )
        result["steps"]["create_node"] = {
            "status": "ok" if scheduled else "failed",
            "uuid": node_uuid,
            "path": node_path,
        }
        result["steps"]["configure_schedule"] = {
            "status": "ok" if scheduled else "failed",
            "cron": cron,
        }
        result.update(
            {
                "success": bool(scheduled),
                "node_uuid": node_uuid,
                "node_path": node_path,
                "sql": dml,
                "publish": "saved_not_deployed",
            }
        )
        return result
