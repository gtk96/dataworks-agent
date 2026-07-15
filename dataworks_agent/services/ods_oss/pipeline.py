"""ODS OSS external-table pipeline orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    auto_distribute,
    generate_cron,
    get_cycle_type,
)
from dataworks_agent.services.ods_oss.config import (
    OSS_NODE_PATH_PREFIX,
    build_ods_extract_sql,
    parse_oss_path,
    validate_oss_config,
)
from dataworks_agent.services.ods_oss.external_table import (
    ExternalTableSpec,
    build_external_table_ddl,
    source_name_from_location,
)
from dataworks_agent.services.ods_oss.managed_discovery import discover_managed_oss_schema

logger = logging.getLogger(__name__)


class OssImportPipeline:
    """OSS external table → giikin ODS: validate → resolve → SQL → node → schedule."""

    def __init__(self, bff_client: Any) -> None:
        self.bff = bff_client

    async def _execute_ddl(self, sql: str) -> bool:
        execute = getattr(self.bff, "execute_sql_ida", None)
        if execute is None:
            return False
        job_code = await execute(sql)
        if not job_code:
            return False
        wait = getattr(self.bff, "wait_ida_job", None)
        if wait is None:
            return True
        return bool(await wait(job_code, max_retry=36, interval=5))

    async def _resolve_external_table(
        self,
        *,
        oss_path: str,
        file_format: str,
        ingestion_mode: str,
        source_partition_value: str | None,
    ) -> dict[str, Any]:
        location = parse_oss_path(oss_path)
        source_name = source_name_from_location(location)
        source_table = source_name
        source_project = "giikin_develop"
        managed = await discover_managed_oss_schema(
            self.bff,
            oss_path,
            file_format,
            include_registration=True,
        )
        if isinstance(managed, dict) and managed.get("success"):
            source_table = str(managed.get("table_name") or source_name).strip()
            source_project = str(managed.get("project") or source_project).strip()
            source_partition = str(
                (managed.get("partition_columns") or ["pt"])[0]
            ).strip()
            if not source_partition_value and managed.get("source_partition_value"):
                source_partition_value = str(managed["source_partition_value"])
            return {
                "status": "reused",
                "created": False,
                "project": source_project,
                "table_name": source_table,
                "source_partition": source_partition,
                "source_partition_value": source_partition_value,
                "metadata_source": managed.get("metadata_source", "dataworks_managed_datasource"),
                "columns": managed.get("columns") or [{"name": "json_data", "type": "STRING"}],
                "file_format": managed.get("file_format") or file_format,
                "location": managed.get("location") or location,
            }

        source_partition = "pt"
        if not source_partition_value:
            return {
                "status": "needs_context",
                "created": False,
                "error": "source_partition_value is required to resolve a partitioned external table",
            }
        columns = (("json_data", "STRING"),)
        external_spec = ExternalTableSpec(
            project=source_project,
            table=source_table,
            columns=columns,
            partition_columns=(source_partition,),
            file_format="json" if ingestion_mode == "raw_json_text" else file_format,
            location=str(location["location_uri"]),
        )
        ddl = build_external_table_ddl(external_spec)
        created = await self._execute_ddl(ddl)
        if not created:
            return {
                "status": "failed",
                "created": False,
                "error": getattr(self.bff, "last_error", None) or "external table creation failed",
                "ddl": ddl,
            }
        return {
            "status": "created",
            "created": True,
            "project": source_project,
            "table_name": source_table,
            "source_partition": source_partition,
            "source_partition_value": source_partition_value,
            "metadata_source": "created_external_table",
            "columns": [{"name": "json_data", "type": "STRING"}],
            "file_format": external_spec.file_format,
            "location": location,
            "ddl": ddl,
        }

    async def run(
        self,
        *,
        oss_path: str,
        target_table: str,
        file_format: str = "json",
        wildcard: str = "",
        schedule_type: str = "day",
        node_path_prefix: str = OSS_NODE_PATH_PREFIX,
        schedule_minute: int | None = None,
        task_index: int = 0,
        total_tasks: int = 1,
        publish: bool = True,
        ingestion_mode: str = "structured",
        root_node_uuid: str | None = None,
        output_ref: str | None = None,
        source_partition_value: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"target_table": target_table, "success": True, "steps": {}}
        normalized_schedule = str(schedule_type or "").strip().lower()
        if normalized_schedule == "hourly":
            normalized_schedule = "hour"
        errors = validate_oss_config(oss_path, target_table, file_format)
        if normalized_schedule not in {"day", "hour"}:
            errors.append("schedule_type must be day or hour")
        if errors:
            result["success"] = False
            result["steps"]["validate"] = {"status": "failed", "errors": errors}
            return result
        result["steps"]["validate"] = {"status": "ok"}

        resolved_root_uuid = str(
            root_node_uuid
            or settings.dataworks_default_root_node_uuid
            or settings.root_check_node_uuid
            or ""
        ).strip()
        if not resolved_root_uuid:
            result["success"] = False
            result["steps"]["configure_dependencies"] = {
                "status": "needs_context",
                "error": "OSS ODS 节点需要根节点 UUID；请提供 root_node_uuid 或配置默认根节点。",
            }
            return result

        external = await self._resolve_external_table(
            oss_path=oss_path,
            file_format=file_format,
            ingestion_mode=ingestion_mode,
            source_partition_value=source_partition_value,
        )
        result["steps"]["resolve_external_table"] = external
        if external.get("status") in {"needs_context", "failed"}:
            result["success"] = False
            return result

        source_table = str(external["table_name"])
        source_project = str(external.get("project") or "giikin_develop")
        partition_value = external.get("source_partition_value")
        try:
            sql = build_ods_extract_sql(
                source_table=source_table,
                target_table=target_table,
                granularity=normalized_schedule,  # type: ignore[arg-type]
                source_partition_value=str(partition_value or ""),
                source_project=source_project,
                target_project="giikin",
                source_partition=str(external.get("source_partition") or "pt"),
            )
        except ValueError as exc:
            result["success"] = False
            result["steps"]["build_sql"] = {"status": "needs_context", "error": str(exc)}
            return result
        result["steps"]["build_sql"] = {"status": "ok", "sql_length": len(sql)}

        resolved_output_ref = str(output_ref or f"giikin.{target_table}").strip()
        dependencies = [
            {
                "type": "Normal",
                "sourceType": "System",
                "output": resolved_root_uuid,
                "refTableName": resolved_root_uuid,
            },
            {"type": "CrossCycleDependsOnSelf", "output": resolved_output_ref, "refTableName": resolved_output_ref},
        ]
        outputs = {
            "nodeOutputs": [
                {
                    "artifactType": "NodeOutput",
                    "sourceType": "System",
                    "data": resolved_output_ref,
                    "refTableName": resolved_output_ref,
                    "isDefault": True,
                }
            ]
        }
        node_path = generate_node_path(node_path_prefix, target_table)
        node_uuid = await self.bff.create_node(target_table, node_path, language="odps-sql")
        if not node_uuid:
            result["success"] = False
            result["steps"]["create_node"] = {"status": "failed", "error": self.bff.last_error or "create_node failed"}
            return result
        if not await self.bff.update_node(node_uuid, sql):
            result["success"] = False
            result["steps"]["create_node"] = {"status": "failed", "error": getattr(self.bff, "last_error", None) or "update_node failed", "uuid": node_uuid, "path": node_path}
            return result
        result["steps"]["create_node"] = {"status": "ok", "uuid": node_uuid, "path": node_path}

        cycle_type = get_cycle_type(normalized_schedule)  # type: ignore[arg-type]
        if schedule_minute is None:
            slot = auto_distribute(task_index, total_tasks, normalized_schedule)  # type: ignore[arg-type]
            minute, hour = slot["minute"], slot.get("hour", 0)
        else:
            minute, hour = schedule_minute, 0 if normalized_schedule == "hour" else 3
        cron = generate_cron(normalized_schedule, hour=hour, minute=minute)  # type: ignore[arg-type]
        parameters = HOURLY_SQL_PARAMETERS if normalized_schedule == "hour" else DAILY_SQL_PARAMETERS
        scheduled = await self.bff.update_vertex(
            node_uuid,
            {
                "trigger": {"type": "Scheduler", "cron": cron, "cycleType": cycle_type, "startTime": "1970-01-01 00:00:00", "endTime": "9999-01-01 00:00:00", "timezone": "Asia/Shanghai"},
                "script": {"parameters": parameters},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": dependencies,
                "outputs": outputs,
            },
        )
        result["steps"]["configure_schedule"] = {"status": "ok" if scheduled else "failed", "cron": cron}
        if not scheduled:
            result["success"] = False
            result["steps"]["configure_schedule"]["error"] = getattr(self.bff, "last_error", None) or "update_vertex failed"
            result["node_uuid"], result["node_path"] = node_uuid, node_path
            return result

        dependency_status = "inline"
        if hasattr(self.bff, "_put"):
            dependency_response = await self.bff._put("ide/addNodeDependencies", {"projectId": getattr(self.bff, "project_id", None), "uuid": node_uuid, "dependencies": dependencies})
            if dependency_response.get("code") != 200:
                result["success"] = False
                result["steps"]["configure_dependencies"] = {"status": "failed", "error": getattr(self.bff, "last_error", None) or "dependency configuration failed"}
                return result
            dependency_status = "cookie_bff"
        result["steps"]["configure_dependencies"] = {"status": "ok", "root_node_uuid": resolved_root_uuid, "dependency_status": dependency_status}
        if publish:
            deployed = await self.bff.deploy_nodes([node_uuid], comment=f"oss import {target_table}")
            result["steps"]["publish"] = {"status": "ok" if deployed else "failed"}
            if not deployed:
                result["success"] = False
        else:
            result["steps"]["publish"] = {"status": "skipped"}
        result.update({"sql": sql, "node_uuid": node_uuid, "node_path": node_path, "dependencies": dependencies, "outputs": outputs, "output_ref": resolved_output_ref, "root_node_uuid": resolved_root_uuid})
        return result
