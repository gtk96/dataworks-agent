"""给 DIM 节点配依赖(Normal 类型, output=上游 ODS 全量节点 uuid)+ outputs。

依赖通过 ide/addNodeDependencies (PUT) 写, outputs 通过 ide/updateVertex (POST) 写。
"""

from __future__ import annotations

import asyncio
import logging

from dataworks_agent.api_clients.bff_client import DataWorksClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dim_deps")

DIM_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/01_DIM"
ODS_BASE = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"

# DIM 3 张表 → ODS 全量表 一对一映射(只用于当前 3 张,以后加表再扩)
DIM_TO_ODS: dict[str, str] = {
    "dim_ord_ofc_cancel_reason_all": "ods_hl_ofc__cancel_reason_config_all",
    "dim_ord_oms_platform_all": "ods_hl_oms__sys_platform_all",
    "dim_ord_oms_payment_all": "ods_hl_oms__sys_payment_all",
}


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
        if (h.get("path") or "").startswith(path_prefix):
            name = h.get("name", "").replace(".sql", "")
            v_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
            if v_uuid:
                out[name] = v_uuid
    return out


async def add_node_dependencies(bff: DataWorksClient, target_uuid: str, deps: list[dict]) -> bool:
    payload = {
        "projectId": bff.project_id,
        "uuid": str(target_uuid),
        "dependencies": deps,
    }
    resp = await bff._put("ide/addNodeDependencies", payload)
    return resp.get("code") == 200


async def write_outputs(bff: DataWorksClient, target_uuid: str, table_name: str) -> bool:
    out_payload = {
        "projectId": bff.project_id,
        "uuid": str(target_uuid),
        "instanceMode": "Immediately",
        "outputs": {
            "nodeOutputs": [
                {
                    "data": str(target_uuid),
                    "refTableName": table_name,
                    "artifactType": "NodeOutput",
                    "sourceType": "System",
                    "isDefault": True,
                }
            ]
        },
    }
    resp = await bff._post("ide/updateVertex", out_payload)
    return resp.get("code") == 200


async def main() -> None:
    bff = DataWorksClient()

    logger.info("抓取 ODS 和 DIM 节点 uuid ...")
    ods_uuids = await fetch_uuids(bff, "ods_hl_", ODS_BASE)
    dim_uuids = await fetch_uuids(bff, "dim_ord_", DIM_BASE)
    logger.info("ODS 节点: %d, DIM 节点: %d", len(ods_uuids), len(dim_uuids))

    ok_deps = ok_out = failed = 0

    for dim_table, dim_uuid in dim_uuids.items():
        ods_table = DIM_TO_ODS.get(dim_table, "")
        ods_uuid = ods_uuids.get(ods_table, "")

        deps: list[dict] = [{"type": "CrossCycleDependsOnSelf"}]
        if ods_uuid:
            deps.insert(0, {"type": "Normal", "output": ods_uuid, "sourceType": "System"})

        dep_ok = await add_node_dependencies(bff, dim_uuid, deps)
        out_ok = await write_outputs(bff, dim_uuid, dim_table)

        if dep_ok:
            ok_deps += 1
        if out_ok:
            ok_out += 1
        if not (dep_ok and out_ok):
            failed += 1
            print(f"  FAIL: {dim_table} (dep={dep_ok}, out={out_ok}, ods={ods_table or '?'})")
        else:
            print(f"  OK: {dim_table} <- {ods_table or '(no upstream)'}")

    await bff.close()
    print(
        f"\n总计: deps={ok_deps}/{len(dim_uuids)}, outputs={ok_out}/{len(dim_uuids)}, failed={failed}"
    )


if __name__ == "__main__":
    asyncio.run(main())
