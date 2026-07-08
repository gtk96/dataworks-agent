"""一次性脚本：DWD 词根规范表 drop+create + 推送 DML。

源 DDL: E:/dw-modeling-template/sql/order-fulfillment/dwd/ddl/  (25 张，硬编码 dataworks schema)
源 DML: E:/dw-modeling-template/sql/order-fulfillment/dwd/dml/  (25 张，硬编码 dataworks schema)

流程（每张表）：
  1. 把源 DDL 中的 dataworks. 替换成 dataworks_dev.，得到 dev DDL
  2. dev DDL 通过资源组执行 → 建 dev 表
  3. prod DDL（源 DDL）通过资源组执行 → drop+create prod 表
  4. 找到/创建节点（已有则用旧的，不再 skip）
  5. update_node(DML) + update_vertex(调度参数)
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import DWD_SQL_PARAMETERS, generate_cron, get_cycle_type

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rebuild_dwd")

DDL_DIR = Path(r"E:\dw-modeling-template\sql\order-fulfillment\dwd\ddl")
DML_DIR = Path(r"E:\dw-modeling-template\sql\order-fulfillment\dwd\dml")
NODE_PATH_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/02_DWD"
SCHEDULE_MINUTE = 1
PROD_SCHEMA = "dataworks"
DEV_SCHEMA = "dataworks_dev"


def parse_ddl(content: str) -> str | None:
    """从 DDL 文件提取单张表完整 DDL（含 drop+create）。"""
    lines = content.split("\n")
    start = None
    for i, line in enumerate(lines):
        if re.match(r"drop\s+table\s+if\s+exists\s+\S+\.(dwd_\w+)", line.strip(), re.IGNORECASE):
            start = i
            break
    if start is None:
        return None
    end = None
    for j in range(start, len(lines)):
        if lines[j].strip() == ";":
            end = j + 1
            break
    if end is None:
        return None
    return "\n".join(lines[start:end]).strip()


def extract_table_name(content: str) -> str | None:
    m = re.search(r"drop\s+table\s+if\s+exists\s+\S+\.(dwd_\w+)", content, re.IGNORECASE)
    return m.group(1) if m else None


def to_dev_ddl(prod_ddl: str, table_name: str) -> str:
    """把 prod DDL 中的 dataworks.{table} 全部替换成 dataworks_dev.{table}。"""
    return _replace_schema(prod_ddl, table_name)


def _replace_schema(prod_ddl: str, table_name: str) -> str:
    """只替换本表名上的 schema 前缀，避免误伤其它字面量。"""
    return prod_ddl.replace(
        f"drop table if exists {PROD_SCHEMA}.{table_name}",
        f"drop table if exists {DEV_SCHEMA}.{table_name}",
    ).replace(f"create table {PROD_SCHEMA}.{table_name}", f"create table {DEV_SCHEMA}.{table_name}")


def extract_dml_for_table(dml_content: str, table_name: str) -> str | None:
    """从 DML 文件抽取单张表完整 DML（从 insert 起到文件末或下一个 insert 前）。"""
    insert_pat = rf"insert\s+(?:overwrite\s+)?(?:into\s+)?(?:table\s+)?\S*{re.escape(table_name)}\b"
    m = re.search(insert_pat, dml_content, re.IGNORECASE)
    if not m:
        return None
    start = m.start()
    nxt = re.search(
        r"\ninsert\s+(?:overwrite\s+)?(?:into\s+)?(?:table\s+)?\S",
        dml_content[start + 1 :],
        re.IGNORECASE,
    )
    end = start + 1 + nxt.start() if nxt else len(dml_content)
    return dml_content[start:end].rstrip() + "\n"


async def rebuild_one(bff: DataWorksClient, table_name: str, prod_ddl: str, dml: str) -> dict:
    """重建一张表 + 推送 DML + 挂调度。"""
    result = {"table": table_name, "success": True, "steps": {}, "error": ""}

    # 1. dev DDL（drop+create dataworks_dev.xxx）
    dev_ddl = _replace_schema(prod_ddl, table_name)
    logger.info("[%s] 建 dev 表", table_name)
    job = await bff.execute_sql(dev_ddl)
    if not job or not await bff.wait_job(job):
        result["steps"]["mc_dev"] = "failed"
        result["success"] = False
        result["error"] = "dev 建表失败"
        return result
    result["steps"]["mc_dev"] = "ok"

    # 2. prod DDL（drop+create dataworks.xxx）
    logger.info("[%s] 建 prod 表", table_name)
    job = await bff.execute_sql(prod_ddl)
    if not job or not await bff.wait_job(job):
        result["steps"]["mc_prod"] = "failed"
        result["success"] = False
        result["error"] = "prod 建表失败"
        return result
    result["steps"]["mc_prod"] = "ok"

    # 3. 节点：已有则复用，没有则创建
    node_path_full = generate_node_path(NODE_PATH_BASE, table_name)
    uuid = await bff.get_node_uuid_by_path(node_path_full)
    if not uuid:
        uuid = await bff.create_node(table_name, node_path_full, language="odps-sql")
        result["steps"]["node_create"] = uuid or "failed"
        if not uuid:
            result["success"] = False
            result["error"] = "节点创建失败"
            return result
    else:
        result["steps"]["node_reuse"] = uuid

    # 4. 推 DML
    if dml:
        if not await bff.update_node(uuid, dml):
            result["steps"]["dml"] = "failed"
            result["success"] = False
            result["error"] = "DML 更新失败"
            return result
        result["steps"]["dml"] = "ok"

    # 5. 调度参数 + 依赖 + 输出
    cron = generate_cron("hour", minute=SCHEDULE_MINUTE)
    cycle_type = get_cycle_type("hour")
    if not await bff.update_vertex(
        uuid,
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
            "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
            "outputs": {
                "nodeOutputs": [
                    {
                        "data": uuid,
                        "refTableName": table_name,
                        "artifactType": "NodeOutput",
                        "sourceType": "System",
                        "isDefault": True,
                    }
                ]
            },
        },
    ):
        result["steps"]["sched"] = "failed"
        result["success"] = False
        result["error"] = "调度参数更新失败"
        return result
    result["steps"]["sched"] = "ok"
    return result


async def main():
    ddl_files = sorted(DDL_DIR.glob("*.sql"))
    logger.info("源 DDL 文件 %d 个", len(ddl_files))

    # 把 DML 按表名映射
    dml_contents = {f.stem: f.read_text(encoding="utf-8") for f in DML_DIR.glob("*.sql")}
    logger.info("源 DML 文件 %d 个", len(dml_contents))

    bff = DataWorksClient()
    results = []
    ok = fail = 0
    for ddl_file in ddl_files:
        content = ddl_file.read_text(encoding="utf-8")
        table_name = extract_table_name(content)
        prod_ddl = parse_ddl(content)
        if not table_name or not prod_ddl:
            logger.warning("跳过无法解析的 DDL: %s", ddl_file.name)
            continue

        dml = None
        for _stem, txt in dml_contents.items():
            dml = extract_dml_for_table(txt, table_name)
            if dml:
                break

        try:
            r = await rebuild_one(bff, table_name, prod_ddl, dml)
        except Exception as e:
            logger.exception("[%s] 异常: %s", table_name, e)
            r = {"table": table_name, "success": False, "error": str(e), "steps": {}}

        status = "OK" if r["success"] else "FAIL"
        logger.info("[%s] %s steps=%s err=%s", status, table_name, r.get("steps"), r.get("error"))
        results.append(r)
        if r["success"]:
            ok += 1
        else:
            fail += 1

    await bff.close()
    print(f"\n总计: {ok} 成功 / {fail} 失败 / {len(results)} 处理")
    for r in results:
        s = "OK" if r["success"] else "FAIL"
        print(f"  [{s}] {r['table']:<50} {r.get('error', '')}")


if __name__ == "__main__":
    asyncio.run(main())
