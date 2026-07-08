"""批量部署 ODS 表到 DataWorks。

完整流程：
1. 解析 DDL 文件，提取每个表的 DDL
2. 用资源组执行 DDL 建表（dev + prod）
3. 创建 Holo SQL 节点（完整配置）
4. 执行 IMPORT FOREIGN SCHEMA 后注释掉
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS, generate_cron, get_cycle_type
from dataworks_agent.services.ods_holo import extract_dml_for_table

logger = logging.getLogger(__name__)


def parse_ddl_file(ddl_content: str) -> list[dict]:
    """解析 DDL 文件，提取每个表的 DDL。"""
    tables = []
    current_table = None
    current_ddl_lines = []

    for line in ddl_content.split("\n"):
        line_stripped = line.strip()

        if line_stripped.startswith("-- ods_hl_") or line_stripped.startswith("-- ods_mc_"):
            if current_table and current_ddl_lines:
                tables.append(
                    {
                        "table_name": current_table,
                        "ddl": "\n".join(current_ddl_lines).strip(),
                    }
                )
            current_table = line_stripped.lstrip("- ").split()[0]
            current_ddl_lines = []
            continue

        if current_table:
            current_ddl_lines.append(line)

    if current_table and current_ddl_lines:
        tables.append(
            {
                "table_name": current_table,
                "ddl": "\n".join(current_ddl_lines).strip(),
            }
        )

    return tables


async def execute_sql_via_resource_group(bff: Any, sql: str) -> bool:
    """通过资源组执行 SQL。"""
    job_code = await bff.execute_sql(sql)
    if not job_code:
        logger.warning("资源组执行失败: %s", bff.last_error)
        return False
    return await bff.wait_job(job_code)


async def deploy_ods_table(
    bff: Any,
    table_name: str,
    ddl: str,
    dml: str | None,
    *,
    mc_project: str = "dataworks",
    mc_dev_project: str = "dataworks_dev",
    node_path: str = "dataworks_agent/01_ODS",
    schedule_minute: int = 1,
) -> dict:
    """部署单个 ODS 表（完整流程）。"""
    result = {
        "table": table_name,
        "success": True,
        "steps": {},
        "error": "",
    }

    # Step 1: 检查节点是否已存在
    if dml:
        node_path_full = generate_node_path(node_path, table_name)
        existing_uuid = await bff.get_node_uuid_by_path(node_path_full)
        if existing_uuid:
            logger.info("节点已存在，跳过: %s", table_name)
            result["steps"]["skipped"] = {"reason": "node_exists", "uuid": existing_uuid}
            return result

    # Step 2: 创建 MC 表（prod）
    logger.info("创建 MC 表: %s.%s", mc_project, table_name)
    ddl_prod = ddl.replace(
        f"drop table if exists {table_name}",
        f"drop table if exists {mc_project}.{table_name}",
    ).replace(
        f"create table {table_name}",
        f"create table {mc_project}.{table_name}",
    )
    ok = await execute_sql_via_resource_group(bff, ddl_prod)
    result["steps"]["mc_prod"] = {"status": "ok" if ok else "failed"}
    if not ok:
        result["success"] = False
        result["error"] = "MC prod 建表失败"
        return result

    # Step 2: 创建 MC 表（dev）
    logger.info("创建 MC 表: %s.%s", mc_dev_project, table_name)
    ddl_dev = ddl_prod.replace(f"{mc_project}.{table_name}", f"{mc_dev_project}.{table_name}")
    ok = await execute_sql_via_resource_group(bff, ddl_dev)
    result["steps"]["mc_dev"] = {"status": "ok" if ok else "failed"}

    # Step 3: 创建 Holo SQL 节点（完整配置）
    if dml:
        logger.info("创建 Holo SQL 节点: %s", table_name)
        node_path_full = generate_node_path(node_path, table_name)
        cron = generate_cron("hour", minute=schedule_minute)
        cycle_type = get_cycle_type("hour")
        parameters = HOURLY_SQL_PARAMETERS

        uid = await bff.create_node(table_name, node_path_full, language="holo")
        action = "created"

        if uid:
            # 写入 DML
            await bff.update_node(uid, dml)

            # 配置完整调度
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
                    "script": {"parameters": parameters},
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

            # 执行 IMPORT FOREIGN SCHEMA
            import_sql = f"IMPORT FOREIGN SCHEMA dataworks LIMIT TO ({table_name}) FROM SERVER odps_server INTO cda OPTIONS (if_table_exist 'update');"
            import_ok = False
            job_code = await bff.execute_sql_ida(import_sql)
            if job_code:
                await bff.wait_ida_job(job_code)
                import_ok = True
            else:
                job_code = await bff.execute_sql(import_sql)
                if job_code:
                    await bff.wait_job(job_code)
                    import_ok = True

            # 注释掉 IMPORT FOREIGN SCHEMA
            from dataworks_agent.services.ods_holo.dml_generator import comment_out_import

            dml_commented = comment_out_import(dml)
            await bff.update_node(uid, dml_commented)

            # 格式化 DML（需要 Chrome CDP 连接）
            try:
                from dataworks_agent.state import app_state

                cdp = getattr(app_state, "_cdp_client", None)
                if cdp:
                    await cdp.format_and_save()
                    logger.info("DML 格式化完成: %s", table_name)
                else:
                    logger.debug("CDP 不可用，跳过格式化: %s", table_name)
            except Exception as e:
                logger.debug("格式化跳过: %s - %s", table_name, e)

            result["steps"]["holo_node"] = {
                "status": "ok",
                "uuid": uid,
                "action": action,
                "import_schema": "ok" if import_ok else "failed",
            }
        else:
            result["steps"]["holo_node"] = {
                "status": "failed",
                "error": bff.last_error or "创建节点失败",
            }

    return result


async def deploy_batch(
    ddl_file: str,
    dml_file: str | None = None,
    *,
    mc_project: str = "dataworks",
    mc_dev_project: str = "dataworks_dev",
    node_path: str = "dataworks_agent/01_ODS",
    schedule_minute: int = 1,
    tables_filter: list[str] | None = None,
) -> list[dict]:
    """批量部署 ODS 表。"""
    ddl_path = Path(ddl_file)
    if not ddl_path.exists():
        raise FileNotFoundError(f"DDL 文件不存在: {ddl_file}")

    ddl_content = ddl_path.read_text(encoding="utf-8")
    tables = parse_ddl_file(ddl_content)

    if tables_filter:
        tables = [t for t in tables if t["table_name"] in tables_filter]

    logger.info("解析到 %d 个表", len(tables))

    dml_content = ""
    if dml_file:
        dml_path = Path(dml_file)
        if dml_path.exists():
            dml_content = dml_path.read_text(encoding="utf-8")

    bff = DataWorksClient()

    results = []
    for table_info in tables:
        table_name = table_info["table_name"]
        ddl = table_info["ddl"]
        dml = extract_dml_for_table(dml_content, table_name) if dml_content else None

        result = await deploy_ods_table(
            bff,
            table_name,
            ddl,
            dml,
            mc_project=mc_project,
            mc_dev_project=mc_dev_project,
            node_path=node_path,
            schedule_minute=schedule_minute,
        )
        results.append(result)

        status = "OK" if result["success"] else "FAIL"
        logger.info("[%s] %s: %s", status, table_name, result["steps"])

    await bff.close()
    return results


async def main():
    """主函数：部署 OFC ODS 表。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    ddl_file = r"E:\dw-modeling-template\sql\order-fulfillment\ods\ddl\ods_hl_ofc__order_fulfillment_hour_ddl.sql"
    dml_file = r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_ofc__order_fulfillment_hour_dml.sql"

    # OFC ODS
    print("=== 部署 OFC ODS ===")
    ofc_results = await deploy_batch(
        ddl_file=ddl_file,
        dml_file=dml_file,
        mc_project="dataworks",
        mc_dev_project="dataworks_dev",
        node_path="业务流程/100_订单信息/Hologres/数据开发/00_ODS",
        schedule_minute=1,
    )

    ofc_ok = sum(1 for r in ofc_results if r["success"])
    ofc_total = len(ofc_results)
    print(f"OFC: {ofc_ok}/{ofc_total} 成功")

    # OMS ODS
    oms_ddl = r"E:\dw-modeling-template\sql\order-fulfillment\ods\ddl\ods_hl_oms__order_fulfillment_hour_ddl.sql"
    oms_dml = r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_oms__order_fulfillment_hour_dml.sql"

    print("\n=== 部署 OMS ODS ===")
    oms_results = await deploy_batch(
        ddl_file=oms_ddl,
        dml_file=oms_dml,
        mc_project="dataworks",
        mc_dev_project="dataworks_dev",
        node_path="业务流程/100_订单信息/Hologres/数据开发/00_ODS",
        schedule_minute=1,
    )

    oms_ok = sum(1 for r in oms_results if r["success"])
    oms_total = len(oms_results)
    print(f"OMS: {oms_ok}/{oms_total} 成功")

    # 汇总
    all_results = ofc_results + oms_results
    success = sum(1 for r in all_results if r["success"])
    total = len(all_results)
    print(f"\n总计: {success}/{total} 成功")

    for r in all_results:
        status = "OK" if r["success"] else "FAIL"
        print(f"  [{status}] {r['table']}")
        if r["error"]:
            print(f"        错误: {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
