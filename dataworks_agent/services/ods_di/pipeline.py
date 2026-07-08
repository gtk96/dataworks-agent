"""ODS DI four-phase pipeline orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.naming import generate_node_path, generate_ods_di_table_name
from dataworks_agent.services.ods_di.create_node import build_config, create_di_node
from dataworks_agent.services.ods_di.ensure_table import ensure_table
from dataworks_agent.services.ods_di.field_infer import infer_fields
from dataworks_agent.services.ods_di.init_workflow import (
    InitializationConfig,
    run_with_initialization,
)

logger = logging.getLogger(__name__)


class DIPipeline:
    """ODS 数据集成管道 — 字段推断 → 建表 → 生成配置 → 创建节点。"""

    def __init__(
        self,
        bff_client: Any,
        mcp_pool: Any = None,
        node_client: Any = None,
        mc_client: Any = None,
    ) -> None:
        self.bff = bff_client
        self.mcp = mcp_pool
        # 建 DI 节点走 AK/SK 适配器、建表走 AK/SK MaxCompute；字段推断/数据源仍走 bff（其独有能力）
        self._nodes = node_client or bff_client
        self._mc = mc_client

    async def run(
        self,
        datasource_name: str,
        source_table: str,
        target_table: str | None = None,
        granularity: str = "hour",
        script_path: str = "dataworks_agent/01_ODS",
        schedule_minute: int = 1,
        resource_group: str = "",
        source_type: str | None = "hologres",
        mc_project: str | None = None,
        with_initialization: bool = False,
        init_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute DI pipeline. Set with_initialization=True for init+incremental flow."""
        if with_initialization:
            cfg = InitializationConfig(**(init_config or {}))
            return await run_with_initialization(
                self.bff,
                self.mcp,
                datasource_name=datasource_name,
                source_table=source_table,
                granularity=granularity,
                script_path=script_path,
                schedule_minute=schedule_minute,
                resource_group=resource_group,
                source_type=source_type,
                target_table=target_table,
                init_config=cfg,
            )

        ods_table = target_table or generate_ods_di_table_name(
            datasource_name,
            source_table,
            granularity,
            source_type=source_type,
        )
        node_path = generate_node_path(script_path, ods_table)
        project = mc_project or settings.dataworks_dev_schema
        rg = resource_group or settings.dataworks_resource_group

        result: dict[str, Any] = {"steps": {}, "success": True, "target_table": ods_table}

        field_step = await infer_fields(
            self.bff, self.mcp, datasource_name, source_table, granularity
        )
        result["steps"]["field_infer"] = field_step
        if field_step.get("status") != "ok":
            result["success"] = False
            return result

        table_step = await ensure_table(
            self.bff,
            self.mcp,
            datasource_name=datasource_name,
            source_table_name=source_table,
            target_table=ods_table,
            granularity=granularity,
            mc_project=project,
            mc=self._mc,
        )
        result["steps"]["ensure_table"] = table_step
        if table_step.get("status") not in {"exists", "created"}:
            result["success"] = False
            return result

        config_step = build_config(
            datasource_name=datasource_name,
            source_table=source_table,
            target_table=ods_table,
            columns=field_step["columns"],
            granularity=granularity,
            split_pk=field_step.get("split_pk", ""),
            where_field=field_step.get("where_field", ""),
            where_type=field_step.get("where_type", "none"),
            source_step_type=field_step.get("source_step_type", "mysql"),
            schedule_minute=schedule_minute,
            resource_group=rg,
        )
        result["steps"]["build_config"] = {
            "status": "ok",
            "cron": config_step["cron"],
            "cycle_type": config_step["cycle_type"],
        }

        node_step = await create_di_node(
            self._nodes,
            node_name=ods_table,
            node_path=node_path,
            di_config=config_step["di_config"],
            cron=config_step["cron"],
            cycle_type=config_step["cycle_type"],
            parameters=config_step["parameters"],
            schedule=True,
        )
        result["steps"]["create_node"] = node_step
        if not node_step.get("uuid"):
            result["success"] = False

        return result
