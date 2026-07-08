"""把 DWD 表的 DML 和调度参数推送到已部署的 DataWorks 节点。

节点路径: 业务流程/DWD/MaxCompute/{table_name}
参数:      HOURLY_SQL_PARAMETERS(已删除 gmtdate_last2h)
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.modeling.dwd.dependencies import find_ods_sources
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS, generate_cron, get_cycle_type

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dwd")


NODE_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/02_DWD"
SCHEDULE_MINUTE = 1
DML_DIR = Path(r"E:\dw-modeling-template\sql\order-fulfillment\dwd\dml")


def extract_table_names(dml_content: str) -> list[str]:
    pattern = r"insert\s+overwrite\s+table\s+\S+\.(dwd_ord_\w+_hour)\b"
    return list(dict.fromkeys(re.findall(pattern, dml_content, re.IGNORECASE)))


def extract_dml_for_table(dml_content: str, table_name: str) -> str | None:
    """提取指定表的完整 DML(包含该表的 insert + 后续 alter table 等语句)。

    策略:从该表的 insert 起始位置开始,取到下一个 insert 之前的所有语句。
    这样能完整保留 `insert ...; -- 注释 \n alter table ...;` 这类组合。
    """
    insert_pattern = rf"insert\s+overwrite\s+table\s+\S*{re.escape(table_name)}\b"
    m = re.search(insert_pattern, dml_content, re.IGNORECASE)
    if not m:
        return None
    start = m.start()
    # 从 start 之后找下一个 insert
    next_insert = re.search(
        r"\ninsert\s+overwrite\s+table", dml_content[start + 1 :], re.IGNORECASE
    )
    end = start + 1 + next_insert.start() if next_insert else len(dml_content)
    chunk = dml_content[start:end].rstrip() + "\n"
    return chunk.strip()


async def main() -> None:
    bff = DataWorksClient()

    dml_files = sorted(DML_DIR.glob("*.sql"))
    if not dml_files:
        raise FileNotFoundError(f"未找到 DML 文件: {DML_DIR}")

    table_to_dml: dict[str, str] = {}
    for f in dml_files:
        content = f.read_text(encoding="utf-8")
        for t in extract_table_names(content):
            extracted = extract_dml_for_table(content, t)
            if extracted:
                table_to_dml[t] = extracted
    logger.info("解析到 %d 个 DWD 表", len(table_to_dml))

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
        logger.warning("预抓取 ODS uuid 失败: %s", e)

    cron = generate_cron("hour", minute=SCHEDULE_MINUTE)
    cycle_type = get_cycle_type("hour")
    parameters = HOURLY_SQL_PARAMETERS

    ok = failed = 0
    for table_name, dml in table_to_dml.items():
        node_path = f"{NODE_BASE}/{table_name}"
        uuid = await bff.get_node_uuid_by_path(node_path)
        if not uuid:
            print(f"  FAIL(node not found, 不自动建目录): {node_path}")
            failed += 1
            continue

        dml_ok = await bff.update_node(uuid, dml)
        if not dml_ok:
            print(f"  FAIL(DML): {node_path} ({bff.last_error or '?'})")
            failed += 1
            continue

        # 从 DML 提取所有上游 ODS 表（1:N）
        ods_sources = find_ods_sources(dml)
        deps: list[dict] = [{"type": "CrossCycleDependsOnSelf"}]
        for ods_src in ods_sources:
            ods_u = ods_uuids.get(ods_src, "")
            if ods_u:
                deps.insert(0, {"type": "Normal", "output": ods_u, "sourceType": "System"})

        sched_ok = await bff.update_vertex(
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
                "script": {"parameters": parameters},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": deps,
            },
        )

        status = "OK" if sched_ok else f"FAIL(sched) ({bff.last_error or '?'})"
        print(f"  {status}: {node_path} (uuid={uuid}, ods_sources={ods_sources})")
        if sched_ok:
            ok += 1
        else:
            failed += 1

    await bff.close()
    print(f"\n总计: {ok} 成功 / {failed} 失败")


if __name__ == "__main__":
    asyncio.run(main())
