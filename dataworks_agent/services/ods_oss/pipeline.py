"""ODS OSS import pipeline orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    auto_distribute,
    generate_cron,
    get_cycle_type,
)
from dataworks_agent.services.ods_di.constants import DI_DEFAULT_DEPENDENCIES
from dataworks_agent.services.ods_oss.config import (
    OSS_DEFAULT_DEPENDENCIES,
    OSS_NODE_PATH_PREFIX,
    build_oss_import_sql,
    validate_oss_config,
)

logger = logging.getLogger(__name__)


class OssImportPipeline:
    """OSS → ODS: validate → SQL → node → schedule → publish."""

    def __init__(self, bff_client: Any) -> None:
        self.bff = bff_client

    async def run(
        self,
        *,
        oss_path: str,
        target_table: str,
        file_format: str = "csv",
        wildcard: str = "",
        schedule_type: str = "day",
        node_path_prefix: str = OSS_NODE_PATH_PREFIX,
        schedule_minute: int | None = None,
        task_index: int = 0,
        total_tasks: int = 1,
        publish: bool = True,
        ingestion_mode: str = "structured",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"target_table": target_table, "success": True, "steps": {}}

        errors = validate_oss_config(oss_path, target_table, file_format)
        if errors:
            result["success"] = False
            result["steps"]["validate"] = {"status": "failed", "errors": errors}
            return result
        result["steps"]["validate"] = {"status": "ok"}

        sql = build_oss_import_sql(
            target_table=target_table,
            oss_path=oss_path,
            file_format=file_format,
            wildcard=wildcard,
            schedule_type=schedule_type,
            raw_json_text=ingestion_mode == "raw_json_text",
        )
        result["steps"]["build_sql"] = {"status": "ok", "sql_length": len(sql)}

        node_path = generate_node_path(node_path_prefix, target_table)
        node_uuid = await self.bff.create_node(target_table, node_path, language="odps-sql")
        if not node_uuid:
            result["success"] = False
            result["steps"]["create_node"] = {
                "status": "failed",
                "error": self.bff.last_error or "create_node failed",
            }
            return result
        if not await self.bff.update_node(node_uuid, sql):
            result["success"] = False
            result["steps"]["create_node"] = {"status": "failed", "error": "update_node failed"}
            return result
        result["steps"]["create_node"] = {"status": "ok", "uuid": node_uuid, "path": node_path}

        cycle_type = get_cycle_type("hour" if schedule_type in ("hour", "hourly") else "day")  # type: ignore[arg-type]
        if schedule_minute is None:
            slot = auto_distribute(
                task_index, total_tasks, "hour" if cycle_type == "NotDaily" else "day"
            )  # type: ignore[arg-type]
            minute = slot["minute"]
            hour = slot.get("hour", 0)
        else:
            minute = schedule_minute
            hour = 0 if cycle_type == "NotDaily" else 3
        cron = generate_cron(
            "hour" if cycle_type == "NotDaily" else "day",  # type: ignore[arg-type]
            hour=hour,
            minute=minute,
        )
        parameters = HOURLY_SQL_PARAMETERS if cycle_type == "NotDaily" else DAILY_SQL_PARAMETERS
        scheduled = await self.bff.update_vertex(
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
                "dependencies": OSS_DEFAULT_DEPENDENCIES or DI_DEFAULT_DEPENDENCIES,
            },
        )
        result["steps"]["configure_schedule"] = {
            "status": "ok" if scheduled else "failed",
            "cron": cron,
        }
        if not scheduled:
            result["success"] = False
            return result

        if publish:
            deployed = await self.bff.deploy_nodes(
                [node_uuid], comment=f"oss import {target_table}"
            )
            result["steps"]["publish"] = {"status": "ok" if deployed else "failed"}
            if not deployed:
                result["success"] = False
        else:
            result["steps"]["publish"] = {"status": "skipped"}

        result["sql"] = sql
        result["node_uuid"] = node_uuid
        return result
