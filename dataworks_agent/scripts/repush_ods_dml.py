"""ODS DML 重推脚本 — 仅刷新节点 script.content 与调度配置，不动 DDL / IMPORT / 调度触发重建。

背景：之前 deploy_ods.py 在节点已存在时直接跳过，导致 DML 调整、HOURLY_SQL_PARAMETERS
更新无法下发到线上节点。本脚本用于一次性把 OFC / OMS 两批 ODS 表全部节点重拉一次。

行为：
- 不调 execute_sql（不重跑 DDL，也不跑 IMPORT FOREIGN SCHEMA）
- 不调 create_node（节点由 deploy_ods.py 在第一次部署时创建）
- 对每个表：拉 uuid → update_node(dml) → update_vertex({trigger, script.parameters, strategy, dependencies, outputs})
- 失败的表 collect 起来，最后打印 FAIL 汇总
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming import generate_node_path
from dataworks_agent.naming.schedule import (
    HOURLY_SQL_PARAMETERS,
    generate_cron,
    get_cycle_type,
)
from dataworks_agent.services.ods_holo import extract_dml_for_table

logger = logging.getLogger("repush_ods_dml")

BACKUP_DIR = Path("logs/repush_backup")
METADATA_SUFFIX = ".dataworks/metadata.json"


async def _backup_online_script(
    bff: DataWorksClient, table_name: str, node_path_full: str
) -> str | None:
    """读 VFS 当前脚本落到 logs/repush_backup/<table>.sql；返回本地路径或 None。"""
    try:
        meta_resp = await bff.get_file(f"{node_path_full}/{METADATA_SUFFIX}")
    except Exception as e:
        logger.debug("读 metadata 失败 %s: %s", table_name, e)
        return None
    data_field = meta_resp.get("data", {}) if isinstance(meta_resp, dict) else {}
    content_str = data_field.get("content", "") if isinstance(data_field, dict) else ""
    if not content_str:
        return None
    try:
        meta = json.loads(content_str)
        script_rel = meta.get("scriptPath")
        if not script_rel:
            return None
        resp = await bff.get_file(f"{node_path_full}/{script_rel}")
        d = resp.get("data", {}) if isinstance(resp, dict) else {}
        c = d.get("content", "") if isinstance(d, dict) else ""
        if not c:
            return None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = BACKUP_DIR / f"{table_name}__{ts}.sql"
        path.write_text(c, encoding="utf-8")
        return str(path)
    except Exception as e:
        logger.debug("备份失败 %s: %s", table_name, e)
        return None


async def repush_one(
    bff: DataWorksClient,
    table_name: str,
    dml: str,
    *,
    node_path_prefix: str,
    schedule_minute: int,
) -> dict:
    """重推单张表。"""
    node_path_full = generate_node_path(node_path_prefix, table_name)
    uuid = await bff.get_node_uuid_by_path(node_path_full)
    if not uuid:
        return {
            "table": table_name,
            "success": False,
            "error": "node_not_found",
            "node_path": node_path_full,
        }

    # 0) 备份当前线上脚本
    backup_path = await _backup_online_script(bff, table_name, node_path_full)

    # 1) 写 DML 内容
    ok_dml = await bff.update_node(uuid, dml)

    # 2) 重发节点配置（与 deploy_ods.py 中 create_node 之后的配置保持一致）
    cron = generate_cron("hour", minute=schedule_minute)
    cycle_type = get_cycle_type("hour")
    payload = {
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
                    "data": uuid,
                    "refTableName": table_name,
                    "artifactType": "NodeOutput",
                    "sourceType": "System",
                    "isDefault": True,
                }
            ]
        },
    }
    ok_cfg = await bff.update_vertex(uuid, payload)

    success = ok_dml and ok_cfg
    err = ""
    if not ok_dml:
        err += "update_node_failed "
    if not ok_cfg:
        err += "update_vertex_failed "
    return {
        "table": table_name,
        "success": success,
        "dml": ok_dml,
        "vertex": ok_cfg,
        "uuid": uuid,
        "backup": backup_path,
        "error": err.strip(),
    }


async def repush_batch(
    dml_file: str,
    *,
    table_names: list[str],
    node_path_prefix: str,
    schedule_minute: int = 1,
) -> list[dict]:
    """对一批表重推 DML。"""
    dml_path = Path(dml_file)
    if not dml_path.exists():
        raise FileNotFoundError(f"DML 文件不存在: {dml_file}")

    dml_content = dml_path.read_text(encoding="utf-8")
    missing_dml: list[str] = []
    results: list[dict] = []

    bff = DataWorksClient()
    try:
        for table_name in table_names:
            dml = extract_dml_for_table(dml_content, table_name)
            if not dml:
                missing_dml.append(table_name)
                results.append({"table": table_name, "success": False, "error": "dml_not_in_file"})
                continue

            logger.info("重推: %s", table_name)
            res = await repush_one(
                bff,
                table_name,
                dml,
                node_path_prefix=node_path_prefix,
                schedule_minute=schedule_minute,
            )
            results.append(res)
    finally:
        await bff.close()

    if missing_dml:
        logger.warning("以下表在 DML 文件中未找到: %s", missing_dml)
    return results


# ── OFC / OMS ODS 表名清单（与 deploy_ods.py 中解析到的所有表一致）────────────────────
OFC_NODE_PREFIX = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"
OFC_DML_FILE = r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_ofc__order_fulfillment_hour_dml.sql"
OMS_NODE_PREFIX = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"
OMS_DML_FILE = r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_oms__order_fulfillment_hour_dml.sql"


# 从 DDL 文件里抽出符合命名约束的 ODS 表名（与 deploy_ods.py 解析口径一致）
def list_ods_tables(ddl_file: str) -> list[str]:
    text = Path(ddl_file).read_text(encoding="utf-8")
    tables: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("-- ods_hl_"):
            tables.append(s.lstrip("- ").split()[0])
    return tables


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只解析/抽取 DML，不调任何线上接口")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    ofc_ddl = r"E:\dw-modeling-template\sql\order-fulfillment\ods\ddl\ods_hl_ofc__order_fulfillment_hour_ddl.sql"
    oms_ddl = r"E:\dw-modeling-template\sql\order-fulfillment\ods\ddl\ods_hl_oms__order_fulfillment_hour_ddl.sql"

    ofc_tables = list_ods_tables(ofc_ddl)
    oms_tables = list_ods_tables(oms_ddl)
    logger.info("OFC: %d 张, OMS: %d 张", len(ofc_tables), len(oms_tables))

    if args.dry_run:
        print("=== DRY RUN: 只解析/抽取 DML，不调任何接口 ===\n")

        for label, ddl_list, dml_file, prefix in [
            ("OFC", ofc_tables, OFC_DML_FILE, OFC_NODE_PREFIX),
            ("OMS", oms_tables, OMS_DML_FILE, OMS_NODE_PREFIX),
        ]:
            print(f"--- {label} ({len(ddl_list)} 张) ---")
            dml_content = Path(dml_file).read_text(encoding="utf-8")
            for tbl in ddl_list:
                dml = extract_dml_for_table(dml_content, tbl)
                if not dml:
                    print(f"  [{tbl}]  MISS dml")
                    continue
                # 前 60 字符去重空白，辨识度高
                preview = " ".join(dml.split())[:60]
                print(f"  [{tbl}]  OK   DML {len(dml)} chars | {preview}...")
            # 给出节点路径示例（与 generate_node_path 一致）
            from dataworks_agent.naming.schedule import generate_cron

            sample = generate_node_path(prefix, ofc_tables[0] if ofc_tables else oms_tables[0])
            print(f"  节点路径示例: {sample}")
            print(f"  cron: {generate_cron('hour', minute=1)}\n")
        print("DRY RUN 完毕。确认无误后去掉 --dry-run 真正跑。")
        return

    print("=== 重推 OFC ODS ===")
    ofc_results = await repush_batch(
        dml_file=OFC_DML_FILE,
        table_names=ofc_tables,
        node_path_prefix=OFC_NODE_PREFIX,
        schedule_minute=1,
    )

    print("\n=== 重推 OMS ODS ===")
    oms_results = await repush_batch(
        dml_file=OMS_DML_FILE,
        table_names=oms_tables,
        node_path_prefix=OMS_NODE_PREFIX,
        schedule_minute=1,
    )

    all_results = ofc_results + oms_results
    ok = sum(1 for r in all_results if r["success"])
    total = len(all_results)
    print(f"\n总计: {ok}/{total} 成功")

    print("\n明细:")
    for r in all_results:
        backup = r.get("backup") or "-"
        if r["success"]:
            print(f"  [OK]   {r['table']}  uuid={r.get('uuid')}  backup={backup}")
        else:
            err = r.get("error", "")
            print(f"  [FAIL] {r['table']}  err={err}  backup={backup}")


if __name__ == "__main__":
    asyncio.run(main())
