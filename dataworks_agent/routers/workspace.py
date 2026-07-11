"""数据源与工作空间 API — 数据源列表、表列表、Holo 操作、文件目录树。"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from dataworks_agent.config import settings
from dataworks_agent.state import app_state

router = APIRouter()
logger = logging.getLogger(__name__)

_DS_CACHE: dict = {"ts": 0.0, "data": []}
_DS_CACHE_TTL = 20.0


async def _get_datasources_cached(bff) -> list:
    """带短 TTL 的数据源列表缓存，避免 list_datasource_tables 每次重复全量拉取（D5）。"""
    now = time.time()
    if now - _DS_CACHE["ts"] < _DS_CACHE_TTL and _DS_CACHE["data"]:
        return _DS_CACHE["data"]
    data = await bff.list_datasources()
    _DS_CACHE["ts"] = now
    _DS_CACHE["data"] = data
    return data


def _infer_layer_from_table(table_name: str) -> str:
    """从表名前缀推断数仓分层。"""
    lower = table_name.lower()
    if lower.startswith("ods_"):
        return "ODS"
    if lower.startswith("dwd_"):
        return "DWD"
    if lower.startswith("dws_"):
        return "DWS"
    if lower.startswith("dmr_") or lower.startswith("dm_"):
        return "DMR"
    if lower.startswith("dim_"):
        return "DIM"
    return "ODS"


TYPE_LABELS = {
    "holo": "Hologres",
    "hologres": "Hologres",
    "mysql": "MySQL",
    "polardb": "PolarDB",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "oss": "OSS",
    "kafka": "Kafka",
    "elasticsearch": "Elasticsearch",
}


def _get_holo_schemas() -> tuple[str, ...]:
    return tuple(s.strip() for s in settings.holo_native_schemas.split(",") if s.strip())


def _get_holo_instance() -> str:
    return settings.holo_instance_datasource


@router.get("/datasources")
async def list_datasources(
    keyword: str = Query(default=""),
    type: str = Query(default="", description="Filter by datasource type, e.g. holo mysql"),
):
    """获取 DataWorks 项目的数据源列表。"""
    bff = getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 客户端不可用")

    try:
        sources = await bff.list_datasources(keyword)
        internal_types = {"odps", "maxcompute", "analyticsdb"}
        filtered = [
            s
            for s in sources
            if (s.get("type") or s.get("datasourceType", "")).lower() not in internal_types
        ]
        if type:
            want = type.strip().lower()
            aliases = {want}
            if want in {"holo", "hologres"}:
                aliases = {"holo", "hologres"}
            filtered = [
                s
                for s in filtered
                if (s.get("type") or s.get("datasourceType", "")).lower() in aliases
            ]

        logger.debug(
            "list_datasources: keyword=%s, type=%s, result=%d", keyword, type, len(filtered)
        )
        return {
            "datasources": [
                {
                    "name": s.get("name") or s.get("datasourceName", ""),
                    "type": s.get("type") or s.get("datasourceType", ""),
                    "type_label": TYPE_LABELS.get(
                        (s.get("type") or s.get("datasourceType", "")).lower(),
                        s.get("type") or s.get("datasourceType", ""),
                    ),
                    "description": s.get("description", ""),
                }
                for s in filtered
            ],
            "total": len(filtered),
        }
    except Exception as e:
        logger.warning("list_datasources 失败: %s", e)
        raise HTTPException(status_code=502, detail="获取数据源列表失败") from e


@router.get("/datasources/{name}/tables")
async def list_datasource_tables(name: str):
    """列出指定数据源下的表。"""
    bff = getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 客户端不可用")

    sources = await _get_datasources_cached(bff)
    ds_type = ""
    for s in sources:
        ds_name = s.get("datasourceName") or s.get("name", "")
        if ds_name == name:
            ds_type = s.get("datasourceType") or s.get("type", "")
            break

    if not ds_type:
        raise HTTPException(status_code=404, detail=f"数据源 {name} 不存在")

    try:
        tables = await bff.list_datasource_tables(name, ds_type)
        logger.debug("list_datasource_tables: %s (%s), result=%d", name, ds_type, len(tables))
        return {
            "datasource_name": name,
            "tables": [{"name": t.get("tableName") or t.get("name", "")} for t in tables],
            "total": len(tables),
        }
    except Exception as e:
        logger.warning("list_datasource_tables 失败: %s, %s", name, e)
        raise HTTPException(status_code=502, detail="获取表列表失败") from e


@router.get("/holo/schemas")
async def list_holo_native_schemas():
    """列出 Holo 内 Binlog 原生 schema（ofc/oms 等）。"""
    bff = getattr(app_state, "_bff_client", None)
    discovered: set[str] = set(_get_holo_schemas())
    if bff:
        try:
            raw = await bff.list_datasource_tables(_get_holo_instance(), "holo")
            for row in raw:
                name = (row.get("name") or "").strip()
                if "." in name:
                    discovered.add(name.split(".", 1)[0].lower())
        except Exception as exc:
            logger.debug("Holo schema 动态发现失败: %s", exc)
    ordered = [s for s in _get_holo_schemas() if s in discovered]
    ordered.extend(sorted(discovered - set(ordered)))
    return {"schemas": ordered, "holo_instance": _get_holo_instance()}


@router.get("/holo/schemas/{schema}/tables")
async def list_holo_native_tables(schema: str):
    """列出 Holo 读端表名：优先 Holo 连接上的 schema.table，否则用同名 MySQL Reader 辅助。"""
    bff = getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 客户端不可用")

    schema_key = schema.strip().lower()
    if not schema_key:
        raise HTTPException(status_code=400, detail="schema 不能为空")

    tables: list[str] = []
    source = "manual"

    try:
        holo_rows = await bff.list_datasource_tables(_get_holo_instance(), "holo")
        prefix = f"{schema_key}."
        for row in holo_rows:
            full = (row.get("name") or "").strip()
            if full.lower().startswith(prefix):
                tables.append(full.split(".", 1)[1])
        if tables:
            source = "hologres"
    except Exception:
        pass

    if not tables:
        sources = await bff.list_datasources()
        ds_type = ""
        for s in sources:
            if (s.get("datasourceName") or s.get("name", "")).lower() == schema_key:
                ds_type = s.get("datasourceType") or s.get("type", "mysql")
                break
        if ds_type:
            try:
                reader_rows = await bff.list_datasource_tables(schema_key, ds_type)
                tables = sorted(
                    {
                        (r.get("name") or r.get("tableName") or "").strip()
                        for r in reader_rows
                        if (r.get("name") or r.get("tableName") or "").strip()
                    }
                )
                if tables:
                    source = "mysql_reader_hint"
            except Exception:
                pass

    return {
        "schema": schema_key,
        "tables": [{"name": t} for t in tables],
        "total": len(tables),
        "source": source,
        "read_ref": f"{schema_key}.{{table}}",
        "hint": (
            "表名来自同名 MySQL Reader，仅作辅助；Holo SQL 读的是 Holo 实例内表"
            if source == "mysql_reader_hint"
            else ""
        ),
    }


@router.get("/holo/schemas/{schema}/tables/{table_name}/columns")
async def preview_holo_table_columns(
    schema: str,
    table_name: str,
    granularity: str = Query(default="hour"),
    where_mode: str = Query(default="auto"),
):
    """预览 Holo 源表字段（与 MySQL DI 同源：snapshot → DDL registry）。"""
    from dataworks_agent.services.ods_holo.column_resolver import load_holo_ods_columns

    bff = getattr(app_state, "_bff_client", None)
    mcp = app_state.mcp_pool
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 不可用")

    schema_key = schema.strip().lower()
    table_key = table_name.strip()
    if not schema_key or not table_key:
        raise HTTPException(status_code=400, detail="schema 与 table_name 不能为空")

    resolved = await load_holo_ods_columns(
        bff, mcp, schema_key, table_key, granularity, where_mode=where_mode
    )
    if resolved.get("status") != "ok":
        raise HTTPException(status_code=404, detail=resolved.get("error") or "字段解析失败")

    return resolved


@router.get("/repository-tree")
async def list_repository_tree(
    path: str = Query(default=""),
    page_size: int = Query(default=200),
):
    """浏览 IDE 文件目录树（仅返回文件夹）。"""
    bff = getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 客户端不可用")

    try:
        items = []
        page_num = 1
        while True:
            resp = await bff._get(
                "ide/listRepositoryTreeV2",
                {
                    "projectId": bff.project_id,
                    "scene": "DATAWORKS_PROJECT",
                    "path": path,
                    "pageSize": page_size,
                    "pageNum": page_num,
                },
            )
            data = resp.get("data", {})
            batch = data.get("data", [])
            items.extend(batch)
            total = data.get("totalNum", len(batch))
            if page_num * page_size >= total:
                break
            page_num += 1

        logger.debug("repository-tree: path=%s, result=%d", path, len(items))
        return {
            "nodes": [
                {
                    "uuid": item.get("uuid", ""),
                    "name": item.get("name", ""),
                    "type": item.get("type", "folder"),
                    "path": item.get("path", ""),
                    "depth": item.get("depth", 0),
                }
                for item in items
            ],
            "total": len(items),
        }
    except Exception as e:
        logger.warning("repository-tree 失败: path=%s, %s", path, e)
        raise HTTPException(status_code=502, detail="获取目录树失败") from e


class PreviewHoloDmlRequest(BaseModel):
    holo_schema: str = ""
    datasource_name: str = ""
    table_name: str
    granularity: str = "hour"
    where_mode: str = "auto"


class CreateHoloRequest(BaseModel):
    datasource_name: str = ""
    holo_schema: str = ""
    table_name: str
    script_path: str = settings.holo_ods_node_path
    granularity: str = "hour"
    resource_group: str = ""
    schedule_minute: int = 1
    where_mode: str = "auto"


class InitializationOptions(BaseModel):
    dev_mc_project: str = ""
    prod_mc_project: str = ""
    init_partition_date: str = "20170101"
    init_partition_hour: str = "00"
    allow_empty_source: bool = False
    publish_incremental_after_init: bool = True
    first_incremental_lookback_hours: int | None = None


class CreateDIRequest(BaseModel):
    datasource_name: str
    table_name: str
    script_path: str = "dataworks_agent/01_ODS"
    granularity: str = "hour"
    resource_group: str = ""
    schedule_minute: int = 1
    source_type: str = ""
    with_initialization: bool = False
    initialization: InitializationOptions | None = None


@router.post("/create-di-node")
async def create_di_node(req: CreateDIRequest, request: Request):
    """完整四阶段 DI 管线：字段推断 → 建表 → 生成配置 → 创建节点。"""
    from dataworks_agent.naming import generate_ods_di_table_name
    from dataworks_agent.services.di_pipeline import DIPipeline
    from dataworks_agent.services.task_classification import NODE_TYPE_DI
    from dataworks_agent.services.task_registry import record_task
    from dataworks_agent.state import app_state

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")

    bff = getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 不可用")
    mcp = app_state.mcp_pool
    if not mcp:
        raise HTTPException(status_code=503, detail="MCP 不可用")

    di_source_type = (req.source_type or "mysql").strip().lower()
    if di_source_type in {"holo", "hologres"}:
        di_source_type = "hologres"

    target_table = generate_ods_di_table_name(
        req.datasource_name,
        req.table_name,
        req.granularity,
        source_type=di_source_type,
    )

    init_config = req.initialization.model_dump() if req.initialization else None

    pipeline = DIPipeline(
        bff_client=bff,
        mcp_pool=mcp,
        node_client=getattr(app_state, "_node_client", None),
        mc_client=getattr(app_state, "_maxcompute_client", None),
    )
    result = await pipeline.run(
        datasource_name=req.datasource_name,
        source_table=req.table_name,
        target_table=target_table,
        granularity=req.granularity,
        script_path=req.script_path,
        schedule_minute=req.schedule_minute,
        resource_group=req.resource_group,
        source_type=di_source_type,
        with_initialization=req.with_initialization,
        init_config=init_config,
    )

    di_uuid = ""
    if req.with_initialization:
        di_uuid = (
            (result.get("incremental") or {}).get("steps", {}).get("create_node", {}).get("uuid")
            or (result.get("initialization") or {})
            .get("steps", {})
            .get("create_node", {})
            .get("uuid")
            or ""
        )
    else:
        di_uuid = (result.get("steps") or {}).get("create_node", {}).get("uuid", "")

    record_task(
        node_type=NODE_TYPE_DI,
        target_table=result.get("target_table", target_table),
        source_table=f"{req.datasource_name}.{req.table_name}",
        target_layer="ODS",
        status="completed" if result.get("success") else "failed",
        created_by_ip=client_ip,
        node_uuid=str(di_uuid or ""),
        error_message="" if result.get("success") else str(result.get("steps", ""))[:500],
    )

    if req.with_initialization:
        return {
            "status": "ok" if result["success"] else "partial",
            "target_table": result.get("target_table", target_table),
            "initialization": result.get("initialization", {}),
            "incremental": result.get("incremental", {}),
            "publish_gate": result.get("publish_gate", {}),
        }

    return {
        "status": "ok" if result["success"] else "partial",
        "target_table": target_table,
        "steps": result["steps"],
    }


@router.post("/preview-holo-dml")
async def preview_holo_dml(req: PreviewHoloDmlRequest):
    """预览 ODS Holo DML（字段对齐 registry + 完整调度参数，不创建节点）。"""
    from dataworks_agent.naming import generate_ods_di_table_name
    from dataworks_agent.services.ods_holo.dml_generator import (
        OdsMetadataMissingError,
        build_holo_ods_dml,
    )
    from dataworks_agent.state import app_state

    holo_schema = (req.holo_schema or req.datasource_name).strip().lower()
    if not holo_schema:
        raise HTTPException(status_code=400, detail="请指定 Holo 原生 schema")

    bff = getattr(app_state, "_bff_client", None)
    mcp = app_state.mcp_pool
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 不可用")

    target_table = generate_ods_di_table_name(
        holo_schema, req.table_name, req.granularity, source_type="hologres"
    )
    try:
        built = await build_holo_ods_dml(
            bff,
            mcp,
            holo_schema=holo_schema,
            source_table=req.table_name,
            target_table=target_table,
            granularity=req.granularity,
            where_mode=req.where_mode,
        )
    except OdsMetadataMissingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "target_table": target_table,
        "holo_read_ref": f"{holo_schema}.{req.table_name}",
        "dml": built["dml"],
        "column_count": built.get("column_count", 0),
        "where_clause": built.get("where_clause", ""),
        "parameters": built.get("parameters", []),
    }


@router.post("/create-holo-node")
async def create_holo_node(req: CreateHoloRequest, request: Request):
    """创建 Holo SQL ODS 节点（生产 DML + 完整调度参数 + 自依赖，不自动发布）。"""
    import logging

    from dataworks_agent.naming import generate_cron, generate_node_path, generate_ods_di_table_name
    from dataworks_agent.naming.schedule import get_cycle_type
    from dataworks_agent.services.ods_holo.dml_generator import (
        OdsMetadataMissingError,
        build_holo_ods_dml,
    )
    from dataworks_agent.services.task_classification import NODE_TYPE_HOLO
    from dataworks_agent.services.task_registry import record_task
    from dataworks_agent.state import app_state

    logger = logging.getLogger(__name__)
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")

    bff = getattr(app_state, "_bff_client", None)
    mcp = app_state.mcp_pool
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 不可用")

    holo_schema = (req.holo_schema or req.datasource_name).strip().lower()
    if not holo_schema:
        raise HTTPException(status_code=400, detail="请指定 Holo 原生 schema（如 ofc/oms）")

    target_table = generate_ods_di_table_name(
        holo_schema,
        req.table_name,
        req.granularity,
        source_type="hologres",
    )
    node_path = generate_node_path(req.script_path, target_table)

    from dataworks_agent.services.ods_holo.column_resolver import load_holo_ods_columns
    from dataworks_agent.services.ods_holo.ensure_table import ensure_holo_table

    resolved = await load_holo_ods_columns(bff, mcp, holo_schema, req.table_name, req.granularity)
    source_columns = resolved.get("source_columns") or []

    ensure_result = await ensure_holo_table(
        bff,
        mcp,
        holo_schema=holo_schema,
        source_table=req.table_name,
        target_table=target_table,
        granularity=req.granularity,
        source_columns=source_columns,
        mc=getattr(app_state, "_maxcompute_client", None),
    )
    if ensure_result.get("status") == "failed":
        logger.warning("ensure_table 失败（不阻塞节点创建）: %s", ensure_result.get("error"))

    try:
        built = await build_holo_ods_dml(
            bff,
            mcp,
            holo_schema=holo_schema,
            source_table=req.table_name,
            target_table=target_table,
            granularity=req.granularity,
            where_mode=req.where_mode,
        )
    except OdsMetadataMissingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dml = built["dml"]
    parameters = built.get("parameters") or []

    gran = req.granularity if req.granularity in ("hour", "hourly", "day", "all", "min") else "hour"
    schedule_gran = "hour" if gran == "min" else gran
    minute = req.schedule_minute
    cron = generate_cron(schedule_gran, minute=minute)  # type: ignore[arg-type]
    cycle_type = get_cycle_type(schedule_gran)  # type: ignore[arg-type]

    # 节点操作优先走 AK/SK 适配器（holo 建节点已真机验证）；元数据读取仍走 bff
    nodes = getattr(app_state, "_node_client", None) or bff

    existing_uuid = await nodes.get_node_uuid_by_path(node_path)
    if existing_uuid:
        logger.info("节点已存在，更新 SQL 和配置: %s (%s)", target_table, existing_uuid)
        uid = existing_uuid
        node_action = "updated"
    else:
        uid = await nodes.create_node(target_table, node_path, language="holo")
        if not uid:
            raise HTTPException(
                status_code=500, detail=f"创建节点失败: {getattr(nodes, 'last_error', '')}"
            )
        node_action = "created"

    # IMPORT FOREIGN SCHEMA 随 DML 留在节点内容里，由 DataWorks(HOLOGRES_SQL) 执行，
    # 平台不直连 Holo 跑（IMPORT ... OPTIONS(if_table_exist 'update') 幂等，每次运行安全）。
    await nodes.update_node(uid, dml)
    await nodes.update_vertex(
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
                        "refTableName": target_table,
                        "artifactType": "NodeOutput",
                        "sourceType": "System",
                        "isDefault": True,
                    }
                ]
            },
        },
    )

    record_task(
        node_type=NODE_TYPE_HOLO,
        target_table=target_table,
        source_table=f"{holo_schema}.{req.table_name}",
        target_layer=_infer_layer_from_table(target_table),
        status="completed",
        created_by_ip=client_ip,
        node_uuid=uid,
    )

    return {
        "status": "ok",
        "action": node_action,
        "table": target_table,
        "uuid": uid,
        "column_count": built.get("column_count", 0),
        "ensure_table": ensure_result,
    }


@router.get("/search-tables")
async def search_mc_tables(keyword: str = Query(...), page_size: int = Query(default=50)):
    """搜索 MaxCompute 表（支持中文注释匹配）。"""
    if len(keyword.strip()) < 2:
        raise HTTPException(status_code=400, detail="关键词至少 2 个字符")
    bff = getattr(app_state, "_bff_client", None)
    if not bff:
        raise HTTPException(status_code=503, detail="BFF 客户端不可用")

    try:
        tables = await bff.search_tables(keyword, page_size)
        logger.debug("search_tables: keyword=%s, result=%d", keyword, len(tables))
        return {"tables": tables, "total": len(tables)}
    except Exception as e:
        logger.warning("search_tables 失败: %s, %s", keyword, e)
        raise HTTPException(status_code=502, detail="搜索表失败") from e
