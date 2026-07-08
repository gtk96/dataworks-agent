"""DWD six-step deploy pipeline (simplified, no PG queue)."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.modeling.dwd.ddl_generator import DwdDDLGenerator
from dataworks_agent.modeling.dwd.metadata import build_structured_metadata
from dataworks_agent.modeling.dwd.schemas import StructuredMetadata
from dataworks_agent.modeling.dwd.sql_generator import DwdSQLGenerator
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    DWD_SQL_PARAMETERS,
    generate_cron,
    infer_schedule_type,
)
from dataworks_agent.services.ods_di.di_config import (
    inject_schema_prefix_in_ddl,
    strip_leading_drop_table,
)

logger = logging.getLogger(__name__)


def _build_upstream_dependencies(
    metadata: StructuredMetadata, project: str
) -> list[dict[str, Any]]:
    """从 metadata 中提取上游表，构建 NodeOutput 依赖。

    DataWorks 依赖格式（与 flowspec.py 保持一致）:
    {
        "type": "Normal",
        "sourceType": "Manual",
        "output": "dataworks.ods_xxx",
        "refTableName": "dataworks.ods_xxx"
    }

    加上自依赖:
    {
        "type": "CrossCycleDependsOnSelf"
    }
    """
    dependencies: list[dict[str, Any]] = []

    # 收集所有上游表（主表 + JOIN 表）
    upstream_tables: set[str] = set()

    # 主表
    master_table = metadata.master_table.table_name
    # 提取纯表名（去掉 schema 前缀）
    master_pure = master_table.split(".")[-1] if "." in master_table else master_table
    upstream_tables.add(f"{project}.{master_pure}")

    # JOIN 表
    for join in metadata.joins:
        join_table = join.right_table_name
        join_pure = join_table.split(".")[-1] if "." in join_table else join_table
        upstream_tables.add(f"{project}.{join_pure}")

    # 构建依赖列表
    for table_ref in upstream_tables:
        dependencies.append(
            {
                "type": "Normal",
                "sourceType": "Manual",
                "output": table_ref,
                "refTableName": table_ref,
            }
        )

    # 添加自依赖
    dependencies.append(
        {
            "type": "CrossCycleDependsOnSelf",
        }
    )

    return dependencies


STEP_NAMES = [
    "generate_ddl",
    "execute_create_table",
    "generate_sql",
    "create_sql_node",
    "configure_schedule",
    "publish",
]

DWD_NODE_PATH_PREFIX = "dataworks_agent/02_DWD"


class DwdDeployPipeline:
    """End-to-end DWD deploy: DDL → 建表 → SQL → 节点 → 调度 → 发布。"""

    def __init__(
        self,
        bff_client: Any,
        *,
        node_client: Any = None,
        mc_client: Any = None,
    ) -> None:
        self.bff = bff_client
        # 节点操作走 AK/SK 适配器（缺则降级 bff）；建表 DDL 走 MaxCompute（缺则降级 bff IDA）
        self._nodes = node_client or bff_client
        self._mc = mc_client
        self.ddl_gen = DwdDDLGenerator()
        self.sql_gen = DwdSQLGenerator()

    def preview_ddl(self, structured_metadata: dict) -> str:
        ddl_meta = self.ddl_gen.from_structured_metadata(structured_metadata)
        return self.ddl_gen.generate(ddl_meta)

    def preview_sql(self, structured_metadata: dict) -> str:
        metadata = build_structured_metadata(structured_metadata)
        return self.sql_gen.generate(metadata)

    async def _create_table_mc(self, ddl_text: str, project: str, target_table: str) -> dict:
        """AK/SK MaxCompute 建表：先查存在性，不存在则执行 CREATE（剥离 DROP）。"""
        try:
            exists = await self._mc.table_exists(target_table, project=project)
        except Exception as exc:
            return {"status": "failed", "error": f"table_exists 失败: {exc}"}
        if exists:
            return {"status": "skipped", "reason": "table_exists"}
        create_ddl = strip_leading_drop_table(inject_schema_prefix_in_ddl(ddl_text, project))
        res = await self._mc.execute_ddl(create_ddl)
        if not res.success:
            return {"status": "failed", "error": res.error or "execute_ddl failed"}
        return {"status": "ok", "instance_id": res.instance_id}

    async def _create_table_bff(self, ddl_text: str, project: str, target_table: str) -> dict:
        """BFF IDA 建表（降级路径，行为与原实现保持一致）。"""
        table_guid = f"odps.{project}.{target_table}"
        existing_ddl = await self.bff.get_creation_ddl(table_guid)
        if existing_ddl:
            return {"status": "skipped", "reason": "table_exists"}
        ddl_exec = inject_schema_prefix_in_ddl(ddl_text, project)
        job_code = await self.bff.execute_sql_ida(ddl_exec)
        if not job_code:
            return {"status": "failed", "error": self.bff.last_error or "execute_sql_ida failed"}
        created = await self.bff.wait_ida_job(job_code, max_retry=36, interval=5)
        if not created:
            return {"status": "failed", "error": self.bff.last_error or "wait_ida_job failed"}
        return {"status": "ok", "job_code": job_code}

    async def deploy(
        self,
        structured_metadata: dict,
        *,
        node_path: str = DWD_NODE_PATH_PREFIX,
        node_name: str | None = None,
        mc_project: str | None = None,
        schedule_minute: int = 1,
        publish: bool = True,
    ) -> dict[str, Any]:
        """Run six-step deploy; returns step results."""
        project = mc_project or settings.dataworks_dev_schema
        metadata = build_structured_metadata(structured_metadata)
        target_table = metadata.target_table_name.split(".")[-1]
        node_name = node_name or target_table
        full_node_path = generate_node_path(node_path, node_name)

        result: dict[str, Any] = {
            "target_table": target_table,
            "node_path": full_node_path,
            "success": True,
            "steps": {},
        }

        # Step 1: generate DDL
        try:
            ddl_text = self.preview_ddl(structured_metadata)
            result["steps"]["generate_ddl"] = {"status": "ok", "ddl_length": len(ddl_text)}
        except Exception as exc:
            result["success"] = False
            result["steps"]["generate_ddl"] = {"status": "failed", "error": str(exc)}
            return result

        # Step 2: execute create table（AK/SK MaxCompute 优先，缺则降级 bff IDA）
        if self._mc is not None:
            create_step = await self._create_table_mc(ddl_text, project, target_table)
        else:
            create_step = await self._create_table_bff(ddl_text, project, target_table)
        result["steps"]["execute_create_table"] = create_step
        if create_step.get("status") == "failed":
            result["success"] = False
            return result

        # Step 3: generate SQL
        try:
            sql_text = self.sql_gen.generate(metadata)
            result["steps"]["generate_sql"] = {"status": "ok", "sql_length": len(sql_text)}
        except Exception as exc:
            result["success"] = False
            result["steps"]["generate_sql"] = {"status": "failed", "error": str(exc)}
            return result

        # Step 4: create SQL node
        node_uuid = await self._nodes.create_node(node_name, full_node_path, language="odps-sql")
        if not node_uuid:
            result["success"] = False
            result["steps"]["create_sql_node"] = {
                "status": "failed",
                "error": self._nodes.last_error or "create_node failed",
            }
            return result
        if not await self._nodes.update_node(node_uuid, sql_text):
            result["success"] = False
            result["steps"]["create_sql_node"] = {
                "status": "failed",
                "error": "update_node failed",
            }
            return result
        result["steps"]["create_sql_node"] = {
            "status": "ok",
            "uuid": node_uuid,
            "path": full_node_path,
        }

        # Step 5: configure schedule
        cycle_type = infer_schedule_type(target_table)
        granularity = "hour" if cycle_type == "NotDaily" else "day"
        cron = generate_cron(
            granularity, hour=3 if cycle_type == "Daily" else 0, minute=schedule_minute
        )

        # DWD 表使用 DWD_SQL_PARAMETERS（包含 gmtdate_next1d 预创建分区）
        # DWD SQL 生成器会使用 ${gmtdate_next1d} 预创建下一天的分区
        parameters = DWD_SQL_PARAMETERS if cycle_type == "NotDaily" else DAILY_SQL_PARAMETERS

        # 从 metadata 构建上游依赖（主表 + JOIN 表）
        dependencies = _build_upstream_dependencies(metadata, project)
        result["steps"]["configure_schedule"] = {"dependencies_count": len(dependencies)}

        vertex_config: dict[str, Any] = {
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
        }
        if self._nodes is self.bff:
            # bff 路径：调度与依赖分两步（保持原行为）
            scheduled = await self.bff.update_vertex(node_uuid, vertex_config)
            if scheduled:
                await self.bff._put(
                    "ide/addNodeDependencies",
                    {
                        "projectId": self.bff.project_id,
                        "uuid": node_uuid,
                        "dependencies": dependencies,
                    },
                )
        else:
            # AK/SK 适配器路径：依赖内嵌于 update_vertex 的 dependencies（→ FlowSpec flow）
            vertex_config["dependencies"] = dependencies
            scheduled = await self._nodes.update_vertex(node_uuid, vertex_config)
        result["steps"]["configure_schedule"] = {
            "status": "ok" if scheduled else "failed",
            "cron": cron,
            "cycle_type": cycle_type,
        }
        if not scheduled:
            result["success"] = False
            return result

        # Step 6: publish
        if not publish:
            result["steps"]["publish"] = {"status": "skipped", "reason": "publish=false"}
            return result

        deployed = await self._nodes.deploy_nodes(
            [node_uuid], comment=f"auto deploy {target_table}"
        )
        result["steps"]["publish"] = {"status": "ok" if deployed else "failed"}
        if not deployed:
            result["success"] = False

        result["ddl"] = ddl_text
        result["sql"] = sql_text
        result["node_uuid"] = node_uuid
        return result
