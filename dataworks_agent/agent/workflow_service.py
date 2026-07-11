"""一句话 DataWorks Agent 的真实执行工作流。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlglot
from sqlglot import exp

from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.config import settings
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    generate_cron,
)
from dataworks_agent.schemas import assert_safe_table_name
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)

ExecutionMode = Literal["plan", "dev_execute"]
_FINAL_STATUSES = {"completed", "failed", "cancelled"}
_WRITE_WORDS = ("创建", "新建", "建好", "执行", "初始化", "生成任务", "落地", "部署开发")


@dataclass
class WorkflowResult:
    success: bool
    message: str
    workflow_type: str
    mode: ExecutionMode
    steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        return {
            "workflow_type": self.workflow_type,
            "execution_mode": self.mode,
            "steps": self.steps,
            "artifacts": self.artifacts,
            "errors": self.errors,
            **self.data,
        }


class AgentWorkflowService:
    """把会话意图路由到项目中已有的真实 AK/SK、Cookie 与 MCP 能力。"""

    def __init__(self) -> None:
        self._extractor = EntityExtractor()

    def infer_mode(self, message: str, requested: str) -> ExecutionMode:
        if requested == "plan":
            return "plan"
        if requested == "dev_execute":
            return "dev_execute"
        return "dev_execute" if any(word in message for word in _WRITE_WORDS) else "plan"

    async def execute(
        self,
        *,
        message: str,
        action: str,
        params: dict[str, Any],
        execution_mode: str = "auto",
        initialize_data: bool = True,
        publish: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> WorkflowResult:
        mode = self.infer_mode(message, execution_mode)
        routed = self._route_action(message, action)
        if routed == "cookie_manage":
            return await self._manage_cookie(message, mode)
        if routed == "ask_data":
            return await self._ask_data(message, mode)
        if routed == "reverse_modeling":
            return await self._reverse_model(message, params, mode)
        if routed == "diagnose_issue":
            return await self._diagnose(message, params, mode)
        return await self._forward_model(
            message,
            params,
            mode,
            initialize_data=initialize_data,
            publish=publish,
            client_ip=client_ip,
        )

    @staticmethod
    def _route_action(message: str, action: str) -> str:
        lower = message.lower()
        if action == "cookie_manage" or "cookie" in lower or "9222" in lower or "登录态" in message:
            return "cookie_manage"
        if action == "ask_data" or any(k in message for k in ("问数", "查数", "多少条", "前几条")):
            return "ask_data"
        return action

    def capability_status(self) -> dict[str, Any]:
        official = getattr(app_state, "_official_mcp_client", None)
        return {
            "ak_sk": bool(settings.aliyun_access_key_id and settings.aliyun_access_key_secret),
            "openapi": getattr(app_state, "_openapi_client", None) is not None,
            "maxcompute": getattr(app_state, "_maxcompute_client", None) is not None,
            "node_adapter": getattr(app_state, "_node_client", None) is not None,
            "cookie_bff": getattr(app_state, "_bff_client", None) is not None,
            "cdp_9222": getattr(app_state, "_cdp_client", None) is not None,
            "official_mcp": official.status.to_dict() if official else {"enabled": False, "connected": False},
        }

    async def _manage_cookie(self, message: str, mode: ExecutionMode) -> WorkflowResult:
        status = self.capability_status()
        if mode == "plan" or not any(k in message for k in ("提取", "刷新", "同步", "更新", "获取")):
            return WorkflowResult(True, "已检查 AK/SK、9222 调试浏览器和 Cookie 兜底通道。", "cookie_manage", mode, data={"capabilities": status})
        from dataworks_agent.cookie.background_refresh import cdp_extract_and_apply

        result = await cdp_extract_and_apply()
        ok = result.get("status") == "success"
        return WorkflowResult(
            ok,
            "已从 9222 登录浏览器提取并同步 Cookie。" if ok else f"Cookie 更新未完成：{result.get('detail', '未知错误')}",
            "cookie_manage",
            mode,
            steps=[{"step": "cookie_refresh", **result}],
            data={"capabilities": self.capability_status()},
            errors=[] if ok else [str(result.get("detail", "cookie refresh failed"))],
        )

    async def _reverse_model(self, message: str, params: dict[str, Any], mode: ExecutionMode) -> WorkflowResult:
        table = params.get("table_name") or params.get("source_table") or self._extractor.extract_table_name(message)
        node_match = re.search(r"(?:节点|node)\s*[:：]?\s*([A-Za-z0-9_-]+)", message, re.I)
        mc = getattr(app_state, "_maxcompute_client", None)
        api = getattr(app_state, "_openapi_client", None)
        if node_match and api is not None:
            from dataworks_agent.api_clients.openapi_node_adapter import _to_map

            node_id = node_match.group(1)
            body = _to_map(await api.get_node(node_id)).get("Node") or {}
            spec = json.loads(body.get("Spec") or "{}")
            nodes = (spec.get("spec") or {}).get("nodes") or []
            script = (nodes[0].get("script") if nodes else {}) or {}
            return WorkflowResult(True, f"已逆向读取节点 {node_id} 的 FlowSpec 与 SQL。", "reverse_modeling", mode, artifacts=[{"type": "node_sql", "name": node_id, "content": script.get("content", "")}], data={"node": body, "flowspec": spec})
        if not table:
            return WorkflowResult(False, "请在一句话中给出要逆向的表名或节点 ID。", "reverse_modeling", mode, errors=["missing table or node"])
        assert_safe_table_name(table.split(".")[-1])
        if mc is None:
            return WorkflowResult(False, "MaxCompute AK/SK 客户端不可用，无法读取真实表结构。", "reverse_modeling", mode, errors=["maxcompute client unavailable"])
        schema = await mc.get_table_schema(table)
        columns = [c.__dict__ for c in schema.columns]
        partitions = [c.__dict__ for c in schema.partition_keys]
        lineage: Any = []
        bff = getattr(app_state, "_bff_client", None)
        if bff is not None:
            try:
                lineage = await bff.list_lineage(f"odps.{settings.maxcompute_project}.{table.split('.')[-1]}")
            except Exception as exc:
                lineage = {"warning": str(exc)}
        return WorkflowResult(
            True,
            f"已从 MaxCompute 元数据逆向表 {table}，并按权限矩阵补充 Cookie 血缘。",
            "reverse_modeling",
            mode,
            artifacts=[{"type": "table_schema", "name": table, "columns": columns, "partitions": partitions}],
            data={"table": table, "columns": columns, "partitions": partitions, "lineage": lineage},
        )

    async def _diagnose(self, message: str, params: dict[str, Any], mode: ExecutionMode) -> WorkflowResult:
        task_id = params.get("task_id") or self._extractor.extract_task_id(message)
        checks = self.capability_status()
        details: dict[str, Any] = {"capabilities": checks, "startup": app_state.smoke_results}
        errors: list[str] = []
        if task_id:
            from dataworks_agent.db.database import SessionLocal
            from dataworks_agent.db.models import ModelingTaskModel

            with SessionLocal() as db:
                task = db.get(ModelingTaskModel, task_id)
                details["task"] = None if task is None else {
                    "task_id": task.task_id,
                    "status": task.status,
                    "target_table": task.target_table,
                    "error_message": task.error_message,
                    "node_uuid": task.node_uuid,
                }
                if task and task.error_message:
                    errors.append(task.error_message)
        ready = checks["ak_sk"] and checks["maxcompute"] and checks["node_adapter"]
        return WorkflowResult(
            ready and not errors,
            "异常排查已完成：已汇总任务状态、AK/SK、官方 MCP、Cookie/BFF 与 9222 CDP 健康度。",
            "diagnose_issue",
            mode,
            steps=[{"step": "health_matrix", "status": "ok" if ready else "degraded"}, {"step": "task_diagnosis", "status": "failed" if errors else "ok"}],
            data=details,
            errors=errors,
        )

    async def _ask_data(self, message: str, mode: ExecutionMode) -> WorkflowResult:
        mc = getattr(app_state, "_maxcompute_client", None)
        if mc is None:
            return WorkflowResult(False, "MaxCompute AK/SK 客户端不可用，无法执行只读问数。", "ask_data", mode, errors=["maxcompute client unavailable"])
        sql = await self._build_readonly_sql(message)
        self._validate_readonly_sql(sql)
        instance = await mc.submit_query(sql)
        result = await asyncio.wait_for(mc.wait_and_fetch(instance), timeout=settings.ask_data_timeout_seconds)
        rows = result.rows[: settings.ask_data_default_limit]
        return WorkflowResult(
            True,
            f"问数完成，返回 {len(rows)} 行（最多 {settings.ask_data_default_limit} 行）。",
            "ask_data",
            mode,
            artifacts=[{"type": "query_sql", "name": "readonly_query", "content": sql}],
            data={"query": {"sql": sql, "columns": result.columns, "rows": rows, "row_count": len(rows)}},
        )

    async def _build_readonly_sql(self, message: str) -> str:
        fenced = re.search(r"```sql\s*(.*?)```", message, re.I | re.S)
        if fenced:
            return fenced.group(1).strip()
        table = self._extractor.extract_table_name(message)
        if not table:
            raw = re.search(r"(?:查询|统计|查看|表)\s*([A-Za-z][A-Za-z0-9_.]+)", message)
            table = raw.group(1) if raw else None
        if table:
            assert_safe_table_name(table.split(".")[-1])
            if any(k in message for k in ("多少条", "行数", "count")):
                return f"SELECT COUNT(*) AS row_count FROM {table}"
            return f"SELECT * FROM {table} LIMIT {settings.ask_data_default_limit}"
        if not settings.llm_api_key:
            raise ValueError("复杂自然语言问数需要配置 LLM_API_KEY；也可以直接提供表名或 SQL。")
        from dataworks_agent.llm.context import ContextBuilder
        from dataworks_agent.llm.service import LLMService

        context = (ContextBuilder().add_instruction("只生成 MaxCompute 只读 SELECT/WITH SQL，不要解释，不得生成写操作，默认 LIMIT 100。")
                   .add_prompt(message).build())
        response = await LLMService.from_settings(settings).complete(context, "normal")
        return response.content.strip().removeprefix("```sql").removesuffix("```").strip()

    @staticmethod
    def _validate_readonly_sql(sql: str) -> None:
        statements = sqlglot.parse(sql, read="hive")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise ValueError("自主问数只允许单条 SELECT/WITH 查询")
        forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.Command)
        if any(statement.find(kind) for statement in statements for kind in forbidden):
            raise ValueError("自主问数检测到写入或 DDL 操作，已阻止")

    async def _forward_model(
        self,
        message: str,
        params: dict[str, Any],
        mode: ExecutionMode,
        *,
        initialize_data: bool,
        publish: bool,
        client_ip: str,
    ) -> WorkflowResult:
        tables = self._extractor.extract_table_names(message)
        by_layer: dict[str, list[str]] = {layer: [] for layer in ("ods", "dwd", "dim", "dws")}
        for table in tables:
            layer = table.split("_", 1)[0].lower()
            if layer in by_layer:
                assert_safe_table_name(table)
                by_layer[layer].append(table)
        source_table = params.get("source_table") or self._extractor.extract_source_table(message)
        datasource = params.get("datasource_name") or self._extractor.extract_datasource_name(message)
        granularity = params.get("granularity") or self._extractor.extract_granularity(message) or "day"
        schedule_minute = params.get("schedule_minute") or 1
        plan = self._build_forward_plan(by_layer, source_table, datasource, initialize_data)
        if mode == "plan":
            return WorkflowResult(True, "已生成 ODS→DWD/DIM→DWS 全链路开发执行计划；切换到开发执行即可建表、建草稿节点并初始化。", "forward_modeling", mode, steps=plan, data={"capabilities": self.capability_status(), "publish_gate": "required_for_publish"})
        if not source_table:
            return WorkflowResult(False, "缺少源表。请在一句话中说明数据源和源表。", "forward_modeling", mode, steps=plan, errors=["missing source_table"])
        if not getattr(app_state, "_node_client", None) or not getattr(app_state, "_maxcompute_client", None):
            return WorkflowResult(False, "AK/SK 执行底座未就绪，无法进行开发环境真实写入。", "forward_modeling", mode, steps=plan, data={"capabilities": self.capability_status()}, errors=["execution clients unavailable"])

        executed: list[dict[str, Any]] = []
        upstream = source_table
        if by_layer["ods"]:
            ods_table = by_layer["ods"][0]
            ods_result = await self._execute_ods(datasource, source_table, ods_table, granularity, schedule_minute, initialize_data)
            executed.append({"layer": "ODS", "table": ods_table, "result": ods_result})
            if not ods_result.get("success"):
                return WorkflowResult(False, "ODS 建表、节点或初始化失败，已停止下游建模。", "forward_modeling", mode, steps=plan, data={"executed": executed}, errors=["ODS execution failed"])
            upstream = ods_table
        for layer in ("dwd", "dim"):
            for table in by_layer[layer]:
                layer_result = await self._deploy_warehouse_layer(layer.upper(), upstream, table, granularity, schedule_minute)
                executed.append({"layer": layer.upper(), "table": table, "result": layer_result})
                if not layer_result.get("success"):
                    return WorkflowResult(False, f"{layer.upper()} 开发任务创建失败。", "forward_modeling", mode, steps=plan, data={"executed": executed}, errors=[f"{layer} execution failed"])
                if layer == "dwd":
                    upstream = table
        for table in by_layer["dws"]:
            layer_result = await self._deploy_warehouse_layer("DWS", upstream, table, granularity, schedule_minute)
            executed.append({"layer": "DWS", "table": table, "result": layer_result})
            if not layer_result.get("success"):
                return WorkflowResult(False, "DWS 开发任务创建失败。", "forward_modeling", mode, steps=plan, data={"executed": executed}, errors=["dws execution failed"])
            upstream = table
        if not any(by_layer.values()):
            return WorkflowResult(False, "请在一句话中给出至少一个 ods_/dwd_/dim_/dws_ 目标表名。", "forward_modeling", mode, steps=plan, errors=["missing target tables"])
        result_data: dict[str, Any] = {
            "executed": executed,
            "capabilities": self.capability_status(),
            "publish_gate": "not_requested",
        }
        message_text = (
            "开发环境全链路已完成：表已创建，节点与调度已保存；"
            "初始化按请求执行，正式发布仍等待 Publish Gate。"
        )
        if publish:
            from dataworks_agent.runtime.publish_gate import PublishGate

            gate = getattr(app_state, "_publish_gate", None) or PublishGate()
            app_state._publish_gate = gate
            request = await gate.interrupt_for_approval(
                run_id=f"agent_{uuid.uuid4().hex[:12]}",
                session_id=client_ip,
                table_name=tables[-1] if tables else source_table,
                change_type="create",
                payload={"message": message, "tables": by_layer, "executed": executed},
                context={"mode": mode},
            )
            result_data["publish_request"] = request.__dict__
            result_data["publish_gate"] = "approval_required"
            message_text = (
                f"开发环境全链路已完成，并已创建发布审批 {request.request_id}；"
                "未绕过 Publish Gate 上线。"
            )
        return WorkflowResult(
            True,
            message_text,
            "forward_modeling",
            mode,
            steps=plan,
            artifacts=self._execution_artifacts(executed),
            data=result_data,
        )

    @staticmethod
    def _build_forward_plan(by_layer: dict[str, list[str]], source_table: str | None, datasource: str | None, initialize: bool) -> list[dict[str, Any]]:
        steps = [{"step": "credential_and_cookie_health", "status": "planned"}, {"step": "official_mcp_health", "status": "planned"}]
        if by_layer["ods"]:
            steps.extend([{"step": "discover_source_schema", "datasource": datasource, "source_table": source_table, "status": "planned"}, {"step": "create_ods_table_and_di_node", "tables": by_layer["ods"], "status": "planned"}])
            if initialize:
                steps.append({"step": "initialize_ods_data", "status": "planned"})
        for layer in ("dwd", "dim", "dws"):
            if by_layer[layer]:
                steps.append({"step": f"create_{layer}_tables_nodes_schedule", "tables": by_layer[layer], "status": "planned"})
        steps.append({"step": "publish_gate", "status": "required_only_for_publish"})
        return steps

    async def _execute_ods(self, datasource: str | None, source_table: str, target_table: str, granularity: str, schedule_minute: int, initialize: bool) -> dict[str, Any]:
        if not datasource:
            return {"success": False, "error": "ODS DI 需要 datasource_name"}
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return {"success": False, "error": "Cookie/BFF 不可用，无法发现数据源字段或手动初始化 DI"}
        from dataworks_agent.services.ods_di.pipeline import DIPipeline

        pipeline = DIPipeline(bff, app_state.mcp_pool, node_client=app_state._node_client, mc_client=app_state._maxcompute_client)
        return await pipeline.run(
            datasource_name=datasource, source_table=source_table, target_table=target_table,
            granularity="hour" if granularity in {"hour", "hourly"} else "day", schedule_minute=schedule_minute,
            mc_project=settings.dataworks_dev_schema, with_initialization=initialize,
            init_config={"dev_mc_project": settings.dataworks_dev_schema, "prod_mc_project": settings.dataworks_prod_schema,
                         "copy_to_prod": False, "publish_incremental_after_init": False},
        )

    async def _deploy_warehouse_layer(self, layer: str, source_table: str, target_table: str, granularity: str, schedule_minute: int) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        nodes = app_state._node_client
        schema = await mc.get_table_schema(source_table)
        columns = [c for c in schema.columns if c.name.lower() not in {"dt", "ht", "hh"}]
        if not columns:
            return {"success": False, "error": f"源表 {source_table} 无业务字段"}
        partition_names = ["dt", "ht"] if granularity in {"hour", "hourly"} else ["dt"]
        ddl_cols = ",\n".join(f"  `{c.name}` {self._normalize_mc_type(c.type)} COMMENT '{self._escape_comment(c.comment)}'" for c in columns)
        partitions = ", ".join(f"`{name}` STRING" for name in partition_names)
        ddl = f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n{ddl_cols}\n) PARTITIONED BY ({partitions}) COMMENT '{layer} Agent generated';"
        if not await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            ddl_result = await mc.execute_ddl(ddl)
            if not ddl_result.success:
                return {"success": False, "error": ddl_result.error, "ddl": ddl}
        select_cols = ",\n".join(f"  `{c.name}`" for c in columns)
        if granularity in {"hour", "hourly"}:
            partition = "PARTITION (dt='${bizdate}', ht='${hour}')"
            where = "WHERE dt='${bizdate}' AND ht='${hour}'"
            cycle = "NotDaily"
            parameters = HOURLY_SQL_PARAMETERS
            cron = generate_cron("hour", minute=schedule_minute)
        else:
            partition = "PARTITION (dt='${bizdate}')"
            where = "WHERE dt='${bizdate}'"
            cycle = "Daily"
            parameters = DAILY_SQL_PARAMETERS
            cron = generate_cron("day", hour=3, minute=schedule_minute)
        sql = f"INSERT OVERWRITE TABLE {settings.dataworks_dev_schema}.{target_table} {partition}\nSELECT\n{select_cols}\nFROM {settings.dataworks_dev_schema}.{source_table}\n{where};"
        node_path = generate_node_path(f"dataworks_agent/{'02_DWD' if layer == 'DWD' else '03_' + layer}", target_table)
        node_uuid = await nodes.create_node(target_table, node_path, language="odps-sql")
        if not node_uuid or not await nodes.update_node(node_uuid, sql):
            return {"success": False, "error": nodes.last_error or "create/update node failed", "ddl": ddl, "sql": sql}
        scheduled = await nodes.update_vertex(node_uuid, {"trigger": {"type": "Scheduler", "cron": cron, "cycleType": cycle, "startTime": "1970-01-01 00:00:00", "endTime": "9999-01-01 00:00:00", "timezone": "Asia/Shanghai"}, "script": {"parameters": parameters}, "strategy": {"instanceMode": "Immediately"}, "dependencies": [{"type": "Normal", "sourceType": "Manual", "output": f"{settings.maxcompute_project}.{source_table}", "refTableName": f"{settings.maxcompute_project}.{source_table}"}, {"type": "CrossCycleDependsOnSelf"}]})
        return {"success": bool(scheduled), "table_status": "exists_or_created", "node_uuid": node_uuid, "node_path": node_path, "cron": cron, "ddl": ddl, "sql": sql, "publish": "saved_not_deployed"}

    @staticmethod
    def _normalize_mc_type(value: str) -> str:
        lower = value.lower()
        if any(t in lower for t in ("tinyint", "smallint", "int", "bigint")):
            return "BIGINT"
        if any(t in lower for t in ("decimal", "double", "float")):
            return "DECIMAL(24,6)"
        if "boolean" in lower:
            return "BOOLEAN"
        return "STRING"

    @staticmethod
    def _escape_comment(value: str) -> str:
        return (value or "").replace("'", "''")

    @staticmethod
    def _execution_artifacts(executed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for item in executed:
            result = item["result"]
            for kind in ("ddl", "sql"):
                if result.get(kind):
                    artifacts.append({"type": kind, "name": item["table"], "content": result[kind]})
        return artifacts
