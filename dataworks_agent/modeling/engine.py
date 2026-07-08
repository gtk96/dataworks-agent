"""ModelingEngine — 数仓建模全流程编排。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from datetime import UTC
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.naming.schedule import (
    get_schedule_config,
    granularity_from_update_method,
)
from dataworks_agent.naming.table_name import validate_table_name
from dataworks_agent.schemas import CreateTaskRequest, TaskStatus
from dataworks_agent.services.task_classification import NODE_TYPE_ODPS
from dataworks_agent.state import app_state
from dataworks_agent.task_engine.state_machine import TaskStateMachine

logger = logging.getLogger(__name__)


async def _publish_task_status(task_id: str, status: str) -> None:
    """本地 publish helper — 驱动 dashboard WS 实时刷新 + cache 失效。

    与 routers/modeling.py:_publish_task_status_changed 行为等价，独立实现避免
    router/engine 的反向依赖。失败时记 warning（不影响主链路，v10 §5.1）。
    """
    request_id = uuid.uuid4().hex[:12]
    try:
        from dataworks_agent.cache.events import Event, EventType, get_event_bus

        await get_event_bus().publish_async(
            Event(
                event_type=EventType.TASK_STATUS_CHANGED,
                source="task",
                data={
                    "task_id": task_id,
                    "status": status,
                    "timestamp": time.time(),
                    "request_id": request_id,
                },
            )
        )
    except Exception as exc:
        logger.warning(
            "TASK_STATUS_CHANGED publish failed: task=%s status=%s request_id=%s err=%s",
            task_id,
            status,
            request_id,
            exc,
        )


class ModelingEngine:
    """建模工作流编排器。"""

    def __init__(self):
        from dataworks_agent.modeling.ddl_generator import DDLGenerator
        from dataworks_agent.modeling.dml_generator import DMLGenerator
        from dataworks_agent.modeling.ownership import OwnershipTracker
        from dataworks_agent.modeling.root_checker import RootChecker
        from dataworks_agent.modeling.schedule_config import ScheduleConfigurator
        from dataworks_agent.modeling.table_discovery import TableDiscovery
        from dataworks_agent.modeling.table_manager import TableManager

        self.ddl_gen = DDLGenerator()
        self.dml_gen = DMLGenerator()
        self.table_mgr = TableManager()
        self.root_checker = RootChecker()
        self.schedule_cfg = ScheduleConfigurator()
        self.table_discovery = TableDiscovery()
        self.ownership = OwnershipTracker()

    async def create_task(self, request: CreateTaskRequest, client_ip: str) -> str:
        """创建建模任务。dry_run 模式同步生成 DDL 并标记完成。"""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        logger.info(
            "创建建模任务 %s (IP: %s, 源表: %s, dry_run=%s)",
            task_id,
            client_ip,
            request.source_table,
            request.dry_run,
        )

        target_table = f"{request.target_layer.value.lower()}_{request.domain}_{request.entity}_{request.update_method.value}"
        if request.update_method.value == "hourly":
            target_table = (
                f"{request.target_layer.value.lower()}_{request.domain}_{request.entity}_hourly"
            )

        name_errors = validate_table_name(target_table)
        if name_errors:
            raise ValueError(f"目标表名不符合规范: {'; '.join(name_errors)}")

        # 层间依赖校验：源表必须来自正确的上游层
        source_prefix = (
            request.source_table.rsplit(".", 1)[-1].lower().split("_")[0]
            if "." in request.source_table
            else request.source_table.lower().split("_")[0]
        )
        layer = request.target_layer.value
        valid_prefixes = {
            "DWD": {"ods"},
            "DIM": {"ods"},
            "DWS": {"dwd", "dim"},
            "DMR": {"dws"},
        }
        expected = valid_prefixes.get(layer, set())
        if expected and source_prefix not in expected:
            raise ValueError(
                f"{layer} 层的源表必须来自 {'/'.join(expected)} 层，"
                f"但源表 {request.source_table} 的前缀是 '{source_prefix}'"
            )

        schedule_payload: dict = {}
        if request.schedule_config:
            schedule_payload = request.schedule_config.model_dump()
        else:
            gran = granularity_from_update_method(request.update_method.value)
            cfg = get_schedule_config(gran)
            schedule_payload = {
                "cycle_type": cfg["cycle_type"],
                "cron": cfg["cron"],
            }

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            model = ModelingTaskModel(
                task_id=task_id,
                status=TaskStatus.PENDING.value,
                created_by_ip=client_ip,
                source_table=request.source_table,
                target_table=target_table,
                target_layer=request.target_layer.value,
                node_type=NODE_TYPE_ODPS,
                domain=request.domain,
                entity=request.entity,
                update_method=request.update_method.value,
                partition_keys_json=json.dumps(request.partition_keys),
                schedule_config_json=json.dumps(schedule_payload, ensure_ascii=False),
                dwd_metadata_json=json.dumps(
                    request.dwd_metadata if request.dwd_metadata else {}, ensure_ascii=False
                ),
            )
            db.add(model)
            db.commit()

        # dashboard 实时刷新：create_task 同步写完 PENDING 后立即 publish（fire-and-forget）。
        # 不阻塞主流程；publish_async 失败只记 debug 不抛。
        await _publish_task_status(task_id, TaskStatus.PENDING.value)

        if request.dry_run:
            # DWD → 走专用生成器
            if request.target_layer.value == "DWD":
                dwd_metadata = request.dwd_metadata

                # 如果没有提供 dwd_metadata，自动推断
                if not dwd_metadata:
                    from dataworks_agent.modeling.field_mapper import infer_dwd_field_mappings
                    from dataworks_agent.modeling.table_discovery import TableDiscovery

                    discovery = TableDiscovery()
                    source_structure = await discovery.get_table_structure(request.source_table)
                    if source_structure.columns:
                        dwd_metadata = infer_dwd_field_mappings(
                            [c.model_dump() for c in source_structure.columns],
                            request.source_table,
                        )
                        # 添加 target 信息
                        dwd_metadata["targets"] = [
                            {
                                "table_name": target_table,
                                "update_mode": request.update_method.value,
                                "partition_fields": request.partition_keys or ["dt"],
                            }
                        ]
                        dwd_metadata["logical_primary_keys"] = []

                if dwd_metadata:
                    from dataworks_agent.modeling.dwd.ddl_generator import DwdDDLGenerator
                    from dataworks_agent.modeling.dwd.metadata import build_structured_metadata
                    from dataworks_agent.modeling.dwd.sql_generator import DwdSQLGenerator

                    ddl_gen = DwdDDLGenerator()
                    try:
                        ddl_meta = ddl_gen.from_structured_metadata(dwd_metadata)
                        ddl_text = ddl_gen.generate(ddl_meta)
                    except Exception as e:
                        raise ValueError(f"DWD DDL 生成失败: {e}") from e

                    dml_text = ""
                    if dwd_metadata.get("sources"):
                        try:
                            sql_gen = DwdSQLGenerator()
                            metadata = build_structured_metadata(dwd_metadata)
                            dml_text = sql_gen.generate(metadata)
                        except Exception as e:
                            logger.warning("DWD DML 生成失败（跳过）: %s", e)

                    with SessionLocal() as db:
                        task = db.get(ModelingTaskModel, task_id)
                        if task:
                            task.ddl_dev = ddl_text
                            task.ddl_prod = ddl_text
                            task.dml = dml_text
                            task.status = TaskStatus.COMPLETED.value
                            task.duration_seconds = 0.1
                            self._save_artifact(db, task)
                            db.commit()
                    await _publish_task_status(task_id, TaskStatus.COMPLETED.value)
                    await self.ownership.record_table_creation(target_table, client_ip)
                    return task_id

            # 通用流程 dry_run
            await self.ddl_gen.generate(request, target_table, task_id)
            from dataworks_agent.modeling.dml_generator import (
                _build_dml_json,
                _build_dml_structured,
            )

            with SessionLocal() as db:
                task = db.get(ModelingTaskModel, task_id)
                if task:
                    columns = json.loads(task.columns_json) if task.columns_json else []
                    fmt = "json" if "json_data" in (task.ddl_dev or "").lower() else "structured"
                    dml = (_build_dml_json if fmt == "json" else _build_dml_structured)(
                        settings.dataworks_dev_schema,
                        settings.dataworks_prod_schema,
                        target_table,
                        request.source_table,
                        columns,
                        request.update_method.value,
                    )
                    task.dml = dml
                    task.status = TaskStatus.COMPLETED.value
                    task.duration_seconds = 0.1
                    self._save_artifact(db, task)
                    db.commit()
            await _publish_task_status(task_id, TaskStatus.COMPLETED.value)
            await self.ownership.record_table_creation(target_table, client_ip)
            return task_id

        # 非 dry_run: 异步启动 pipeline（包装异常捕获）
        async def _safe_pipeline():
            try:
                await self._run_pipeline(task_id, request, target_table, client_ip)
            except Exception as e:
                logger.exception("任务 %s 流水线异常: %s", task_id, e)
                from datetime import datetime

                from dataworks_agent.db.database import SessionLocal
                from dataworks_agent.db.models import ModelingTaskModel

                with SessionLocal() as db:
                    t = db.get(ModelingTaskModel, task_id)
                    if t and t.status not in ("completed", "failed", "cancelled"):
                        t.status = "failed"
                        t.error_message = f"流水线异常: {e}"
                        t.updated_at = datetime.now(UTC).isoformat()
                        db.commit()
                        # dashboard 实时刷新：_safe_pipeline 异常回滚时 publish FAILED
                        await _publish_task_status(task_id, "failed")

        # fire-and-forget pipeline；引用返回值避免 RUF006 dangling task warning
        background_task = asyncio.create_task(_safe_pipeline())
        app_state._background_tasks = getattr(app_state, "_background_tasks", [])
        app_state._background_tasks.append(background_task)
        return task_id

    async def preview_task(self, request: CreateTaskRequest) -> dict[str, Any]:
        """预览：生成 DDL/DML 但不写库，无副作用。"""
        target_table = f"{request.target_layer.value.lower()}_{request.domain}_{request.entity}_{request.update_method.value}"
        if request.update_method.value == "hourly":
            target_table = (
                f"{request.target_layer.value.lower()}_{request.domain}_{request.entity}_hourly"
            )

        name_errors = validate_table_name(target_table)
        if name_errors:
            raise ValueError(f"目标表名不符合规范: {'; '.join(name_errors)}")

        result: dict[str, Any] = {"ddl_dev": "", "ddl_prod": "", "dml": ""}

        if request.target_layer.value == "DWD":
            dwd_metadata = request.dwd_metadata
            if not dwd_metadata:
                from dataworks_agent.modeling.field_mapper import infer_dwd_field_mappings
                from dataworks_agent.modeling.table_discovery import TableDiscovery

                discovery = TableDiscovery()
                source_structure = await discovery.get_table_structure(request.source_table)
                if source_structure.columns:
                    dwd_metadata = infer_dwd_field_mappings(
                        [c.model_dump() for c in source_structure.columns],
                        request.source_table,
                    )
                    dwd_metadata["targets"] = [
                        {
                            "table_name": target_table,
                            "update_mode": request.update_method.value,
                            "partition_fields": request.partition_keys or ["dt"],
                        }
                    ]
                    dwd_metadata["logical_primary_keys"] = []

            if dwd_metadata:
                from dataworks_agent.modeling.dwd.ddl_generator import DwdDDLGenerator
                from dataworks_agent.modeling.dwd.metadata import build_structured_metadata
                from dataworks_agent.modeling.dwd.sql_generator import DwdSQLGenerator

                ddl_gen = DwdDDLGenerator()
                try:
                    ddl_meta = ddl_gen.from_structured_metadata(dwd_metadata)
                    result["ddl_dev"] = ddl_gen.generate(ddl_meta)
                except Exception as e:
                    raise ValueError(f"DWD DDL 生成失败: {e}") from e

                if dwd_metadata.get("sources"):
                    try:
                        sql_gen = DwdSQLGenerator()
                        metadata = build_structured_metadata(dwd_metadata)
                        result["dml"] = sql_gen.generate(metadata)
                    except Exception as e:
                        logger.warning("DWD DML 生成失败（跳过）: %s", e)

                result["ddl_prod"] = result["ddl_dev"]
        else:
            await self.ddl_gen.generate(request, target_table, preview_result=result)

        return result

    async def _run_pipeline(
        self, task_id: str, request: CreateTaskRequest, target_table: str, client_ip: str
    ) -> None:
        """异步执行建模全流程。"""
        from datetime import datetime

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        start = datetime.now(UTC)
        TaskStateMachine(task_id)
        errors = []

        async def update_status(status: str):
            with SessionLocal() as db:
                t = db.get(ModelingTaskModel, task_id)
                if t:
                    t.status = status
                    t.updated_at = datetime.now(UTC).isoformat()
                    db.commit()
                    # dashboard 实时刷新：状态机每次 transition 后 publish
                    # 用 fire-and-forget 防止 commit 链路被阻塞
                    await _publish_task_status(task_id, status)

        # DWD 专用流程
        if request.target_layer.value == "DWD" and request.dwd_metadata:
            await self._run_dwd_pipeline(task_id, request, target_table, client_ip, start, errors)
            return

        # 通用流程（DWS/DMR/DIM）

        # Step 1: DDL 生成
        await update_status(TaskStatus.DDL_GEN.value)
        try:
            await self.ddl_gen.generate(request, target_table, task_id)
        except Exception as e:
            errors.append(f"DDL生成: {e}")
            return

        # Step 2: 建表 — 通过 MCP execute_ddl 执行（MCP 有数据源权限）
        await update_status(TaskStatus.TABLE_CRE.value)
        try:
            with SessionLocal() as db:
                t = db.get(ModelingTaskModel, task_id)
                ddl_dev = t.ddl_dev if t else ""

            if not ddl_dev:
                errors.append("DDL为空，无法建表")
            else:
                from dataworks_agent.mcp.operations import execute_ddl

                # MCP execute_ddl 自动加 dataworks. 前缀
                result = await execute_ddl(ddl_dev)
                if isinstance(result, dict) and result.get("status") == "SUCCESS":
                    logger.info("建表成功: %s", target_table)
                else:
                    errors.append(f"建表失败: {str(result)[:200]}")
        except Exception as e:
            errors.append(f"建表异常: {e}")

        # 建表失败 → 不继续
        if any("建表" in e for e in errors):
            pass  # 继续标记失败
        else:
            # Step 3: 词根校验
            await update_status(TaskStatus.ROOT_CHECK.value)
            with contextlib.suppress(Exception):
                await self.root_checker.check(task_id)

            # Step 4: DML 生成
            await update_status(TaskStatus.DML_WRITE.value)
            try:
                from dataworks_agent.modeling.dml_generator import (
                    _build_dml_json,
                    _build_dml_structured,
                )

                with SessionLocal() as db:
                    t = db.get(ModelingTaskModel, task_id)
                    if t:
                        cols = json.loads(t.columns_json) if t.columns_json else []
                        fmt = "json" if "json_data" in (t.ddl_dev or "").lower() else "structured"
                        dml = (_build_dml_json if fmt == "json" else _build_dml_structured)(
                            settings.dataworks_dev_schema,
                            settings.dataworks_prod_schema,
                            target_table,
                            request.source_table,
                            cols,
                            request.update_method.value,
                        )
                        t.dml = dml
                        db.commit()
            except Exception as e:
                errors.append(f"DML生成: {e}")

        # 标记完成/失败
        with SessionLocal() as db:
            t = db.get(ModelingTaskModel, task_id)
            if t:
                elapsed = (datetime.now(UTC) - start).total_seconds()
                if errors:
                    t.status = TaskStatus.FAILED.value
                    t.error_message = "; ".join(errors)
                else:
                    t.status = TaskStatus.COMPLETED.value
                t.duration_seconds = elapsed
                t.updated_at = datetime.now(UTC).isoformat()
                if t.status == TaskStatus.COMPLETED.value:
                    self._save_artifact(db, t)
                db.commit()
                # dashboard 实时刷新：终态 publish
                await _publish_task_status(task_id, t.status)

        from dataworks_agent.metrics import task_duration, task_total

        final_status = TaskStatus.FAILED.value if errors else TaskStatus.COMPLETED.value
        task_total.labels(status=final_status).inc()
        task_duration.labels(layer=request.target_layer.value).observe(
            (datetime.now(UTC) - start).total_seconds()
        )
        logger.info(
            "任务 %s 完成: %s", task_id, "成功" if not errors else f"失败 ({'; '.join(errors)})"
        )

    def _save_artifact(self, db, task):
        """保存生成产物到 artifacts 表。"""
        # 同时归档到文件
        from datetime import datetime
        from pathlib import Path

        from dataworks_agent.db.models import ArtifactModel

        archive_dir = Path(settings.archive_dir) / datetime.now().strftime("%Y-%m")
        archive_dir.mkdir(parents=True, exist_ok=True)
        filepath = archive_dir / f"{task.target_table}.sql"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"-- Task: {task.task_id}\n-- {datetime.now().isoformat()}\n\n")
            f.write(f"-- DEV DDL:\n{task.ddl_dev}\n\n-- DML:\n{task.dml}\n")

        artifact = ArtifactModel(
            task_id=task.task_id,
            table_name=task.target_table,
            ddl_dev=task.ddl_dev,
            ddl_prod=task.ddl_prod,
            dml=task.dml,
            schedule_config_json=task.schedule_config_json,
        )
        db.add(artifact)

    async def _run_dwd_pipeline(
        self,
        task_id: str,
        request: CreateTaskRequest,
        target_table: str,
        client_ip: str,
        start: Any,
        errors: list[str],
    ) -> None:
        """DWD 专用流程：使用 DWD DDL/SQL 生成器 + 节点创建。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel
        from dataworks_agent.modeling.dwd.ddl_generator import DwdDDLGenerator
        from dataworks_agent.modeling.dwd.metadata import build_structured_metadata
        from dataworks_agent.modeling.dwd.sql_generator import DwdSQLGenerator

        bff = getattr(app_state, "_bff_client", None)
        # 节点操作优先 AK/SK 适配器、建表优先 AK/SK MaxCompute；缺则降级 bff（Task 8a/8b）
        nodes = getattr(app_state, "_node_client", None) or bff
        mc = getattr(app_state, "_maxcompute_client", None)
        if not nodes:
            errors.append("节点客户端不可用")
            await self._finalize_task(task_id, errors, start)
            return

        ddl_gen = DwdDDLGenerator()
        sql_gen = DwdSQLGenerator()
        metadata = build_structured_metadata(request.dwd_metadata)

        # Step 1: DDL 生成
        with SessionLocal() as db:
            t = db.get(ModelingTaskModel, task_id)
            if t:
                t.status = TaskStatus.DDL_GEN.value
                db.commit()
                await _publish_task_status(task_id, TaskStatus.DDL_GEN.value)

        try:
            ddl_text = ddl_gen.from_structured_metadata(request.dwd_metadata)
            ddl_text = ddl_gen.generate(ddl_text)
        except Exception as e:
            errors.append(f"DWD DDL生成: {e}")
            await self._finalize_task(task_id, errors, start)
            return

        # Step 2: 建表
        with SessionLocal() as db:
            t = db.get(ModelingTaskModel, task_id)
            if t:
                t.status = TaskStatus.TABLE_CRE.value
                t.ddl_dev = ddl_text
                db.commit()
                await _publish_task_status(task_id, TaskStatus.TABLE_CRE.value)

        from dataworks_agent.services.ods_di.di_config import (
            inject_schema_prefix_in_ddl,
            strip_leading_drop_table,
        )

        dev = settings.dataworks_dev_schema
        try:
            if mc is not None:
                # AK/SK MaxCompute：存在性检查 + CREATE（剥离 DROP 避开破坏性护栏）
                if await mc.table_exists(target_table, project=dev):
                    logger.info("DWD 表已存在: %s", target_table)
                else:
                    ddl_exec = strip_leading_drop_table(inject_schema_prefix_in_ddl(ddl_text, dev))
                    res = await mc.execute_ddl(ddl_exec)
                    if not res.success:
                        errors.append(f"DWD 建表执行失败: {res.error or ''}")
                    else:
                        logger.info("DWD 建表成功: %s", target_table)
            else:
                # 降级：bff IDA
                table_guid = f"odps.{dev}.{target_table}"
                existing = await bff.get_creation_ddl(table_guid)
                if existing:
                    logger.info("DWD 表已存在: %s", target_table)
                else:
                    ddl_exec = inject_schema_prefix_in_ddl(ddl_text, dev)
                    job_code = await bff.execute_sql_ida(ddl_exec)
                    if not job_code:
                        errors.append(f"DWD 建表失败: {bff.last_error or 'IDA 无权限'}")
                    else:
                        ok = await bff.wait_ida_job(job_code)
                        if not ok:
                            errors.append(f"DWD 建表执行失败: {bff.last_error or ''}")
                        else:
                            logger.info("DWD 建表成功: %s", target_table)
        except Exception as e:
            errors.append(f"DWD 建表异常: {e}")

        if any("建表" in e for e in errors):
            await self._finalize_task(task_id, errors, start)
            return

        # Step 3: DML 生成
        with SessionLocal() as db:
            t = db.get(ModelingTaskModel, task_id)
            if t:
                t.status = TaskStatus.DML_WRITE.value
                db.commit()
                await _publish_task_status(task_id, TaskStatus.DML_WRITE.value)

        try:
            sql_text = sql_gen.generate(metadata)
            with SessionLocal() as db:
                t = db.get(ModelingTaskModel, task_id)
                if t:
                    t.dml = sql_text
                    db.commit()
        except Exception as e:
            errors.append(f"DWD DML生成: {e}")

        # Step 4: 节点创建 + 调度 + 发布
        from dataworks_agent.naming import generate_node_path
        from dataworks_agent.naming.schedule import generate_cron, infer_schedule_type

        node_path = generate_node_path("dataworks_agent/02_DWD", target_table)
        cycle_type = infer_schedule_type(target_table)
        granularity = "hour" if cycle_type == "NotDaily" else "day"
        cron = generate_cron(granularity, hour=3 if cycle_type == "Daily" else 0, minute=1)

        with SessionLocal() as db:
            t = db.get(ModelingTaskModel, task_id)
            if t:
                t.status = TaskStatus.SCHED_CFG.value
                db.commit()
                await _publish_task_status(task_id, TaskStatus.SCHED_CFG.value)

        node_uuid = await nodes.create_node(target_table, node_path, language="odps-sql")
        if node_uuid:
            await nodes.update_node(node_uuid, sql_text)
            await nodes.update_vertex(
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
                    "script": {"parameters": []},
                    "strategy": {"instanceMode": "Immediately"},
                    "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
                },
            )
            deployed = await nodes.deploy_nodes([node_uuid], comment=f"auto deploy {target_table}")
            if not deployed:
                errors.append("DWD 节点发布失败")

            with SessionLocal() as db:
                t = db.get(ModelingTaskModel, task_id)
                if t:
                    t.node_uuid = node_uuid
                    t.node_name = target_table
        else:
            errors.append(f"DWD 节点创建失败: {bff.last_error or ''}")

        await self._finalize_task(task_id, errors, start)

    async def _finalize_task(self, task_id: str, errors: list[str], start: Any) -> None:
        """标记任务完成/失败。"""
        from datetime import datetime

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            t = db.get(ModelingTaskModel, task_id)
            if t:
                elapsed = (datetime.now(UTC) - start).total_seconds()
                if errors:
                    t.status = TaskStatus.FAILED.value
                    t.error_message = "; ".join(errors)
                else:
                    t.status = TaskStatus.COMPLETED.value
                t.duration_seconds = elapsed
                t.updated_at = datetime.now(UTC).isoformat()
                if t.status == TaskStatus.COMPLETED.value:
                    self._save_artifact(db, t)
                db.commit()
                # dashboard 实时刷新：_finalize_task 终态 publish
                await _publish_task_status(task_id, t.status)

        from dataworks_agent.metrics import task_duration, task_total

        final_status = TaskStatus.FAILED.value if errors else TaskStatus.COMPLETED.value
        task_total.labels(status=final_status).inc()
        task_duration.labels(layer="DWD").observe((datetime.now(UTC) - start).total_seconds())
        logger.info(
            "任务 %s 完成: %s", task_id, "成功" if not errors else f"失败 ({'; '.join(errors)})"
        )
