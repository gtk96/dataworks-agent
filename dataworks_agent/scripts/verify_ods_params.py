"""ODS 节点 DML 完整性 + 一致性校验。

校验口径（按"会挡 bug"的优先级排序）：
1. 字节级：拉 VFS 真实脚本（用 metadata.json.scriptPath），与 extract_dml_for_table 修后版本做
   严格等值比较。任一不等即视为"线上与源文件漂移"。
2. 语义级：必含 from、where、; 收尾、insert into cda.X 开头、长度 > 100。
3. 完整性：必不存在老 bug——`apply_type -- 申请类型，1：取消申请 ;` 这种行尾注释里的
   分号提前截断（校验方式：脚本末尾 `;` 之前应至少出现一次 `from` / `where`，且
   最后 200 字符内应含 `;`）。

输出：
- 默认打印 25 张表 (OFC 17 + OMS 8) 的逐行 OK/DIFF/MISS
- 失败统计；DIFF 给出 first_diff_at + 局部上下文（300 字符）
- 退出码：0 = 全部 OK；1 = 有 DIFF 或 MISS
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming import generate_node_path
from dataworks_agent.services.ods_holo import extract_dml_for_table

NODE_PREFIX = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"
OFC_DDL = r"E:\dw-modeling-template\sql\order-fulfillment\ods\ddl\ods_hl_ofc__order_fulfillment_hour_ddl.sql"
OMS_DDL = r"E:\dw-modeling-template\sql\order-fulfillment\ods\ddl\ods_hl_oms__order_fulfillment_hour_ddl.sql"
OFC_DML = r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_ofc__order_fulfillment_hour_dml.sql"
OMS_DML = r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml\ods_hl_oms__order_fulfillment_hour_dml.sql"

META_SUFFIX = ".dataworks/metadata.json"


def list_ods_tables(ddl_file: str) -> list[str]:
    out: list[str] = []
    for line in Path(ddl_file).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("-- ods_hl_"):
            out.append(s.lstrip("- ").split()[0])
    return out


def semantic_check(dml: str | None) -> dict:
    if not dml:
        return {"has_dml": False}
    has_from = bool(re.search(r"\bfrom\s+\w+\.\w+", dml, re.IGNORECASE))
    has_where = bool(re.search(r"\bwhere\b", dml, re.IGNORECASE))
    ends_ok = dml.rstrip().endswith(";")
    starts_ok = bool(re.match(r"\s*insert\s+into\s+cda\.\S+", dml, re.IGNORECASE))
    return {
        "len": len(dml),
        "has_from": has_from,
        "has_where": has_where,
        "endswith_semicolon": ends_ok,
        "starts_with_insert_into_cda": starts_ok,
        "ok": all([has_from, has_where, ends_ok, starts_ok, len(dml) >= 100]),
    }


async def read_online_dml(bff: DataWorksClient, table: str) -> str | None:
    node_path = generate_node_path(NODE_PREFIX, table)
    meta_resp = await bff.get_file(f"{node_path}/{META_SUFFIX}")
    data_field = meta_resp.get("data", {}) if isinstance(meta_resp, dict) else {}
    content_str = data_field.get("content", "") if isinstance(data_field, dict) else ""
    if not content_str:
        return None
    try:
        meta = json.loads(content_str)
    except json.JSONDecodeError:
        return None
    script_rel = meta.get("scriptPath")
    if not script_rel:
        return None
    resp = await bff.get_file(f"{node_path}/{script_rel}")
    d = resp.get("data", {}) if isinstance(resp, dict) else {}
    c = d.get("content", "") if isinstance(d, dict) else ""
    return c or None


def first_diff(a: str, b: str) -> tuple[int, int, str, str]:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i, len(a) - len(b), a, b
    return n, len(a) - len(b), a, b


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true", help="只打印汇总，不打每张表")
    args = parser.parse_args()

    bff = DataWorksClient()
    try:
        rows: list[dict] = []
        for label, ddl, dml in [("OFC", OFC_DDL, OFC_DML), ("OMS", OMS_DDL, OMS_DML)]:
            dml_text = Path(dml).read_text(encoding="utf-8")
            for tbl in list_ods_tables(ddl):
                local = extract_dml_for_table(dml_text, tbl)
                online = await read_online_dml(bff, tbl)
                local_sem = semantic_check(local)
                online_sem = semantic_check(online)
                equal = (local is not None) and (online is not None) and (local == online)

                row = {
                    "group": label,
                    "table": tbl,
                    "equal": equal,
                    "local_len": len(local) if local else 0,
                    "online_len": len(online) if online else 0,
                    "local_sem": local_sem,
                    "online_sem": online_sem,
                    "online": online,
                    "local": local,
                }
                if not equal and local and online:
                    idx, dlen, _, _ = first_diff(local, online)
                    row["diff_at"] = idx
                    row["len_diff"] = dlen
                rows.append(row)

        ok = sum(
            1
            for r in rows
            if r["equal"] and r["online_sem"].get("ok", False) and r["local_sem"].get("ok", False)
        )
        bad = [
            r
            for r in rows
            if not r["equal"]
            or not r["online_sem"].get("ok", False)
            or not r["local_sem"].get("ok", False)
        ]

        if not args.quiet:
            print(f"{'group':<5} {'table':<48} {'local':>6} {'online':>7} {'equal':>6} {'sem':>4}")
            for r in rows:
                eq = "OK" if r["equal"] else "DIFF"
                sem_ok = r["online_sem"].get("ok", False) and r["local_sem"].get("ok", False)
                sem = "OK" if sem_ok else "BAD"
                print(
                    f"{r['group']:<5} {r['table']:<48} "
                    f"{r['local_len']:>6} {r['online_len']:>7} "
                    f"{eq:>6} {sem:>4}"
                )
        else:
            for r in rows:
                if not r["equal"] or not r["online_sem"].get("ok", False):
                    print(
                        f"  [{r['group']}] {r['table']}: equal={r['equal']} sem={r['online_sem']}"
                    )

        print(f"\n通过: {ok}/{len(rows)}")

        if bad:
            print("\n=== 失败详情 ===")
            for r in bad:
                print(f"\n[{r['group']}] {r['table']}")
                if not r["local_sem"].get("ok", False):
                    print(f"  LOCAL  sem: {r['local_sem']}")
                if not r["online_sem"].get("ok", False):
                    print(f"  ONLINE sem: {r['online_sem']}")
                if not r["equal"] and r["local"] and r["online"]:
                    idx = r.get("diff_at", -1)
                    a, b = r["local"], r["online"]
                    print(f"  first_diff_at: {idx} (len_diff={r.get('len_diff', 0)})")
                    lo = max(0, idx - 60)
                    hi = min(min(len(a), len(b)), idx + 240)
                    print(f"  local[{lo}:{hi}]: {a[lo:hi]!r}")
                    print(f"  online[{lo}:{hi}]: {b[lo:hi]!r}")
        return 0 if not bad else 1
    finally:
        await bff.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
