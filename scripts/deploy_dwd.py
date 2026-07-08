"""批量部署 DWD 表到 DataWorks。

流程：
1. 解析 DDL 文件，提取每个表的 DDL
2. 用资源组执行 DDL 建表（dev + prod）
3. 创建 ODPS SQL 节点（含 DML + 调度）
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.modeling.dwd.dependencies import find_ods_sources
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import DWD_SQL_PARAMETERS, generate_cron, get_cycle_type

logger = logging.getLogger(__name__)


def parse_ddl_file(ddl_content: str) -> list[dict]:
    """解析 DDL 文件，提取每个表的 DDL。"""
    tables = []
    current_table = None
    current_ddl_lines = []

    for line in ddl_content.split("\n"):
        line_stripped = line.strip()

        # 匹配 drop table if exists dwd_xxx 或 create table dwd_xxx
        drop_match = re.match(
            r"drop\s+table\s+if\s+exists\s+\S+\.(dwd_\w+)", line_stripped, re.IGNORECASE
        )
        if drop_match:
            if current_table and current_ddl_lines:
                tables.append(
                    {
                        "table_name": current_table,
                        "ddl": "\n".join(current_ddl_lines).strip(),
                    }
                )
            current_table = drop_match.group(1)
            current_ddl_lines = [line]
            continue

        if current_table:
            current_ddl_lines.append(line)
            # 遇到分号结束当前表
            if line_stripped == ";":
                tables.append(
                    {
                        "table_name": current_table,
                        "ddl": "\n".join(current_ddl_lines).strip(),
                    }
                )
                current_table = None
                current_ddl_lines = []

    if current_table and current_ddl_lines:
        tables.append(
            {
                "table_name": current_table,
                "ddl": "\n".join(current_ddl_lines).strip(),
            }
        )

    return tables


def extract_dml_for_table(dml_content: str, table_name: str) -> str | None:
    """从 DML 文件中提取指定表的 DML。"""
    # 匹配 insert overwrite table dev.table_name
    pattern = rf"(insert\s+overwrite\s+table\s+\S*{re.escape(table_name)}\b.*?;)"
    match = re.search(pattern, dml_content, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


async def execute_sql(bff, sql: str) -> bool:
    """通过资源组执行 SQL。"""
    job_code = await bff.execute_sql(sql)
    if not job_code:
        logger.warning("资源组执行失败: %s", bff.last_error)
        return False
    return await bff.wait_job(job_code)


async def deploy_dwd_table(
    bff,
    table_name: str,
    ddl: str,
    dml: str | None,
    *,
    mc_project: str = "dataworks",
    mc_dev_project: str = "dataworks_dev",
    node_path: str = "业务流程/DWD/MaxCompute",
    schedule_minute: int = 1,
    ods_uuids: dict[str, str] | None = None,
) -> dict:
    """部署单个 DWD 表。"""
    result = {"table": table_name, "success": True, "steps": {}, "error": ""}
    ods_uuids = ods_uuids or {}

    # Step 1: 检查节点是否已存在
    node_path_full = generate_node_path(node_path, table_name)
    existing_uuid = await bff.get_node_uuid_by_path(node_path_full)
    if existing_uuid:
        logger.info("节点已存在，跳过: %s", table_name)
        result["steps"]["skipped"] = {"reason": "node_exists", "uuid": existing_uuid}
        return result

    # Step 2: 创建 MC 表（dev）
    logger.info("创建 MC 表: %s.%s", mc_dev_project, table_name)
    ddl_dev = ddl.replace(
        f"drop table if exists {table_name}",
        f"drop table if exists {mc_dev_project}.{table_name}",
    ).replace(
        f"create table {table_name}",
        f"create table {mc_dev_project}.{table_name}",
    )
    ok = await execute_sql(bff, ddl_dev)
    result["steps"]["mc_dev"] = {"status": "ok" if ok else "failed"}
    if not ok:
        result["success"] = False
        result["error"] = "MC dev 建表失败"
        return result

    # Step 3: 创建 MC 表（prod）
    logger.info("创建 MC 表: %s.%s", mc_project, table_name)
    ddl_prod = ddl_dev.replace(f"{mc_dev_project}.{table_name}", f"{mc_project}.{table_name}")
    ok = await execute_sql(bff, ddl_prod)
    result["steps"]["mc_prod"] = {"status": "ok" if ok else "failed"}

    # Step 4: 创建 ODPS SQL 节点
    if dml:
        logger.info("创建 DWD 节点: %s", table_name)
        cron = generate_cron("hour", minute=schedule_minute)
        cycle_type = get_cycle_type("hour")

        uid = await bff.create_node(table_name, node_path_full, language="odps-sql")
        if uid:
            await bff.update_node(uid, dml)

            # 从 DML 提取所有上游 ODS 表（1:N）
            ods_sources = find_ods_sources(dml)
            deps: list[dict] = [{"type": "CrossCycleDependsOnSelf"}]
            for ods_src in ods_sources:
                ods_uuid = ods_uuids.get(ods_src, "")
                if ods_uuid:
                    deps.insert(0, {"type": "Normal", "output": ods_uuid, "sourceType": "System"})

            await bff.update_vertex(
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
                    "script": {"parameters": DWD_SQL_PARAMETERS},
                    "strategy": {"instanceMode": "Immediately"},
                    "dependencies": deps,
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
            result["steps"]["dwd_node"] = {"status": "ok", "uuid": uid, "ods_sources": ods_sources}
        else:
            result["steps"]["dwd_node"] = {"status": "failed", "error": bff.last_error}

    return result


async def deploy_batch(
    ddl_dir: str,
    dml_dir: str | None = None,
    *,
    mc_project: str = "dataworks",
    mc_dev_project: str = "dataworks_dev",
    node_path: str = "业务流程/DWD/MaxCompute",
    schedule_minute: int = 1,
    tables_filter: list[str] | None = None,
) -> list[dict]:
    """批量部署 DWD 表。"""
    ddl_path = Path(ddl_dir)
    if not ddl_path.exists():
        raise FileNotFoundError(f"DDL 目录不存在: {ddl_dir}")

    # 读取所有 DDL 文件
    all_tables = []
    for ddl_file in sorted(ddl_path.glob("*.sql")):
        content = ddl_file.read_text(encoding="utf-8")
        tables = parse_ddl_file(content)
        for t in tables:
            t["ddl_file"] = str(ddl_file)
        all_tables.extend(tables)

    if tables_filter:
        all_tables = [t for t in all_tables if t["table_name"] in tables_filter]

    logger.info("解析到 %d 个 DWD 表", len(all_tables))

    # 读取 DML 文件
    dml_contents: dict[str, str] = {}
    if dml_dir:
        dml_path = Path(dml_dir)
        if dml_path.exists():
            for dml_file in dml_path.glob("*.sql"):
                dml_contents[dml_file.stem] = dml_file.read_text(encoding="utf-8")

    bff = DataWorksClient()

    # 预抓取 ODS 节点 uuid（用于 1:N 依赖）
    ods_uuids: dict[str, str] = {}
    try:
        ods_search = await bff._get(
            "ide/searchFiles",
            {
                "projectId": bff.project_id,
                "keyword": "ods_hl_",
                "scene": "DATAWORKS_PROJECT",
                "pageSize": 200,
            },
        )
        for h in (ods_search.get("data") or {}).get("data", {}).get("hits", []) or []:
            path = h.get("path", "")
            if "00_ODS" in path:
                name = h.get("name", "").replace(".sql", "")
                v_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
                if v_uuid:
                    ods_uuids[name] = v_uuid
        logger.info("预抓取 ODS uuid: %d", len(ods_uuids))
    except Exception as e:
        logger.warning("预抓取 ODS uuid 失败（将使用 1:1 依赖）: %s", e)

    results = []

    for table_info in all_tables:
        table_name = table_info["table_name"]
        ddl = table_info["ddl"]

        # 查找对应的 DML
        dml = None
        for _stem, content in dml_contents.items():
            extracted = extract_dml_for_table(content, table_name)
            if extracted:
                dml = extracted
                break

        result = await deploy_dwd_table(
            bff,
            table_name,
            ddl,
            dml,
            mc_project=mc_project,
            mc_dev_project=mc_dev_project,
            node_path=node_path,
            schedule_minute=schedule_minute,
            ods_uuids=ods_uuids,
        )
        results.append(result)

        status = "OK" if result["success"] else "FAIL"
        logger.info("[%s] %s: %s", status, table_name, result["steps"])

    await bff.close()
    return results


async def main():
    """主函数：部署 DWD 表。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ddl_dir = r"E:\dw-modeling-template\sql\order-fulfillment\dwd\ddl"
    dml_dir = r"E:\dw-modeling-template\sql\order-fulfillment\dwd\dml"

    results = await deploy_batch(
        ddl_dir=ddl_dir,
        dml_dir=dml_dir,
        mc_project="dataworks",
        mc_dev_project="dataworks_dev",
        node_path="业务流程/DWD/MaxCompute",
        schedule_minute=1,
    )

    success = sum(1 for r in results if r["success"])
    total = len(results)
    print(f"\nDWD 部署完成: {success}/{total} 成功")

    for r in results:
        status = "OK" if r["success"] else "FAIL"
        print(f"  [{status}] {r['table']}")
        if r.get("error"):
            print(f"        错误: {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
