"""ODS Realtime sync pipeline orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS
from dataworks_agent.services.ods_di.constants import DI_DEFAULT_DEPENDENCIES
from dataworks_agent.services.ods_realtime.helpers import (
    REALTIME_DEFAULT_DEPENDENCIES,
    REALTIME_NODE_PATH_PREFIX,
    extract_fields_from_select_dml,
    generate_insert_sql,
    preprocess_realtime_task,
)

logger = logging.getLogger(__name__)


class RealtimeSyncPipeline:
    """Realtime ODS: preprocess → SQL → node → schedule → publish."""

    def __init__(self, bff_client: Any) -> None:
        self.bff = bff_client

    async def run(
        self,
        *,
        database_schema: str,
        table_name: str,
        sync_rows: list[dict[str, Any]],
        select_dml: str | None = None,
        target_table: str | None = None,
        granularity: str = "hour",
        node_path_prefix: str = REALTIME_NODE_PATH_PREFIX,
        schedule_minute: int = 0,
        mc_project: str | None = None,
        source_project: str | None = None,
        publish: bool = True,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"success": True, "steps": {}}

        prep = preprocess_realtime_task(
            database_schema=database_schema,
            table_name=table_name,
            sync_rows=sync_rows,
            granularity=granularity,
            node_path_prefix=node_path_prefix,
            schedule_minute=schedule_minute,
        )
        result["steps"]["preprocess"] = prep
        if not prep.get("success"):
            result["success"] = False
            return result

        ods_table = target_table or prep["ods_table_name"]
        delta_table = prep["delta_table"]
        node_path = (
            prep["node_path"]
            if target_table is None
            else generate_node_path(node_path_prefix, target_table)
        )
        result["target_table"] = ods_table

        fields = extract_fields_from_select_dml(select_dml)
        if not fields:
            result["success"] = False
            result["steps"]["extract_fields"] = {
                "status": "failed",
                "error": "无法从 SELECT DML 提取字段",
            }
            return result
        result["steps"]["extract_fields"] = {"status": "ok", "field_count": len(fields)}

        prod = mc_project or settings.dataworks_prod_schema
        dev = source_project or settings.dataworks_dev_schema
        sql = generate_insert_sql(ods_table, delta_table, fields, prod, dev)
        result["steps"]["build_sql"] = {"status": "ok", "sql_length": len(sql)}

        node_uuid = await self.bff.create_node(ods_table, node_path, language="odps-sql")
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

        scheduled = await self.bff.update_vertex(
            node_uuid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": prep["cron_expr"],
                    "cycleType": prep["cycle_type"],
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": HOURLY_SQL_PARAMETERS},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": REALTIME_DEFAULT_DEPENDENCIES or DI_DEFAULT_DEPENDENCIES,
            },
        )
        result["steps"]["configure_schedule"] = {
            "status": "ok" if scheduled else "failed",
            "cron": prep["cron_expr"],
        }
        if not scheduled:
            result["success"] = False
            return result

        if publish:
            deployed = await self.bff.deploy_nodes([node_uuid], comment=f"realtime {ods_table}")
            result["steps"]["publish"] = {"status": "ok" if deployed else "failed"}
            if not deployed:
                result["success"] = False
        else:
            result["steps"]["publish"] = {"status": "skipped"}

        result["sql"] = sql
        result["node_uuid"] = node_uuid
        return result
