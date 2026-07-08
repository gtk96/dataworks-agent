"""调度配置 + DI 节点创建 — 批量配置导入表的调度参数和数据集成节点。"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class ScheduleRequest(BaseModel):
    tables: list[str] = []  # 空 = 所有表
    layer: str = "all"
    cycle: str = "auto"  # auto | hour | day
    biz_hour: int = 3


def _gen_schedule(table_name: str, cycle: str = "auto", biz_hour: int = 3) -> dict:
    """根据表名和配置生成调度参数。"""
    from dataworks_agent.naming import generate_cron, infer_schedule_type

    if cycle == "auto":
        cycle = "hour" if infer_schedule_type(table_name) == "NotDaily" else "day"

    if cycle == "hour":
        return {
            "cycle_type": "NotDaily",
            "cron": generate_cron("hour", minute=0),
            "parameters": [
                {"name": "gmtdate", "type": "System", "value": "$[yyyymmdd-1/24]"},
                {"name": "hour_last1h", "type": "System", "value": "$[hh24-1/24]"},
                {"name": "gmtdate_last1h", "type": "System", "value": "$[yyyymmdd-2/24]"},
                {"name": "gmtdate_last2h", "type": "System", "value": "$[yyyymmdd-3/24]"},
                {"name": "hour_last2h", "type": "System", "value": "$[hh24-2/24]"},
            ],
            "resource_group": "",
            "node_checked": True,
        }
    else:
        return {
            "cycle_type": "Daily",
            "cron": generate_cron("day", hour=biz_hour, minute=0),
            "parameters": [
                {"name": "bizdate", "type": "System", "value": "$[yyyymmdd-1]"},
                {"name": "biz_date", "type": "System", "value": "$[yyyy-mm-dd-1]"},
            ],
            "resource_group": "",
            "node_checked": True,
        }


def _is_ods_table(name: str) -> bool:
    return name.startswith("ods_")


def _load_dml_for_table(table_name: str) -> str:
    """从 SQL 文件目录加载对应表的 DML 脚本。"""
    base = Path("E:/dw-modeling-template/sql/order-fulfillment")

    # 确定层和文件名模式
    if table_name.startswith("ods_"):
        layer_dir = "ods"
        # ods_hl_ofc__* → ofc 文件; ods_hl_oms__* → oms 文件
        if "ofc" in table_name or "oms" in table_name:
            pass
        else:
            return ""
    elif table_name.startswith("dwd_"):
        layer_dir = "dwd"
        # dwd_ord_ofc_* → ofc 文件; dwd_ord_oms_* → oms 文件
        table_name.replace("dwd_ord_", "").split("_hour")[0]
    elif table_name.startswith("dim_"):
        layer_dir = "dim"
    else:
        return ""

    # 尝试找 DML 文件
    dml_dir = base / layer_dir / "dml"
    if not dml_dir.exists():
        return ""

    for f in sorted(dml_dir.glob("*.sql")):
        content = f.read_text(encoding="utf-8")
        if table_name in content:
            return content.strip()

    return ""


@router.post("/generate")
async def generate_schedule_configs(req: ScheduleRequest):
    """为指定表生成调度配置（不创建节点，仅生成配置 JSON）。"""
    tables = req.tables
    if not tables:
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            rows = (
                db.query(ModelingTaskModel.target_table)
                .filter(ModelingTaskModel.status == "completed")
                .distinct()
                .all()
            )
            tables = [
                r[0] for r in rows if req.layer == "all" or r[0].startswith(req.layer.lower() + "_")
            ]

    configs = []
    for name in tables:
        cfg = _gen_schedule(name, req.cycle, req.biz_hour)
        is_ods = _is_ods_table(name)
        configs.append(
            {
                "table": name,
                "layer": "ODS" if is_ods else ("DIM" if name.startswith("dim_") else "DWD"),
                "needs_di": is_ods,
                "cycle_type": cfg["cycle_type"],
                "cron": cfg["cron"],
                "parameters": cfg["parameters"],
                "node_name": name,
                "node_path": f"dataworks_agent/01_ODS/{name}"
                if is_ods
                else f"dataworks_agent/02_DWD/{name}",
            }
        )

    return {"configs": configs, "total": len(configs)}


@router.post("/apply")
async def apply_schedule_configs(req: ScheduleRequest):
    """为表批量创建 IDE 节点 + 配置调度（通过 BFF createPackage + updateVertex）。"""
    from dataworks_agent.state import app_state

    # 纯节点操作（create/update/vertex）优先走 AK/SK 适配器，缺则降级 bff（Task 8b/9a）
    bff = getattr(app_state, "_node_client", None) or getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="节点客户端不可用")

    # 获取表列表
    tables = req.tables
    if not tables:
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            rows = (
                db.query(ModelingTaskModel.target_table)
                .filter(ModelingTaskModel.status == "completed")
                .distinct()
                .all()
            )
            tables = [
                r[0] for r in rows if req.layer == "all" or r[0].startswith(req.layer.lower() + "_")
            ]

    results = []
    for name in tables:
        cfg = _gen_schedule(name, req.cycle, req.biz_hour)
        is_ods = _is_ods_table(name)
        node_path = f"dataworks_agent/01_ODS/{name}" if is_ods else f"dataworks_agent/02_DWD/{name}"

        # ODS → Holo SQL 节点; DWD/DIM → MaxCompute SQL 节点
        language = "holo" if is_ods else "odps-sql"

        try:
            # 1. 创建节点
            pkg_result = await bff.create_node(
                name=name,
                path=node_path,
                language=language,
            )

            if not pkg_result:
                results.append({"table": name, "status": "failed", "error": "createPackage 返回空"})
                continue

            node_uuid = pkg_result.get("uuid") if isinstance(pkg_result, dict) else pkg_result

            # 2. 写入 DML/调度内容
            dml_content = _load_dml_for_table(name)
            if dml_content:
                await bff.update_node(str(node_uuid), dml_content)

            # 3. 配置调度
            await bff.update_vertex(
                node_uuid,
                {
                    "trigger": {
                        "type": "Scheduler",
                        "cron": cfg["cron"],
                        "cycleType": cfg["cycle_type"],
                        "startTime": "1970-01-01 00:00:00",
                        "endTime": "9999-01-01 00:00:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "script": {"parameters": cfg["parameters"]},
                    "strategy": {"instanceMode": "Immediately"},
                },
            )

            # 3. 更新本地记录
            import json

            from dataworks_agent.db.database import SessionLocal
            from dataworks_agent.db.models import ModelingTaskModel

            with SessionLocal() as db:
                tasks = db.query(ModelingTaskModel).filter_by(target_table=name).all()
                for t in tasks:
                    t.node_uuid = str(node_uuid)
                    t.node_name = name
                    t.schedule_config_json = json.dumps(cfg, ensure_ascii=False)
                db.commit()

            results.append(
                {
                    "table": name,
                    "status": "ok",
                    "node_uuid": str(node_uuid),
                    "cycle": cfg["cycle_type"],
                    "is_di": is_ods,
                }
            )
            logger.info("节点创建+调度配置成功: %s (uuid=%s)", name, node_uuid)

        except Exception as e:
            results.append({"table": name, "status": "failed", "error": str(e)[:150]})
            logger.warning("节点创建失败: %s → %s", name, e)

    return {
        "total": len(tables),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "details": results,
    }
