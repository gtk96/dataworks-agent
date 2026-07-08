"""批量部署 DIM 表到 DataWorks(日全量, MaxCompute)。

流程:
1. 解析 DDL 文件,提取每个表的 DDL
2. 在 dataworks_dev / dataworks 上执行 DDL 建表(create table if not exists, 不动历史)
3. 创建 ODPS SQL 节点,写 DML,配 Daily 调度 + DAILY_SQL_PARAMETERS
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import get_schedule_config

logger = logging.getLogger(__name__)


def parse_ddl_file(ddl_content: str) -> list[dict]:
    """解析 DDL 文件,提取每个表的 DDL。关键字: create table if not exists dataworks.dim_xxx。"""
    tables: list[dict] = []
    current_table: str | None = None
    current_ddl_lines: list[str] = []

    for line in ddl_content.split("\n"):
        line_stripped = line.strip()
        # 匹配 create table [if not exists] project.dim_xxx
        create_match = re.match(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?\S+\.(dim_\w+)",
            line_stripped,
            re.IGNORECASE,
        )
        if create_match:
            if current_table and current_ddl_lines:
                tables.append({
                    "table_name": current_table,
                    "ddl": "\n".join(current_ddl_lines).strip(),
                })
            current_table = create_match.group(1)
            current_ddl_lines = [line]
            continue

        if current_table:
            current_ddl_lines.append(line)
            if line_stripped == ";":
                tables.append({
                    "table_name": current_table,
                    "ddl": "\n".join(current_ddl_lines).strip(),
                })
                current_table = None
                current_ddl_lines = []

    if current_table and current_ddl_lines:
        tables.append({
            "table_name": current_table,
            "ddl": "\n".join(current_ddl_lines).strip(),
        })
    return tables


def extract_dml_for_table(dml_content: str, table_name: str) -> str | None:
    """从 DML 文件中提取指定表的 insert overwrite 块。"""
    pattern = rf"(insert\s+overwrite\s+table\s+\S*{re.escape(table_name)}\b.*?;)"
    match = re.search(pattern, dml_content, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def rewrite_ddl_schema(ddl: str, table_name: str, target_project: str) -> str:
    """把 DDL 里的 dataworks.dim_xxx 替换成 target_project.dim_xxx。"""
    return re.sub(
        r"(create\s+table\s+(?:if\s+not\s+exists\s+)?)\S+\." + re.escape(table_name),
        rf"\1{target_project}.{table_name}",
        ddl,
        flags=re.IGNORECASE,
    )


async def execute_sql(bff, sql: str) -> bool:
    """通过资源组执行 SQL。"""
    job_code = await bff.execute_sql(sql)
    if not job_code:
        logger.warning("资源组执行失败: %s", bff.last_error)
        return False
    return await bff.wait_job(job_code)


async def deploy_dim_table(
    bff,
    table_name: str,
    ddl: str,
    dml: str | None,
    *,
    mc_project: str = "dataworks",
    mc_dev_project: str = "dataworks_dev",
    node_path: str = "业务流程/100_订单信息/MaxCompute/数据开发/01_DIM",
) -> dict:
    """部署单个 DIM 表。"""
    result = {"table": table_name, "success": True, "steps": {}, "error": ""}

    node_path_full = generate_node_path(node_path, table_name)
    existing_uuid = await bff.get_node_uuid_by_path(node_path_full)
    if existing_uuid:
        logger.info("节点已存在,跳过: %s", table_name)
        result["steps"]["skipped"] = {"reason": "node_exists", "uuid": existing_uuid}
        return result

    # Step 1: dev 建表
    ddl_dev = rewrite_ddl_schema(ddl, table_name, mc_dev_project)
    logger.info("创建 MC 表(dev): %s.%s", mc_dev_project, table_name)
    ok = await execute_sql(bff, ddl_dev)
    result["steps"]["mc_dev"] = {"status": "ok" if ok else "failed"}
    if not ok:
        result["success"] = False
        result["error"] = "MC dev 建表失败"
        return result

    # Step 2: prod 建表
    ddl_prod = rewrite_ddl_schema(ddl, table_name, mc_project)
    logger.info("创建 MC 表(prod): %s.%s", mc_project, table_name)
    ok = await execute_sql(bff, ddl_prod)
    result["steps"]["mc_prod"] = {"status": "ok" if ok else "failed"}

    # Step 3: 创建节点 + 写 DML + 配 Daily 调度
    if dml:
        logger.info("创建 DIM 节点: %s", table_name)
        sched = get_schedule_config("all")
        uid = await bff.create_node(table_name, node_path_full, language="odps-sql")
        if uid:
            await bff.update_node(uid, dml)
            await bff.update_vertex(uid, {
                "trigger": {
                    "type": "Scheduler",
                    "cron": sched["cron"],
                    "cycleType": sched["cycle_type"],
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": sched["parameters"]},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
                "outputs": {"nodeOutputs": [
                    {"data": uid, "refTableName": table_name, "artifactType": "NodeOutput",
                     "sourceType": "System", "isDefault": True}
                ]},
            })
            result["steps"]["dim_node"] = {"status": "ok", "uuid": uid}
        else:
            result["steps"]["dim_node"] = {"status": "failed", "error": bff.last_error}

    return result


async def deploy_batch(
    ddl_dir: str,
    dml_dir: str | None = None,
    *,
    mc_project: str = "dataworks",
    mc_dev_project: str = "dataworks_dev",
    node_path: str = "业务流程/100_订单信息/MaxCompute/数据开发/01_DIM",
    tables_filter: list[str] | None = None,
) -> list[dict]:
    """批量部署 DIM 表。"""
    ddl_path = Path(ddl_dir)
    if not ddl_path.exists():
        raise FileNotFoundError(f"DDL 目录不存在: {ddl_dir}")

    all_tables: list[dict] = []
    for ddl_file in sorted(ddl_path.glob("*.sql")):
        content = ddl_file.read_text(encoding="utf-8")
        tables = parse_ddl_file(content)
        for t in tables:
            t["ddl_file"] = str(ddl_file)
        all_tables.extend(tables)

    if tables_filter:
        all_tables = [t for t in all_tables if t["table_name"] in tables_filter]

    logger.info("解析到 %d 个 DIM 表", len(all_tables))

    dml_contents: dict[str, str] = {}
    if dml_dir:
        dml_path = Path(dml_dir)
        if dml_path.exists():
            for dml_file in dml_path.glob("*.sql"):
                dml_contents[dml_file.stem] = dml_file.read_text(encoding="utf-8")

    bff = DataWorksClient()
    results: list[dict] = []

    for table_info in all_tables:
        table_name = table_info["table_name"]
        ddl = table_info["ddl"]

        dml = None
        for _stem, content in dml_contents.items():
            extracted = extract_dml_for_table(content, table_name)
            if extracted:
                dml = extracted
                break

        result = await deploy_dim_table(
            bff, table_name, ddl, dml,
            mc_project=mc_project, mc_dev_project=mc_dev_project,
            node_path=node_path,
        )
        results.append(result)
        status = "OK" if result["success"] else "FAIL"
        logger.info("[%s] %s: %s", status, table_name, result["steps"])

    await bff.close()
    return results


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ddl_dir = r"E:\dw-modeling-template\sql\order-fulfillment\dim\ddl"
    dml_dir = r"E:\dw-modeling-template\sql\order-fulfillment\dim\dml"

    results = await deploy_batch(ddl_dir=ddl_dir, dml_dir=dml_dir)

    success = sum(1 for r in results if r["success"])
    total = len(results)
    print(f"\nDIM 部署完成: {success}/{total} 成功")
    for r in results:
        status = "OK" if r["success"] else "FAIL"
        print(f"  [{status}] {r['table']}")
        if r.get("error"):
            print(f"        错误: {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
