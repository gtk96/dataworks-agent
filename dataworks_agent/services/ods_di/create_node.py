"""Phase 3–4: build DI config and create/configure DataWorks DI node."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from dataworks_agent.config import settings
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    generate_cron,
    get_cycle_type,
)
from dataworks_agent.services.ods_di.constants import DI_DEFAULT_DEPENDENCIES
from dataworks_agent.services.ods_di.di_config import build_di_task_config

logger = logging.getLogger(__name__)


def build_config(
    *,
    datasource_name: str,
    source_table: str,
    target_table: str,
    columns: list[str],
    granularity: str,
    split_pk: str,
    where_field: str,
    where_type: str,
    source_step_type: str,
    odps_datasource_name: str | None = None,
    schedule_minute: int = 0,
    resource_group: str = "",
    task_role: Literal["init", "incremental"] = "incremental",
    init_partition_date: str = "20170101",
    init_partition_hour: str = "00",
) -> dict[str, Any]:
    """Phase 3: build DI config + schedule metadata."""
    odps_ds = odps_datasource_name or settings.odps_datasource_name
    di_config = build_di_task_config(
        datasource_name=datasource_name,
        source_table_name=source_table,
        ods_table_name=target_table,
        columns=columns,
        odps_datasource_name=odps_ds,
        granularity=granularity,
        split_pk=split_pk,
        where_type=where_type,
        where_field=where_field,
        source_step_type=source_step_type,
        task_role=task_role,
        init_partition_date=init_partition_date,
        init_partition_hour=init_partition_hour,
    )
    if resource_group:
        di_config.setdefault("extend", {})["resourceGroup"] = resource_group

    if task_role == "init":
        return {
            "di_config": di_config,
            "cron": "",
            "cycle_type": "",
            "parameters": [],
            "scheduled": False,
        }

    cycle_type = get_cycle_type(granularity)  # type: ignore[arg-type]
    parameters = HOURLY_SQL_PARAMETERS if cycle_type == "NotDaily" else DAILY_SQL_PARAMETERS
    cron = generate_cron(
        granularity,  # type: ignore[arg-type]
        hour=3 if cycle_type == "Daily" else 0,
        minute=schedule_minute,
    )
    return {
        "di_config": di_config,
        "cron": cron,
        "cycle_type": cycle_type,
        "parameters": parameters,
        "scheduled": True,
    }


async def create_di_node(
    client: Any,
    *,
    node_name: str,
    node_path: str,
    di_config: dict[str, Any],
    cron: str = "",
    cycle_type: str = "NotDaily",
    parameters: list[dict[str, Any]] | None = None,
    schedule: bool = True,
) -> dict[str, Any]:
    """Phase 4: create DI node, write config, optional schedule + self-dependency.

    双路径（迁移期）：适配器(AK/SK, 无 `_post`) 走 create_node(language="di")；
    bff(有 `_post`) 走 ide/createPackage。DI 节点 = FlowSpec runtime=DI + DataX content
    （见 CLAUDE.md §7.7）。
    """
    script_content = json.dumps(di_config, ensure_ascii=False)
    use_bff = hasattr(client, "_post")  # bff 有私有 _post；OpenAPINodeAdapter 没有

    if use_bff:
        payload = {
            "projectId": client.project_id,
            "kind": "Node",
            "scene": "DATAWORKS_PROJECT",
            "name": node_name,
            "script": {
                "path": node_path,
                "runtime": {"command": "DI"},
                "content": script_content,
            },
        }
        resp = await client._post("ide/createPackage", payload)
        data = resp.get("data", {}) or {}
        node_uuid = data.get("uuid") if isinstance(data, dict) else None
    else:
        node_uuid = await client.create_node(node_name, node_path, language="di")

    if not node_uuid:
        err = getattr(client, "last_error", None) or "createPackage 返回空"
        return {"status": "failed", "error": err, "path": node_path}

    node_uuid = str(node_uuid)
    await client.update_node(node_uuid, script_content)

    if schedule and cron:
        vertex_config: dict[str, Any] = {
            "trigger": {
                "type": "Scheduler",
                "cron": cron,
                "cycleType": cycle_type,
                "startTime": "1970-01-01 00:00:00",
                "endTime": "9999-01-01 00:00:00",
                "timezone": "Asia/Shanghai",
            },
            "script": {"parameters": parameters or []},
            "strategy": {"instanceMode": "Immediately"},
        }
        if use_bff:
            await client.update_vertex(node_uuid, vertex_config)
            await client._put(
                "ide/addNodeDependencies",
                {
                    "projectId": client.project_id,
                    "uuid": node_uuid,
                    "dependencies": DI_DEFAULT_DEPENDENCIES,
                },
            )
        else:
            vertex_config["dependencies"] = DI_DEFAULT_DEPENDENCIES
            await client.update_vertex(node_uuid, vertex_config)

    return {"status": "created", "uuid": node_uuid, "path": node_path, "name": node_name}
