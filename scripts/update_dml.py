"""更新已部署 ODS 节点的 DML。"""
import asyncio
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.services.ods_holo.dml_generator import comment_out_import


async def update_node_dml(bff, node_path: str, dml: str) -> bool:
    """更新节点 DML。"""
    uuid = await bff.get_node_uuid_by_path(node_path)
    if not uuid:
        print(f"  节点不存在: {node_path}")
        return False
    dml_commented = comment_out_import(dml)
    ok = await bff.update_node(uuid, dml_commented)
    print(f"  {'OK' if ok else 'FAIL'}: {node_path} (uuid={uuid})")
    return ok


def extract_dmls(dml_content: str) -> dict[str, str]:
    """从 DML 文件提取每个表的 DML。"""
    result = {}
    pattern = r"(insert into cda\.(ods_hl_\w+__\w+_hour)\b.*?;)"
    for match in re.finditer(pattern, dml_content, re.IGNORECASE | re.DOTALL):
        result[match.group(2)] = match.group(1).strip()
    return result


async def main():
    bff = DataWorksClient()
    node_base = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"

    # OFC
    ofc_dml = Path(r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_ofc__order_fulfillment_hour_dml.sql").read_text(encoding="utf-8", errors="ignore")
    ofc_dmls = extract_dmls(ofc_dml)
    print(f"OFC DML: {len(ofc_dmls)} 个")

    for table_name, dml in ofc_dmls.items():
        await update_node_dml(bff, f"{node_base}/{table_name}", dml)

    # OMS
    oms_dml = Path(r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_oms__order_fulfillment_hour_dml.sql").read_text(encoding="utf-8", errors="ignore")
    oms_dmls = extract_dmls(oms_dml)
    print(f"OMS DML: {len(oms_dmls)} 个")

    for table_name, dml in oms_dmls.items():
        await update_node_dml(bff, f"{node_base}/{table_name}", dml)

    await bff.close()
    print("完成")

asyncio.run(main())
