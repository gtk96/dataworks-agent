"""批量部署 API — ODS/DWD 批量建表 + 节点创建。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS, generate_cron, get_cycle_type

router = APIRouter()
logger = logging.getLogger(__name__)


class BatchDeployRequest(BaseModel):
    ddl_dir: str
    dml_dir: str = ""
    node_path: str = "dataworks_agent/01_ODS"
    mc_project: str = "dataworks"
    mc_dev_project: str = "dataworks_dev"
    schedule_minute: int = 1
    layer: str = "ODS"  # ODS / DWD


async def _execute_ddl(bff: Any, mc: Any, sql: str) -> bool:
    """建表 DDL：AK/SK MaxCompute(剥离 DROP) 优先，缺则降级 bff 资源组。"""
    from dataworks_agent.services.ods_di.di_config import strip_leading_drop_table

    if mc is not None:
        res = await mc.execute_ddl(strip_leading_drop_table(sql))
        if not res.success:
            logger.warning("DDL 执行失败(MaxCompute): %s", res.error)
        return res.success
    job_code = await bff.execute_sql(sql)
    if not job_code:
        logger.warning("SQL 执行失败: %s", bff.last_error)
        return False
    return await bff.wait_job(job_code)


def _parse_ddl_file(ddl_content: str, layer: str) -> list[dict]:
    """解析 DDL 文件，提取每个表的 DDL。"""
    tables = []
    current_table = None
    current_ddl_lines = []

    prefix = "ods_" if layer == "ODS" else "dwd_"

    for line in ddl_content.split("\n"):
        line_stripped = line.strip()

        # 匹配注释中的表名
        if line_stripped.startswith(f"-- {prefix}"):
            if current_table and current_ddl_lines:
                tables.append(
                    {"table_name": current_table, "ddl": "\n".join(current_ddl_lines).strip()}
                )
            current_table = line_stripped.lstrip("- ").split()[0]
            current_ddl_lines = []
            continue

        # 匹配 drop table 语句
        drop_match = re.match(
            r"drop\s+table\s+if\s+exists\s+\S+\.(" + prefix + r"\w+)", line_stripped, re.IGNORECASE
        )
        if drop_match:
            if current_table and current_ddl_lines:
                tables.append(
                    {"table_name": current_table, "ddl": "\n".join(current_ddl_lines).strip()}
                )
            current_table = drop_match.group(1)
            current_ddl_lines = [line]
            continue

        if current_table:
            current_ddl_lines.append(line)
            if line_stripped == ";":
                tables.append(
                    {"table_name": current_table, "ddl": "\n".join(current_ddl_lines).strip()}
                )
                current_table = None
                current_ddl_lines = []

    if current_table and current_ddl_lines:
        tables.append({"table_name": current_table, "ddl": "\n".join(current_ddl_lines).strip()})

    return tables


def _extract_dml(dml_content: str, table_name: str) -> str | None:
    """从 DML 文件中提取指定表的 DML。"""
    pattern = (
        rf"(insert\s+(?:overwrite\s+)?(?:into\s+)?(?:table\s+)?\S*{re.escape(table_name)}\b.*?;)"
    )
    match = re.search(pattern, dml_content, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


async def _deploy_table(
    bff: Any,
    nodes: Any,
    mc: Any,
    table_name: str,
    ddl: str,
    dml: str | None,
    *,
    mc_project: str,
    mc_dev_project: str,
    node_path: str,
    schedule_minute: int,
    language: str = "odps-sql",
) -> dict:
    """部署单个表。建表走 AK/SK MaxCompute、节点走 AK/SK 适配器（缺则降级 bff）。"""
    result = {"table": table_name, "success": True, "steps": {}, "error": ""}

    # 检查节点是否已存在
    node_path_full = generate_node_path(node_path, table_name)
    existing_uuid = await nodes.get_node_uuid_by_path(node_path_full)
    if existing_uuid:
        result["steps"]["skipped"] = {"reason": "node_exists", "uuid": existing_uuid}
        return result

    # 创建 MC 表（dev）
    ddl_dev = ddl.replace(
        f"drop table if exists {table_name}", f"drop table if exists {mc_dev_project}.{table_name}"
    ).replace(f"create table {table_name}", f"create table {mc_dev_project}.{table_name}")
    ok = await _execute_ddl(bff, mc, ddl_dev)
    result["steps"]["mc_dev"] = {"status": "ok" if ok else "failed"}
    if not ok:
        result["success"] = False
        result["error"] = "MC dev 建表失败"
        return result

    # 创建 MC 表（prod）
    ddl_prod = ddl_dev.replace(f"{mc_dev_project}.{table_name}", f"{mc_project}.{table_name}")
    ok = await _execute_ddl(bff, mc, ddl_prod)
    result["steps"]["mc_prod"] = {"status": "ok" if ok else "failed"}

    # 创建节点
    if dml:
        cron = generate_cron("hour", minute=schedule_minute)
        cycle_type = get_cycle_type("hour")
        uid = await nodes.create_node(table_name, node_path_full, language=language)
        if uid:
            await nodes.update_node(uid, dml)
            await nodes.update_vertex(
                uid,
                {
                    "trigger": {
                        "type": "Scheduler",
                        "cron": cron,
                        "cycleType": cycle_type,
                        "startTime": "1970-01-01 00:00:00",
                        "endTime": "9999-01-01 00:00:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "script": {"parameters": HOURLY_SQL_PARAMETERS},
                    "strategy": {"instanceMode": "Immediately"},
                    "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
                    "outputs": {
                        "nodeOutputs": [
                            {
                                "data": uid,
                                "refTableName": table_name,
                                "artifactType": "NodeOutput",
                                "sourceType": "System",
                                "isDefault": True,
                            }
                        ]
                    },
                },
            )
            result["steps"]["node"] = {"status": "ok", "uuid": uid}
        else:
            result["steps"]["node"] = {
                "status": "failed",
                "error": getattr(nodes, "last_error", None) or "创建节点失败",
            }

    return result


@router.post("/batch-deploy")
async def batch_deploy(body: BatchDeployRequest):
    """批量部署 ODS/DWD 表。"""
    from dataworks_agent.state import app_state

    bff = getattr(app_state, "_bff_client", None)
    nodes = getattr(app_state, "_node_client", None) or bff
    mc = getattr(app_state, "_maxcompute_client", None)
    if not nodes and not mc:
        raise HTTPException(status_code=503, detail="执行客户端不可用")

    ddl_path = Path(body.ddl_dir)
    if not ddl_path.exists():
        raise HTTPException(status_code=400, detail=f"DDL 目录不存在: {body.ddl_dir}")

    # 解析 DDL 文件
    all_tables = []
    for ddl_file in sorted(ddl_path.glob("*.sql")):
        content = ddl_file.read_text(encoding="utf-8", errors="ignore")
        tables = _parse_ddl_file(content, body.layer)
        all_tables.extend(tables)

    if not all_tables:
        raise HTTPException(status_code=400, detail="未解析到任何表")

    # 读取 DML 文件
    dml_contents: dict[str, str] = {}
    if body.dml_dir:
        dml_path = Path(body.dml_dir)
        if dml_path.exists():
            for f in dml_path.glob("*.sql"):
                dml_contents[f.stem] = f.read_text(encoding="utf-8", errors="ignore")

    # 部署
    language = "holo" if body.layer == "ODS" else "odps-sql"
    results = []
    for table_info in all_tables:
        table_name = table_info["table_name"]
        ddl = table_info["ddl"]

        dml = None
        for content in dml_contents.values():
            extracted = _extract_dml(content, table_name)
            if extracted:
                dml = extracted
                break

        result = await _deploy_table(
            bff,
            nodes,
            mc,
            table_name,
            ddl,
            dml,
            mc_project=body.mc_project,
            mc_dev_project=body.mc_dev_project,
            node_path=body.node_path,
            schedule_minute=body.schedule_minute,
            language=language,
        )
        results.append(result)

    success = sum(1 for r in results if r["success"])
    return {
        "status": "ok",
        "total": len(results),
        "success": success,
        "failed": len(results) - success,
        "results": results,
    }
