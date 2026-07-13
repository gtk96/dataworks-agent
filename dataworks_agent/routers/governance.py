"""Governance API — 词根/表名/血缘/总线矩阵/血缘代码导出。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter()


class ParseTableRequest(BaseModel):
    table_name: str


class InferUpdateModeRequest(BaseModel):
    table_name: str


class ParseSqlRequest(BaseModel):
    sql: str


class ParseDdlRequest(BaseModel):
    ddl: str


class LineagePreviewRequest(BaseModel):
    table_name: str
    mc_project: str = ""
    env: str = "prod"


class LineageExportRequest(LineagePreviewRequest):
    excluded_node_ids: list[str] = Field(default_factory=list)


class BusMatrixRegisterRequest(BaseModel):
    domain: str
    dimension: str
    tables: list[str] = Field(default_factory=list)


@router.get("/subject-domains")
async def get_subject_domains():
    from dataworks_agent.governance.warehouse_config import load_subject_domains

    return {"status": "ok", "subject_domains": load_subject_domains()}


@router.get("/update-modes")
async def get_update_modes():
    from dataworks_agent.governance.warehouse_config import load_update_modes

    return {"status": "ok", "update_modes": load_update_modes()}


@router.get("/bus-matrix/rules")
async def get_bus_matrix_rules():
    from dataworks_agent.governance.warehouse_config import load_bus_matrix_rules

    return {"status": "ok", "rules": load_bus_matrix_rules()}


@router.get("/conventions/{layer}")
async def get_layer_conventions(layer: str):
    from dataworks_agent.governance.warehouse_config import load_conventions

    try:
        data = load_conventions(layer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "layer": layer.lower(), "data": data}


@router.get("/warehouse-standards")
async def get_warehouse_standards():
    from dataworks_agent.governance.warehouse_config import load_warehouse_standards_bundle

    return {"status": "ok", "standards": load_warehouse_standards_bundle()}


@router.get("/standards")
async def list_standards():
    from dataworks_agent.standards.loader import list_standard_documents

    return {"status": "ok", "documents": list_standard_documents()}


@router.get("/standards/{doc_id}")
async def get_standard_doc(doc_id: str):
    from dataworks_agent.standards.loader import load_standard_document

    try:
        content = load_standard_document(doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知规范: {doc_id}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "id": doc_id, "content": content}


@router.get("/word-roots")
async def get_word_roots(q: str = "", limit: int = 50):
    from dataworks_agent.cache import get_cache_manager
    from dataworks_agent.governance.word_root_sync import get_word_root_sync_meta
    from dataworks_agent.standards.loader import load_word_root_entries

    cache = get_cache_manager()
    cache_key = f"word_roots:{q}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    entries = load_word_root_entries()
    if q:
        needle = q.strip().lower()
        entries = [
            item
            for item in entries
            if needle in item["column_name"].lower()
            or needle in item.get("column_desc", "").lower()
        ]
    limit = max(1, min(limit, 500))
    meta = get_word_root_sync_meta()

    result = {
        "status": "ok",
        "total": len(entries),
        "entries": entries[:limit],
        "source": meta.get("source", "bundled"),
        "synced_at": meta.get("synced_at", ""),
        "table": meta.get("table", ""),
    }
    cache.set(cache_key, result, ttl=3600)
    return result


@router.post("/word-roots/sync")
async def sync_word_roots():
    """从线上 dim_pub_column_dictionary_static 拉取最新词根并更新本地缓存。"""
    from fastapi import HTTPException

    from dataworks_agent.governance.word_root_sync import run_word_root_sync_once

    try:
        result = await run_word_root_sync_once(force=True)
        if result.get("status") == "failed":
            raise HTTPException(status_code=503, detail=result.get("detail", "词根同步失败"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"词根同步失败: {exc}") from exc


@router.get("/word-roots/sync-status")
async def word_roots_sync_status():
    """词根自动同步状态（间隔、上次结果、本地缓存概况）。"""
    from dataworks_agent.governance.word_root_sync import get_word_root_sync_status

    return {"status": "ok", **get_word_root_sync_status()}


@router.get("/runtime-hints")
async def governance_runtime_hints():
    """治理页运行时提示（MC 项目默认值、通道状态）。"""
    from dataworks_agent.config import settings
    from dataworks_agent.state import app_state

    return {
        "status": "ok",
        "mc_prod_project": settings.dataworks_prod_schema,
        "mc_dev_project": settings.dataworks_dev_schema,
        "maxcompute_project": settings.maxcompute_project,
        "bff_available": getattr(app_state, "_bff_client", None) is not None,
        "openapi_available": getattr(app_state, "_openapi_client", None) is not None,
        "mcp_available": getattr(app_state, "_official_mcp_client", None) is not None,
    }


@router.get("/bus-matrix")
async def get_bus_matrix():
    from dataworks_agent.modeling.bus_matrix import BusMatrixManager

    manager = BusMatrixManager()
    matrix = await manager.get_matrix()
    return {"status": "ok", "matrix": [entry.model_dump() for entry in matrix]}


@router.post("/bus-matrix/register")
async def register_bus_matrix_link(body: BusMatrixRegisterRequest):
    from dataworks_agent.modeling.bus_matrix import BusMatrixManager

    manager = BusMatrixManager()
    await manager.register_link(body.domain, body.dimension, body.tables)
    return {"status": "ok"}


@router.post("/parse-table-name")
async def parse_table_name_api(body: ParseTableRequest):
    from dataworks_agent.governance.table_name_parser import identify_layer_ext, parse_table_name

    parsed = parse_table_name(body.table_name)
    parsed["layer_ext"] = identify_layer_ext(body.table_name)
    return {"status": "ok", "parsed": parsed}


@router.post("/infer-update-mode")
async def infer_update_mode_api(body: InferUpdateModeRequest):
    from dataworks_agent.governance.update_mode_inferer import infer_update_mode

    try:
        result = infer_update_mode(body.table_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result.__dict__}


@router.post("/parse-sql-lineage")
async def parse_sql_lineage_api(body: ParseSqlRequest):
    from dataworks_agent.governance.sql_lineage import parse_sql_lineage

    return {"status": "ok", **parse_sql_lineage(body.sql)}


@router.post("/parse-ddl")
async def parse_ddl_api(body: ParseDdlRequest):
    from dataworks_agent.governance.sql_lineage import parse_ddl_structure

    return {"status": "ok", **parse_ddl_structure(body.ddl)}


@router.post("/lineage/preview")
async def lineage_preview(body: LineagePreviewRequest):
    import asyncio

    from dataworks_agent.governance.lineage_provider import get_lineage_provider
    from dataworks_agent.governance.lineage_service import preview_lineage

    provider = get_lineage_provider(mc_project=body.mc_project or None)

    try:
        return await asyncio.wait_for(
            preview_lineage(
                provider,
                table_name=body.table_name,
                mc_project=body.mc_project or None,
                env=body.env,
            ),
            timeout=90,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="血缘预览超时（>90s）。请缩小表范围或检查 DataWorks 连接。",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="上游服务调用失败，请稍后重试") from exc


@router.post("/lineage/export")
async def lineage_export(body: LineageExportRequest):
    import asyncio

    from dataworks_agent.governance.lineage_provider import get_lineage_provider
    from dataworks_agent.governance.lineage_service import export_lineage

    provider = get_lineage_provider(mc_project=body.mc_project or None)

    try:
        result = await asyncio.wait_for(
            export_lineage(
                provider,
                table_name=body.table_name,
                mc_project=body.mc_project or None,
                env=body.env,
                excluded_node_ids=body.excluded_node_ids,
            ),
            timeout=180,
        )
        zip_name = Path(result["file_path"]).name
        result["download_url"] = f"/api/governance/lineage/download/{zip_name}"
        return result
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="血缘导出超时（>180s）。请缩小范围或检查 DataWorks 连接。",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="上游服务调用失败，请稍后重试") from exc


@router.get("/lineage/download/{filename}")
async def lineage_download(filename: str):
    """下载血缘导出 ZIP（仅允许 archive/lineage_export 目录下的文件名）。"""
    from dataworks_agent.config import settings

    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    zip_path = Path(settings.archive_dir) / "lineage_export" / safe_name
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=safe_name,
    )


class CheckDdlRequest(BaseModel):
    ddl: str


@router.post("/check-ddl")
async def check_ddl_api(body: CheckDdlRequest):
    """检查 DDL 是否符合数仓规范（词根走 MCP 线上词根表）。"""
    from dataworks_agent.governance.ddl_checker import check_ddl_text_async

    return await check_ddl_text_async(body.ddl)
