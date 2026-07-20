"""任务执行器 — 逐步执行 AutonomousTask 中的真实 DataWorks 操作。"""

from __future__ import annotations

import logging
import time
from typing import Any

from dataworks_agent.agent.autonomous.state import (
    AutonomousTask,
    ExecutionStatus,
    StepResult,
)

logger = logging.getLogger(__name__)


def _get_maxcompute_client() -> Any:
    from dataworks_agent.state import app_state

    return app_state._maxcompute_client


def _get_node_client() -> Any:
    from dataworks_agent.state import app_state

    return app_state._node_client


def _get_openapi_client() -> Any:
    from dataworks_agent.state import app_state

    return app_state._openapi_client


class AutonomousExecutor:
    """按步骤链驱动任务执行，调用真实 OpenAPI / MaxCompute 客户端。"""

    def __init__(self, openapi_client: Any, modeling_engine: Any) -> None:
        self._openapi_client = openapi_client
        self._modeling_engine = modeling_engine

    async def execute_task(self, task: AutonomousTask) -> bool:
        """按 plan 顺序逐步执行任务。

        Returns:
            True 表示所有步骤均成功；False 表示中途失败。
        """
        if task.status == ExecutionStatus.VERIFIED:
            logger.info("任务 %s 已通过验证，跳过重复执行", task.id)
            return True

        task.mark_executing()
        logger.info("开始执行任务 %s (%s): %s 步", task.id, task.task_type, len(task.plan))

        for idx, step_def in enumerate(task.plan):
            step_name = step_def.get("step", f"step_{idx}")
            logger.info("执行步骤 [%d/%d]: %s", idx + 1, len(task.plan), step_name)
            started = time.monotonic()

            try:
                success = await self.execute_step(task, step_def)
            except Exception as exc:
                elapsed = (time.monotonic() - started) * 1000
                result = StepResult(
                    step=step_name,
                    status="failed",
                    error=str(exc),
                    duration_ms=elapsed,
                )
                task.add_step_result(result)
                task.mark_failed(f"步骤 {step_name} 执行异常: {exc}")
                logger.exception("任务 %s 步骤 %s 失败: %s", task.id, step_name, exc)
                return False

            elapsed = (time.monotonic() - started) * 1000
            result = StepResult(
                step=step_name,
                status="completed" if success else "failed",
                details=step_def.get("details", {}),
                duration_ms=elapsed,
            )
            task.add_step_result(result)

            if not success:
                task.mark_failed(f"步骤 {step_name} 返回失败")
                logger.warning("任务 %s 步骤 %s 失败，停止执行", task.id, step_name)
                return False

        logger.info("任务 %s 全部步骤完成", task.id)
        return True

    async def execute_step(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """执行单个步骤。"""
        handler_name = step.get("step", "")

        handlers: dict[str, Any] = {
            "validate_params": self._handle_validate_params,
            "generate_ddl": self._handle_generate_ddl,
            "create_table": self._handle_create_table,
            "create_node": self._handle_create_node,
            "configure_schedule": self._handle_configure_schedule,
            "configure_dependencies": self._handle_configure_dependencies,
            "discover_source_tables": self._handle_discover_source_tables,
            "generate_sql": self._handle_generate_sql,
            "read_current": self._handle_read_current,
            "apply_change": self._handle_apply_change,
            "apply_schedule": self._handle_apply_schedule,
            "apply_dependency": self._handle_apply_dependency,
            "verify": self._handle_verify,
        }

        handler = handlers.get(handler_name)
        if handler is None:
            logger.warning("未知步骤类型: %s，跳过", handler_name)
            return True

        return await handler(task, step)

    # ── 参数校验 ──

    async def _handle_validate_params(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """校验目标表名、源表、数据源类型。"""
        params = task.params
        target = params.get("target_table")
        if not target:
            raise ValueError("缺少 target_table 参数")

        from dataworks_agent.schemas import assert_safe_table_name

        assert_safe_table_name(target)

        from dataworks_agent.naming.table_name import validate_table_name

        errors = validate_table_name(target)
        if errors:
            raise ValueError(f"表名校验失败: {'; '.join(errors)}")

        source_table = params.get("source_table")
        if source_table:
            assert_safe_table_name(source_table)

        logger.info("参数校验通过: target=%s", target)
        return True

    # ── DDL 生成 ──

    async def _handle_generate_ddl(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """根据任务类型生成 MaxCompute DDL。"""
        target = task.params["target_table"]
        task_type = task.task_type.value

        if task_type == "create_dwd":
            source_table = task.params.get("source_table", "")
            ddl = self._generate_dwd_ddl(target, source_table, task.params)
            task.params["_ddl"] = ddl
            logger.info("DWD DDL 生成完成: %s (%d 字符)", target, len(ddl))
        else:
            source_type = task.params.get("source_type", "mysql")
            source_table = task.params.get("source_table", "")
            datasource_name = task.params.get("datasource_name", "")

            ddl = self._generate_ods_ddl(
                target, source_type, source_table, datasource_name, task.params
            )
            task.params["_ddl"] = ddl
            logger.info("ODS DDL 生成完成: %s (%d 字符)", target, len(ddl))

        return True

    def _generate_ods_ddl(
        self,
        target_table: str,
        source_type: str,
        source_table: str,
        datasource_name: str,
        params: dict[str, Any],
    ) -> str:
        """生成 ODS 层 DDL。"""
        from dataworks_agent.config import settings

        project = settings.maxcompute_project or settings.dataworks_dev_schema or "dataworks"
        columns = params.get("columns", [])
        partition_keys = params.get("partition_keys", ["ds"])

        col_defs = []
        for col in columns:
            name = col.get("name", "")
            dtype = col.get("type", "STRING")
            # 分区键不放进列定义（MaxCompute 分区键只在 PARTITIONED BY 里）
            if name not in partition_keys:
                col_defs.append(f"    {name} {dtype}")

        if not col_defs:
            col_defs = ["    id BIGINT"]

        cols_sql = ",\n".join(col_defs)
        part_sql = (
            ", ".join(f"{k} STRING" for k in partition_keys) if partition_keys else "ds STRING"
        )

        ddl = f"""CREATE TABLE IF NOT EXISTS {project}.{target_table}
(
{cols_sql}
)
COMMENT 'ODS {source_type.upper()} 同步表 - {source_table}'
PARTITIONED BY ({part_sql});
"""
        return ddl

    def _generate_dwd_ddl(
        self,
        target_table: str,
        source_table: str,
        params: dict[str, Any],
    ) -> str:
        """生成 DWD 层 DDL。"""
        from dataworks_agent.config import settings

        project = settings.maxcompute_project or settings.dataworks_dev_schema or "dataworks"
        columns = params.get("columns", [])
        partition_keys = params.get("partition_keys", ["ds"])
        domain = params.get("domain", "")
        entity = params.get("entity", "")

        col_defs = []
        for col in columns:
            name = col.get("name", "")
            dtype = col.get("type", "STRING")
            comment = col.get("comment", "")
            col_defs.append(f"    {name} {dtype}" + (f"  -- {comment}" if comment else ""))

        if not col_defs:
            col_defs = [
                "    id BIGINT  -- 主键",
                "    ds STRING  -- 分区键",
            ]

        cols_sql = ",\n".join(col_defs)
        part_sql = (
            ", ".join(f"{k} STRING" for k in partition_keys) if partition_keys else "ds STRING"
        )
        comment_suffix = f" {domain}_{entity}" if domain and entity else ""

        ddl = f"""CREATE TABLE IF NOT EXISTS {project}.{target_table}
(
{cols_sql}
)
COMMENT 'DWD 明细表{comment_suffix} - 来源 {source_table}'
PARTITIONED BY ({part_sql});
"""
        return ddl

    # ── 建表 ──

    async def _handle_create_table(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """在 MaxCompute 上执行 DDL 建表。"""
        ddl = task.params.get("_ddl")
        if not ddl:
            raise ValueError("DDL 未生成，请先执行 generate_ddl 步骤")

        mc = _get_maxcompute_client()
        if mc is None:
            raise RuntimeError("MaxComputeClient 未初始化，请检查 app_state._maxcompute_client")

        from dataworks_agent.api_clients.maxcompute_client import JobResult

        result: JobResult = await mc.execute_ddl(ddl)
        if not result.success:
            raise RuntimeError(f"DDL 执行失败: {result.error}")

        task.params["_table_created"] = True
        logger.info(
            "MaxCompute 建表成功: %s (instance=%s)", task.params["target_table"], result.instance_id
        )
        return True

    # ── 建节点 ──

    async def _handle_create_node(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """在 DataWorks 上创建调度节点。"""
        target = task.params["target_table"]
        node_client = _get_node_client()
        if node_client is None:
            raise RuntimeError("OpenAPINodeAdapter 未初始化，请检查 app_state._node_client")

        from dataworks_agent.naming.table_name import generate_node_path

        business_folder = task.params.get("business_folder", "")
        language = task.params.get("language", "odps-sql")
        node_name = task.params.get("node_name", target)
        path = generate_node_path(business_folder, target)

        existing_uuid = await node_client.get_node_uuid_by_path(path)
        if existing_uuid:
            task.params["_node_id"] = existing_uuid
            logger.info("节点已存在，复用: %s (uuid=%s)", path, existing_uuid)
            return True

        directory_evidence = None
        if business_folder:
            try:
                directory_evidence = await node_client.check_existing_directory(business_folder)
            except Exception:
                logger.warning("目录证据获取失败，尝试直接创建: %s", business_folder)

        node_uuid = await node_client.create_node(
            name=node_name,
            path=path,
            language=language,
            directory_evidence=directory_evidence,
        )

        if node_uuid is None:
            raise RuntimeError(f"节点创建失败: {path}")

        task.params["_node_id"] = node_uuid

        # 清理 DataWorks 自动生成的多余 output，只保留一个正确的
        await self._clean_node_outputs(node_client, node_uuid, target)

        # 写入 SQL 内容到节点（优先用 _sql/DML，不用 _ddl/DDL）
        sql_content = task.params.get("_sql")
        if sql_content:
            try:
                spec = await node_client._load_spec(node_uuid)
                if spec:
                    spec["spec"]["nodes"][0]["script"]["content"] = sql_content
                    await node_client._save_spec(node_uuid, spec)
                    logger.info("节点 SQL 内容已写入: %s (%d 字符)", node_uuid, len(sql_content))
            except Exception as exc:
                logger.warning("写入节点 SQL 失败: %s, error=%s", node_uuid, exc)

        # 配置上游依赖（如果指定了）
        upstream_tables = task.params.get("_upstream_tables", [])
        if upstream_tables:
            await self._configure_node_dependencies(node_client, node_uuid, upstream_tables)

        logger.info("DataWorks 节点创建成功: %s (uuid=%s)", path, node_uuid)
        return True

    async def _clean_node_outputs(
        self, node_client: Any, node_uuid: str, target_table: str
    ) -> None:
        """清理节点的多余 output，只保留节点 ID（自动）和一个指向目标表的 output。

        DataWorks 平台会自动保留节点 ID 的 output，无法删除。
        此方法移除其他多余的 output，只添加一个指向目标表的正确 output。
        """
        try:
            spec = await node_client._load_spec(node_uuid)
            if spec is None:
                return

            node = spec.get("spec", {}).get("nodes", [{}])[0]
            project = node_client._project or "dataworks"
            target_output = f"{project}.{target_table}"

            # 保留节点 ID 的自动 output + 我们设置的目标表 output
            existing = node.get("outputs", {}).get("nodeOutputs", [])
            node_id_output = None
            for o in existing:
                if o.get("data") == node_uuid:
                    node_id_output = o
                    break

            cleaned = []
            if node_id_output:
                cleaned.append(node_id_output)
            cleaned.append(
                {
                    "artifactType": "NodeOutput",
                    "sourceType": "System",
                    "data": target_output,
                    "refTableName": target_output,
                }
            )

            node["outputs"] = {"nodeOutputs": cleaned}

            await node_client._save_spec(node_uuid, spec)
            logger.info("节点 output 已清理: %s → %d 个", node_uuid, len(cleaned))
        except Exception as exc:
            logger.warning("清理节点 output 失败: %s, error=%s", node_uuid, exc)

    async def _configure_node_dependencies(
        self, node_client: Any, node_uuid: str, upstream_tables: list[str]
    ) -> None:
        """配置节点的上游依赖和 inputs。"""
        try:
            spec = await node_client._load_spec(node_uuid)
            if spec is None:
                return

            node = spec.get("spec", {}).get("nodes", [{}])[0]
            project = node_client._project or "dataworks"

            # 清除默认根依赖
            flow = spec.get("spec", {}).get("flow", [])
            if not flow:
                flow.append({"depends": []})
            depends = [d for d in flow[0].get("depends", []) if d.get("output") != "giikin_root"]

            for table in upstream_tables:
                depends.append(
                    {
                        "type": "Normal",
                        "sourceType": "Manual",
                        "output": f"{project}.{table}",
                        "refTableName": f"{project}.{table}",
                    }
                )
            flow[0]["depends"] = depends
            spec["spec"]["flow"] = flow

            # 同步更新 inputs
            node["inputs"] = {
                "nodeOutputs": [
                    {
                        "artifactType": "NodeOutput",
                        "sourceType": "Manual",
                        "data": f"{project}.{table}",
                    }
                    for table in upstream_tables
                ],
            }

            await node_client._save_spec(node_uuid, spec)
            logger.info("节点依赖已配置: %s → upstream=%s", node_uuid, upstream_tables)
        except Exception as exc:
            logger.warning("配置节点依赖失败: %s, error=%s", node_uuid, exc)

    # ── 调度配置 ──

    async def _handle_configure_schedule(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """配置节点调度周期。"""
        node_id = task.params.get("_node_id")
        if not node_id:
            raise ValueError("节点 ID 未设置，请先执行 create_node 步骤")

        node_client = _get_node_client()
        if node_client is None:
            raise RuntimeError("OpenAPINodeAdapter 未初始化")

        from dataworks_agent.naming.schedule import (
            DAILY_SQL_PARAMETERS,
            generate_cron,
            get_cycle_type,
        )

        granularity = task.params.get("granularity", "day")
        cron = task.params.get("cron") or generate_cron(granularity)
        cycle_type = get_cycle_type(granularity)
        parameters = DAILY_SQL_PARAMETERS if granularity == "day" else []

        config = {
            "trigger": {
                "cron": cron,
                "cycleType": cycle_type,
                "timezone": "Asia/Shanghai",
            },
            "script": {
                "parameters": parameters,
            },
            "strategy": {
                "instanceMode": "Immediately",
                "rerunMode": "Allowed",
            },
        }

        success = await node_client.update_vertex(node_id, config)
        if not success:
            raise RuntimeError(f"调度配置失败: node={node_id}")

        task.params["_schedule_configured"] = True
        logger.info("调度配置成功: node=%s, cron=%s", node_id, cron)
        return True

    # ── 依赖配置 ──

    async def _handle_configure_dependencies(
        self, task: AutonomousTask, step: dict[str, Any]
    ) -> bool:
        """配置节点上游依赖。"""
        node_id = task.params.get("_node_id")
        if not node_id:
            raise ValueError("节点 ID 未设置，请先执行 create_node 步骤")

        node_client = _get_node_client()
        if node_client is None:
            raise RuntimeError("OpenAPINodeAdapter 未初始化")

        upstream_tables = task.params.get("_upstream_tables", [])
        if not upstream_tables:
            logger.info("无上游依赖需要配置")
            return True

        spec = await node_client._load_spec(node_id)
        if spec is None:
            raise RuntimeError(f"无法读取节点 spec: {node_id}")

        flow = spec.get("spec", {}).get("flow", [])
        if not flow:
            flow.append({"depends": []})

        depends = flow[0].get("depends", [])
        node = spec.get("spec", {}).get("nodes", [{}])[0]
        project = node_client._project or "dataworks"

        # 清除默认根依赖，添加真实上游
        depends = [d for d in depends if d.get("output") != "giikin_root"]

        for table in upstream_tables:
            depends.append(
                {
                    "type": "Normal",
                    "sourceType": "Manual",
                    "output": f"{project}.{table}",
                    "refTableName": f"{project}.{table}",
                }
            )

        flow[0]["depends"] = depends
        spec["spec"]["flow"] = flow

        # 同步更新 inputs
        node["inputs"] = {
            "nodeOutputs": [
                {
                    "artifactType": "NodeOutput",
                    "sourceType": "Manual",
                    "data": f"{project}.{table}",
                }
                for table in upstream_tables
            ],
        }

        success = await node_client._save_spec(node_id, spec)
        if not success:
            raise RuntimeError(f"依赖配置失败: node={node_id}")

        task.params["_dependencies_configured"] = True
        logger.info("依赖配置成功: node=%s, upstream=%s", node_id, upstream_tables)
        return True

    # ── 源表发现 ──

    async def _handle_discover_source_tables(
        self, task: AutonomousTask, step: dict[str, Any]
    ) -> bool:
        """发现并确认上游源表结构。"""
        source_table = task.params.get("source_table")
        if not source_table:
            logger.info("未指定 source_table，跳过源表发现")
            return True

        from dataworks_agent.modeling.table_discovery import TableDiscovery

        discovery = TableDiscovery()
        try:
            structure = await discovery.get_table_structure(source_table)
            task.params["_source_structure"] = {
                "table_name": structure.table_name,
                "columns": [c.model_dump() for c in structure.columns],
                "partition_keys": structure.partition_keys,
                "source_format": structure.source_format,
            }
            logger.info("源表发现完成: %s (%d 列)", source_table, len(structure.columns))
        except Exception as exc:
            logger.warning("源表发现失败 (%s)，继续执行: %s", source_table, exc)
            task.params["_source_structure"] = None

        return True

    # ── SQL 生成 ──

    async def _handle_generate_sql(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """生成 DWD SQL/DML。"""
        target = task.params["target_table"]
        source_table = task.params.get("source_table", "")
        task_type = task.task_type.value

        if task_type == "create_dwd":
            sql = self._generate_dwd_sql(target, source_table, task.params)
            task.params["_sql"] = sql
            logger.info("DWD SQL 生成完成: %s (%d 字符)", target, len(sql))
        else:
            logger.info("非 DWD 任务，跳过 SQL 生成")
            task.params["_sql"] = None

        return True

    def _generate_dwd_sql(
        self,
        target_table: str,
        source_table: str,
        params: dict[str, Any],
    ) -> str:
        """生成 DWD 层 INSERT SQL。"""
        from dataworks_agent.config import settings

        project = settings.maxcompute_project or settings.dataworks_dev_schema or "dataworks"
        columns = params.get("columns", [])
        partition_keys = params.get("partition_keys", ["ds"])

        if not columns:
            select_cols = f"SELECT\n    *\nFROM {project}.{source_table}"
        else:
            col_names = [c.get("name", "") for c in columns if c.get("name")]
            select_cols = (
                "SELECT\n    " + ",\n    ".join(col_names) + f"\nFROM {project}.{source_table}"
            )

        part_cols = ", ".join(partition_keys) if partition_keys else "ds"

        sql = f"""INSERT OVERWRITE TABLE {project}.{target_table}
PARTITION ({part_cols})
{select_cols};
"""
        return sql

    # ── 读取当前配置 ──

    async def _handle_read_current(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """读取节点当前配置（spec / 调度 / 依赖）。"""
        node_id = task.params.get("node_id")
        if not node_id:
            raise ValueError("缺少 node_id 参数")

        node_client = _get_node_client()
        if node_client is None:
            raise RuntimeError("OpenAPINodeAdapter 未初始化")

        spec = await node_client._load_spec(node_id)
        if spec is None:
            raise RuntimeError(f"无法读取节点 spec: {node_id}")

        task.params["_current_spec"] = spec
        logger.info("当前配置读取完成: node=%s", node_id)
        return True

    # ── 应用变更 ──

    async def _handle_apply_change(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """更新节点脚本内容。"""
        node_id = task.params.get("node_id")
        if not node_id:
            raise ValueError("缺少 node_id 参数")

        content = task.params.get("new_sql") or task.params.get("_ddl")
        if not content:
            raise ValueError("缺少 new_sql 或 _ddl 参数")

        node_client = _get_node_client()
        if node_client is None:
            raise RuntimeError("OpenAPINodeAdapter 未初始化")

        success = await node_client.update_node(node_id, content)
        if not success:
            raise RuntimeError(f"节点更新失败: node={node_id}")

        logger.info("节点变更已应用: node=%s", node_id)
        return True

    # ── 应用调度变更 ──

    async def _handle_apply_schedule(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """应用调度配置变更。"""
        return await self._handle_configure_schedule(task, step)

    # ── 应用依赖变更 ──

    async def _handle_apply_dependency(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """应用依赖配置变更。"""
        return await self._handle_configure_dependencies(task, step)

    # ── 验证 ──

    async def _handle_verify(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """验证步骤 — 委托给 AutonomousVerifier。"""
        from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

        verifier = AutonomousVerifier(_get_openapi_client())
        result = await verifier.verify_task(task)
        return result.success
