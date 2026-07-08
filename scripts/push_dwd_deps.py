"""给 DWD 节点配依赖(Normal 类型, output=上游 ODS uuid)+ outputs。

依赖通过 ide/addNodeDependencies 接口(PUT),不是 updateVertex。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dwd_deps")

DWD_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/02_DWD"
ODS_BASE = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"


async def fetch_uuids(bff: DataWorksClient, keyword: str, path_prefix: str) -> dict[str, str]:
    r = await bff._get(
        "ide/searchFiles",
        {
            "projectId": bff.project_id,
            "keyword": keyword,
            "scene": "DATAWORKS_PROJECT",
            "pageSize": 100,
        },
    )
    out: dict[str, str] = {}
    for h in (r.get("data") or {}).get("data", {}).get("hits", []) or []:
        path = h.get("path", "")
        if path.startswith(path_prefix):
            name = h.get("name", "").replace(".sql", "")
            v_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
            if v_uuid:
                out[name] = v_uuid
    return out


def extract_dml_sources(dml: str) -> list[str]:
    """从 DML 正文提取所有上游 ODS 表名。"""
    from dataworks_agent.modeling.dwd.dependencies import find_ods_sources

    return find_ods_sources(dml)


async def add_node_dependencies(bff: DataWorksClient, target_uuid: str, deps: list[dict]) -> bool:
    """调用 ide/addNodeDependencies (PUT) 增加节点依赖。"""
    payload = {
        "projectId": bff.project_id,
        "uuid": str(target_uuid),
        "dependencies": deps,
    }
    resp = await bff._put("ide/addNodeDependencies", payload)
    return resp.get("code") == 200


async def main() -> None:
    bff = DataWorksClient()

    logger.info("抓取 ODS 和 DWD 节点 uuid ...")
    ods_uuids = await fetch_uuids(bff, "ods_hl_", ODS_BASE)
    dwd_uuids = await fetch_uuids(bff, "dwd_ord_", DWD_BASE)
    logger.info("ODS 节点: %d, DWD 节点: %d", len(ods_uuids), len(dwd_uuids))

    ok_deps = ok_out = failed = 0

    # 加载 DML 文件以解析多源依赖
    dml_dir = Path(r"E:\dw-modeling-template\sql\order-fulfillment\dwd\dml")
    table_to_dml: dict[str, str] = {}
    if dml_dir.exists():
        for f in dml_dir.glob("*.sql"):
            content = f.read_text(encoding="utf-8")
            # 提取表名和 DML 正文
            for table_name in dwd_uuids:
                if table_name.lower() in f.name.lower():
                    table_to_dml[table_name] = content

    for dwd_table, dwd_uuid in dwd_uuids.items():
        # 从 DML 提取所有上游 ODS 表（1:N）
        dml_content = table_to_dml.get(dwd_table, "")
        ods_sources = extract_dml_sources(dml_content) if dml_content else []

        # 1. dependencies: 所有上游 ODS + 自依赖 (CrossCycleDependsOnSelf)
        deps: list[dict] = [{"type": "CrossCycleDependsOnSelf"}]
        for ods_src in ods_sources:
            ods_uuid = ods_uuids.get(ods_src, "")
            if ods_uuid:
                deps.insert(0, {"type": "Normal", "output": ods_uuid, "sourceType": "System"})

        dep_ok = await add_node_dependencies(bff, dwd_uuid, deps)

        # 2. outputs: 节点产出
        out_payload = {
            "projectId": bff.project_id,
            "uuid": str(dwd_uuid),
            "instanceMode": "Immediately",
            "outputs": {
                "nodeOutputs": [
                    {
                        "data": str(dwd_uuid),
                        "refTableName": dwd_table,
                        "artifactType": "NodeOutput",
                        "sourceType": "System",
                        "isDefault": True,
                    }
                ]
            },
        }
        out_resp = await bff._post("ide/updateVertex", out_payload)
        out_ok = out_resp.get("code") == 200

        if dep_ok:
            ok_deps += 1
        if out_ok:
            ok_out += 1
        if not (dep_ok and out_ok):
            failed += 1
            print(f"  FAIL: {dwd_table} (dep={dep_ok}, out={out_ok}, ods_sources={ods_sources})")
        else:
            print(f"  OK: {dwd_table} <- {ods_sources}")

    await bff.close()
    print(
        f"\n总计: deps={ok_deps}/{len(dwd_uuids)}, outputs={ok_out}/{len(dwd_uuids)}, failed={failed}"
    )


if __name__ == "__main__":
    asyncio.run(main())
