"""Phase 2: init/incremental dual-task workflow and publish gate."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from dataworks_agent.config import settings
from dataworks_agent.naming import generate_node_path, generate_ods_di_table_name
from dataworks_agent.services.ods_di.create_node import build_config, create_di_node
from dataworks_agent.services.ods_di.di_config import (
    build_copy_init_partition_sql,
    build_first_incremental_where_clause,
    build_node_name,
    evaluate_publish_gate,
    partition_where_clause,
    replace_reader_where,
)
from dataworks_agent.services.ods_di.ensure_table import ensure_table
from dataworks_agent.services.ods_di.field_infer import infer_fields
from dataworks_agent.services.ods_di.sql_runner import run_ida_query

logger = logging.getLogger(__name__)


@dataclass
class InitializationConfig:
    """Options for init + incremental dual-task workflow."""

    dev_mc_project: str = ""
    prod_mc_project: str = ""
    init_partition_date: str = "20170101"
    init_partition_hour: str = "00"
    allow_empty_source: bool = False
    publish_incremental_after_init: bool = True
    copy_to_prod: bool = True
    first_incremental_lookback_hours: int | None = None


async def query_partition_count(
    bff: Any,
    *,
    project: str,
    table_name: str,
    granularity: str,
    init_partition_date: str,
    init_partition_hour: str,
) -> tuple[bool, int]:
    """Count rows in the fixed init partition via IDA."""
    where = partition_where_clause(
        granularity,
        init_partition_date=init_partition_date,
        init_partition_hour=init_partition_hour,
    )
    sql = f"SELECT COUNT(*) FROM {project}.{table_name} WHERE {where}"
    body_list = await run_ida_query(bff, sql)
    if not body_list:
        return False, 0
    try:
        return True, int(body_list[0][0])
    except (IndexError, TypeError, ValueError):
        return False, 0


async def validate_init_partition(
    bff: Any,
    *,
    project: str,
    table_name: str,
    granularity: str,
    allow_empty_source: bool = False,
    init_partition_date: str = "20170101",
    init_partition_hour: str = "00",
) -> dict[str, Any]:
    """Validate init partition row count."""
    query_ok, row_count = await query_partition_count(
        bff,
        project=project,
        table_name=table_name,
        granularity=granularity,
        init_partition_date=init_partition_date,
        init_partition_hour=init_partition_hour,
    )
    errors: list[str] = []
    if not query_ok:
        errors.append("partition_count_query_failed")
    elif row_count == 0 and not allow_empty_source:
        errors.append(
            f"empty_source_not_allowed: project={project}, table={table_name}, row_count=0"
        )

    return {
        "project": project,
        "target_row_count": row_count,
        "partition_exists": query_ok,
        "execution_errors": errors,
        "passed": query_ok and not errors,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def manual_run_init_node(
    bff: Any,
    *,
    node_path: str,
    node_name: str,
    resource_group: str | None = None,
) -> bool:
    """Execute saved init DI node once (unpublished)."""
    di_rg = resource_group or bff.di_resource_group
    if not di_rg:
        bff.last_error = "DI 资源组未配置"
        return False

    script_path = f"{node_path.rstrip('/')}/{node_name}.json"
    file_resp = await bff.get_file(script_path)
    file_info = bff.parse_ide_file(file_resp)
    script_content = file_info.get("content", "")
    node_uuid = file_info.get("uuid", "")
    package_uuid = file_info.get("bizId", "") or await bff.get_node_uuid_by_path(node_path)

    if not script_content or not node_uuid or not package_uuid:
        bff.last_error = "无法读取 init 节点脚本或 UUID"
        return False

    job_code = await bff.create_di_executor_job(
        script_content=script_content,
        resource_group_code=di_rg,
        package_uuid=str(package_uuid),
        file_name=node_name,
    )
    if not job_code:
        return False
    if not await bff.write_executor_config(
        entity_uuid=str(node_uuid),
        resource_group_identifier=di_rg,
        script_params={},
    ):
        return False

    max_retry = max(1, settings.init_di_max_wait_seconds // 5)
    return await bff.wait_job(job_code, max_retry=max_retry, interval=5)


async def run_four_phases(
    bff: Any,
    mcp: Any,
    *,
    datasource_name: str,
    source_table: str,
    ods_table: str,
    node_name: str,
    node_path: str,
    granularity: str,
    field_info: dict[str, Any] | None,
    task_role: Literal["init", "incremental"],
    mc_project: str,
    schedule_minute: int,
    resource_group: str,
    source_type: str | None,
    node_client: Any = None,
    mc_client: Any = None,
) -> dict[str, Any]:
    """Run phases 1–4 for one task role."""
    steps: dict[str, Any] = {}

    if field_info is None:
        field_info = await infer_fields(bff, mcp, datasource_name, source_table, granularity)
    steps["field_infer"] = field_info
    if field_info.get("status") != "ok":
        return {"success": False, "steps": steps}

    table_step = await ensure_table(
        bff,
        mcp,
        datasource_name=datasource_name,
        source_table_name=source_table,
        target_table=ods_table,
        granularity=granularity,
        mc_project=mc_project,
        mc=mc_client,
    )
    steps["ensure_table"] = table_step
    if table_step.get("status") not in {"exists", "created"}:
        return {"success": False, "steps": steps}

    config_step = build_config(
        datasource_name=datasource_name,
        source_table=source_table,
        target_table=ods_table,
        columns=field_info["columns"],
        granularity=granularity,
        split_pk=field_info.get("split_pk", ""),
        where_field=field_info.get("where_field", ""),
        where_type=field_info.get("where_type", "none"),
        source_step_type=field_info.get("source_step_type", "mysql"),
        schedule_minute=schedule_minute,
        resource_group=resource_group,
        task_role=task_role,
        init_partition_date=field_info.get("init_partition_date", "20170101"),
        init_partition_hour=field_info.get("init_partition_hour", "00"),
    )
    steps["build_config"] = {
        "status": "ok",
        "cron": config_step.get("cron"),
        "cycle_type": config_step.get("cycle_type"),
        "scheduled": config_step.get("scheduled", True),
    }

    node_step = await create_di_node(
        node_client or bff,
        node_name=node_name,
        node_path=node_path,
        di_config=config_step["di_config"],
        cron=config_step.get("cron", ""),
        cycle_type=config_step.get("cycle_type", "NotDaily"),
        parameters=config_step.get("parameters", []),
        schedule=config_step.get("scheduled", True),
    )
    steps["create_node"] = node_step
    success = bool(node_step.get("uuid"))
    return {
        "success": success,
        "steps": steps,
        "standard_ddl": table_step.get("standard_ddl", ""),
        "di_config": config_step["di_config"],
        "field_info": field_info,
    }


async def apply_first_incremental_lookback(
    bff: Any,
    *,
    incr_uuid: str,
    di_config: dict[str, Any],
    where_field: str,
    where_type: str,
    granularity: str,
    lookback_hours: int,
) -> dict[str, Any]:
    """改写 incremental 节点首跑 Reader.where 为 lookback 兜底窗口。

    init 跑完后、首次增量调度前，标准增量窗口(bizdate/gmtdate_last2h)可能漏采
    init 与首跑之间的数据。用 first_incremental_lookback_hours 把首跑窗口向前
    扩展 lookback_hours，重写并落库到 incremental 节点脚本。

    仅改写首跑窗口：调度系统此后每次运行仍按节点自身 cron 走标准增量窗口，
    故只在建节点后、发布前执行一次。
    """
    if not where_field:
        return {"status": "skipped", "reason": "no where_field"}
    try:
        where_clause = build_first_incremental_where_clause(
            where_type, where_field, granularity, lookback_hours
        )
    except ValueError as e:
        return {"status": "failed", "error": str(e)}
    updated = replace_reader_where(di_config, where_clause)
    ok = await bff.update_node(incr_uuid, json.dumps(updated, ensure_ascii=False))
    if not ok:
        return {"status": "failed", "error": bff.last_error or "update_node 失败"}
    return {"status": "ok", "where": where_clause}


async def run_with_initialization(
    bff: Any,
    mcp: Any,
    *,
    datasource_name: str,
    source_table: str,
    granularity: str = "hour",
    script_path: str = "dataworks_agent/01_ODS",
    schedule_minute: int = 1,
    resource_group: str = "",
    source_type: str | None = "hologres",
    target_table: str | None = None,
    init_config: InitializationConfig | None = None,
    node_client: Any = None,
    mc_client: Any = None,
) -> dict[str, Any]:
    """Run init + incremental workflow with an explicit dev-only safe mode."""
    if target_table is not None:
        from dataworks_agent.schemas import assert_safe_table_name

        assert_safe_table_name(target_table)

    cfg = init_config or InitializationConfig()
    dev_project = cfg.dev_mc_project or settings.dataworks_dev_schema
    prod_project = cfg.prod_mc_project or settings.dataworks_prod_schema
    rg = resource_group or settings.dataworks_resource_group
    nodes = node_client or bff

    ods_table = target_table or generate_ods_di_table_name(
        datasource_name, source_table, granularity, source_type=source_type
    )
    init_node_name = build_node_name(ods_table, "init")
    incr_node_name = build_node_name(ods_table, "incremental")
    init_path = generate_node_path(script_path, init_node_name)
    incr_path = generate_node_path(script_path, incr_node_name)

    result: dict[str, Any] = {
        "target_table": ods_table,
        "success": True,
        "execution_scope": "dev_only" if not cfg.copy_to_prod else "dev_to_prod",
        "initialization": {},
        "incremental": {},
    }

    field_info = await infer_fields(bff, mcp, datasource_name, source_table, granularity)
    field_info["init_partition_date"] = cfg.init_partition_date
    field_info["init_partition_hour"] = cfg.init_partition_hour

    init_run = await run_four_phases(
        bff,
        mcp,
        datasource_name=datasource_name,
        source_table=source_table,
        ods_table=ods_table,
        node_name=init_node_name,
        node_path=init_path,
        granularity=granularity,
        field_info=field_info,
        task_role="init",
        mc_project=dev_project,
        schedule_minute=schedule_minute,
        resource_group=rg,
        source_type=source_type,
        node_client=nodes,
        mc_client=mc_client,
    )
    result["initialization"]["init_pipeline"] = init_run
    if not init_run.get("success"):
        result["success"] = False
        return result

    init_exec_ok = await manual_run_init_node(
        bff, node_path=init_path, node_name=init_node_name, resource_group=rg
    )
    result["initialization"]["init_run"] = {
        "status": "ok" if init_exec_ok else "failed",
        "error": bff.last_error if not init_exec_ok else "",
    }

    dev_validation = await validate_init_partition(
        bff,
        project=dev_project,
        table_name=ods_table,
        granularity=granularity,
        allow_empty_source=cfg.allow_empty_source,
        init_partition_date=cfg.init_partition_date,
        init_partition_hour=cfg.init_partition_hour,
    )
    result["initialization"]["dev_validation"] = dev_validation
    filter_valid = bool(field_info.get("where_field") or granularity in {"all", "hourly", "hour"})

    if cfg.copy_to_prod:
        prod_table = await ensure_table(
            bff,
            mcp,
            datasource_name=datasource_name,
            source_table_name=source_table,
            target_table=ods_table,
            granularity=granularity,
            mc_project=prod_project,
            mc=mc_client,
        )
        result["initialization"]["prod_ensure_table"] = prod_table
        prod_table_ok = prod_table.get("status") in {"exists", "created"}

        standard_ddl = init_run.get("standard_ddl") or prod_table.get("standard_ddl") or ""
        di_config = init_run.get("di_config") or {}
        writer_columns = ((di_config.get("steps") or [{}, {}, {}])[2].get("parameter") or {}).get(
            "column"
        ) or field_info.get("columns", [])
        copy_ok = False
        copy_job = None
        if dev_validation.get("passed"):
            copy_sql = build_copy_init_partition_sql(
                ods_table_name=ods_table,
                columns=list(writer_columns),
                granularity=granularity,
                ddl=standard_ddl or None,
                dev_project=dev_project,
                prod_project=prod_project,
                init_partition_date=cfg.init_partition_date,
                init_partition_hour=cfg.init_partition_hour,
            )
            copy_job = await bff.execute_sql_ida(copy_sql)
            copy_ok = bool(copy_job and await bff.wait_ida_job(copy_job, max_retry=36, interval=5))
        result["initialization"]["prod_copy"] = {
            "status": "ok" if copy_ok else "failed",
            "job_code": copy_job,
        }
        prod_validation = await validate_init_partition(
            bff,
            project=prod_project,
            table_name=ods_table,
            granularity=granularity,
            allow_empty_source=cfg.allow_empty_source,
            init_partition_date=cfg.init_partition_date,
            init_partition_hour=cfg.init_partition_hour,
        )
        result["initialization"]["prod_validation"] = prod_validation
        dev_count = int(dev_validation.get("target_row_count") or 0)
        prod_count = int(prod_validation.get("target_row_count") or 0)
        gate = evaluate_publish_gate(
            tables_created=prod_table_ok,
            init_run_succeeded=init_exec_ok,
            dev_validated=bool(dev_validation.get("passed")),
            prod_copy_succeeded=copy_ok,
            prod_validated=bool(prod_validation.get("passed")) and prod_count == dev_count,
            incremental_filter_valid=filter_valid,
        )
        incremental_project = prod_project
    else:
        for key in ("prod_ensure_table", "prod_copy", "prod_validation"):
            result["initialization"][key] = {
                "status": "skipped",
                "reason": "copy_to_prod=false",
            }
        gate = {
            "allowed": bool(init_exec_ok and dev_validation.get("passed") and filter_valid),
            "scope": "development",
            "reasons": [],
        }
        if not init_exec_ok:
            gate["reasons"].append("init_run_failed")
        if not dev_validation.get("passed"):
            gate["reasons"].append("dev_validation_failed")
        if not filter_valid:
            gate["reasons"].append("incremental_filter_invalid")
        incremental_project = dev_project

    result["publish_gate"] = gate
    if not gate.get("allowed"):
        result["success"] = False
        return result

    incr_run = await run_four_phases(
        bff,
        mcp,
        datasource_name=datasource_name,
        source_table=source_table,
        ods_table=ods_table,
        node_name=incr_node_name,
        node_path=incr_path,
        granularity=granularity,
        field_info=field_info,
        task_role="incremental",
        mc_project=incremental_project,
        schedule_minute=schedule_minute,
        resource_group=rg,
        source_type=source_type,
        node_client=nodes,
        mc_client=mc_client,
    )
    result["incremental"] = incr_run
    if not incr_run.get("success"):
        result["success"] = False
        return result

    incr_uuid = incr_run.get("steps", {}).get("create_node", {}).get("uuid")
    if incr_uuid:
        lookback = cfg.first_incremental_lookback_hours
        if lookback:
            lb_result = await apply_first_incremental_lookback(
                nodes,
                incr_uuid=str(incr_uuid),
                di_config=incr_run.get("di_config", {}),
                where_field=field_info.get("where_field", ""),
                where_type=field_info.get("where_type", "none"),
                granularity=granularity,
                lookback_hours=lookback,
            )
            result["incremental"]["first_run_lookback"] = lb_result
            if lb_result.get("status") == "failed":
                result["success"] = False
                return result
        if cfg.copy_to_prod and cfg.publish_incremental_after_init:
            deployed = await bff.deploy_nodes([str(incr_uuid)], comment=f"auto deploy {ods_table}")
            result["incremental"]["deploy"] = {"status": "ok" if deployed else "failed"}
        else:
            result["incremental"]["deploy"] = {
                "status": "skipped",
                "reason": "saved_dev_node_requires_publish_gate",
            }

    return result
