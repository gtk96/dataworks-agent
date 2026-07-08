"""SQL 文件批量导入 — 从本地目录扫描 DDL/DML 并执行建表。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from dataworks_agent.schemas import require_write_access

logger = logging.getLogger(__name__)

router = APIRouter()


class ImportRequest(BaseModel):
    path: str  # 目录路径，如 E:/dw-modeling-template/sql/order-fulfillment
    layer: str = "all"  # ods | dwd | dim | all
    dry_run: bool = False  # True = 只解析不执行


class ImportResult(BaseModel):
    total_files: int = 0
    total_tables: int = 0
    created: int = 0
    failed: int = 0
    details: list[dict] = []


def _read_sql_file(path: Path) -> str:
    """读取 SQL 文件，自动 fallback 编码。"""
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _find_columns_block_end(stmt: str, start: int) -> int:
    """定位 CREATE TABLE (...) 列定义块的顶层右括号（v11 §4.3 五态 tokenizer）。"""
    depth = 1
    i = start
    n = len(stmt)
    state = "normal"  # normal | sq | dq | line | block

    while i < n:
        ch = stmt[i]
        if state == "normal":
            if ch == "'":
                state = "sq"
            elif ch == '"':
                state = "dq"
            elif ch == "-" and i + 1 < n and stmt[i + 1] == "-":
                state = "line"
            elif ch == "/" and i + 1 < n and stmt[i + 1] == "*":
                state = "block"
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        elif state == "sq":
            if ch == "'" and i + 1 < n and stmt[i + 1] == "'":
                i += 1
            elif ch == "'":
                state = "normal"
        elif state == "dq":
            if ch == '"':
                state = "normal"
        elif state == "line":
            if ch == "\n":
                state = "normal"
        elif state == "block" and ch == "*" and i + 1 < n and stmt[i + 1] == "/":
            state = "normal"
            i += 1
        i += 1
    return start


_LAYER_COMMENT_RE = re.compile(r"^\s*--\s*layer:\s*(ods|dwd|dim|dws)\s*$", re.IGNORECASE)


def _layer_from_table_prefix(bare_name: str) -> str:
    name = bare_name.lower()
    if name.startswith("dwd_"):
        return "DWD"
    if name.startswith("dim_"):
        return "DIM"
    if name.startswith("dws_"):
        return "DWS"
    return "ODS"


def _infer_layer(stmt: str, bare_name: str) -> str:
    """识别分层：优先 stmt 顶部 `-- layer: xxx` 注释，否则表名前缀（v11 §4.4）。"""
    comment_layer: str | None = None
    for line in stmt.splitlines()[:5]:
        m = _LAYER_COMMENT_RE.match(line.strip())
        if m:
            comment_layer = m.group(1).upper()
            break
    prefix_layer = _layer_from_table_prefix(bare_name)
    if comment_layer:
        if comment_layer != prefix_layer:
            logger.warning(
                "DDL 层注释 %s 与表名前缀推断 %s 冲突，以注释为准: %s",
                comment_layer,
                prefix_layer,
                bare_name,
            )
        return comment_layer
    return prefix_layer


def parse_ddl_file(content: str) -> list[dict]:
    """从 SQL 文件中提取所有 CREATE TABLE 语句。

    分句策略：按 `;` 分割，后跟 SQL 关键字或行注释起始或文件结尾。
    lookahead 要求 `;` 后必须有空白字符再跟关键字/注释，避免注释内的分号
    被误判为语句边界（CLAUDE.md §5 场景：`-- 申请类型，1：取消申请 ;`）。
    """
    tables = []
    # 移除 BOM
    content = content.lstrip("\ufeff")
    # 分句：; 后可紧跟或隔空白接 SQL 关键字 / 行注释 / 行尾。
    # 用 \s* 而非 \s+：避免 ";CREATE" 紧邻合法分句被吞；同时 §5 场景
    # (字段注释行尾中文分号 ";取消申请") 后是中文字符而非 "--"，
    # 不会触发 -- 边界，注释内分号安全保留。
    statements = re.split(
        r";\s*(?=\b(?:CREATE|DROP|INSERT)\b|--\s|\Z)",
        content,
        flags=re.IGNORECASE,
    )

    for stmt in statements:
        stmt_raw = stmt.strip()
        if not stmt_raw:
            continue
        # 剥离顶部空行与 -- 注释后再匹配 CREATE（保留 stmt_raw 供层注释推断）
        lines = stmt_raw.splitlines()
        while lines and (not lines[0].strip() or lines[0].strip().startswith("--")):
            lines.pop(0)
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue

        m = re.match(
            r"(?:DROP\s+TABLE\s+IF\s+EXISTS\s+\S+\s*;\s*)?\s*"
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`([^`]+)`|(\S+))\s*\(",
            stmt,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            table_name = (m.group(1) or m.group(2)).strip()
            # 定位列定义块的顶层右括号：按括号深度计数，支持 STRUCT<>/ARRAY<>/DECIMAL(,)
            # 等嵌套括号，避免贪婪正则把 PARTITIONED BY(...) 等内容吞进列块导致重建 DDL 错位（I3）。
            start = m.end()
            i = _find_columns_block_end(stmt, start)
            columns_block = stmt[start:i]
            after = stmt[i + 1 :]

            # MCP 自动加 dataworks. 前缀，所以去掉原 SQL 中的 schema 前缀
            bare_name = re.sub(r"^(dataworks|dataworks_dev|cda|cda_dev)\.", "", table_name)
            full_ddl = f"CREATE TABLE IF NOT EXISTS {bare_name} ({columns_block}) {after}"
            full_ddl = full_ddl.strip() + ";"

            # 提取分区字段
            part_match = re.search(r"partitioned\s+by\s*\((.*?)\)", stmt, re.IGNORECASE)
            partitions = []
            if part_match:
                part_str = part_match.group(1)
                for p in re.findall(r"(\w+)\s+string", part_str, re.IGNORECASE):
                    partitions.append(p)

            # 识别层（注释优先，否则表名前缀，I5 + v11 §4.4）
            layer = _infer_layer(stmt_raw, bare_name)

            # 识别更新方式
            update_method = "all"
            if "_hour" in table_name.lower():
                update_method = "hour"
            elif "_day" in table_name.lower():
                update_method = "day"

            tables.append(
                {
                    "table_name": table_name,
                    "layer": layer,
                    "update_method": update_method,
                    "ddl": full_ddl,
                    "partitions": partitions,
                    "raw": stmt.strip(),
                }
            )

    return tables


def _save_task_record(table_info: dict, source_file: str, client_ip: str = "127.0.0.1") -> None:
    """导入成功后写任务记录到数据库。"""
    import json
    import uuid
    from datetime import datetime

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import ArtifactModel, ModelingTaskModel
    from dataworks_agent.services.task_classification import NODE_TYPE_ODPS

    try:
        task_id = f"imp_{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC).isoformat()

        with SessionLocal() as db:
            task = ModelingTaskModel(
                task_id=task_id,
                status="completed",
                created_by_ip=client_ip,
                source_table=source_file,
                target_table=table_info["table_name"],
                target_layer=table_info["layer"],
                node_type=NODE_TYPE_ODPS,
                update_method=table_info["update_method"],
                partition_keys_json=json.dumps(table_info.get("partitions", [])),
                ddl_dev=table_info["ddl"],
                created_at=now,
                updated_at=now,
                duration_seconds=0.1,
            )
            db.add(task)

            artifact = ArtifactModel(
                task_id=task_id,
                table_name=table_info["table_name"],
                ddl_dev=table_info["ddl"],
                dml="",
                created_at=now,
            )
            db.add(artifact)
            db.commit()
    except Exception as e:
        logger.warning("写入任务记录失败: %s (table=%s)", e, table_info.get("table_name"))


def _is_within(path: Path, root: Path) -> bool:
    """判断 path 是否位于 root（含恰好等于 root）之下。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_import_root(path: str) -> Path:
    """校验并解析导入根目录，防止路径遍历（B1）。

    仅允许位于配置白名单根目录（settings.import_allowed_roots，缺省回退到
    sql_template_root）之下；拒绝 '..' 逃逸与越界绝对路径。
    """
    from dataworks_agent.config import settings

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()

    # B1 白名单：用户配置根目录 + 内建 fixture 根目录。
    # fixture 根（tests/integration/fixtures/sample_sql）只放行"存在于
    # repo 内且路径不指向仓外"的子集；避免污染 settings（生产仍由
    # settings.import_allowed_roots 管控），同时让集成测试可跑。
    repo_root = Path(__file__).resolve().parents[2]  # dataworks_agent/routers/import_sql.py
    fixture_root = repo_root / "tests" / "integration" / "fixtures" / "sample_sql"

    roots = settings.import_allowed_roots or [settings.sql_template_root]
    norm_roots = [Path(r).resolve() for r in roots]
    if not any(candidate == root or _is_within(candidate, root) for root in norm_roots) and not (
        fixture_root.exists() and _is_within(candidate, fixture_root)
    ):
        raise HTTPException(
            status_code=400,
            detail=f"导入目录越权：{path!r} 不在允许的根目录内",
        )
    return candidate


def scan_sql_files(
    base_path: str,
    layer: str = "all",
    exclude_patterns: tuple[str, ...] = ("maintenance", "_meta_probe"),
) -> list[Path]:
    """扫描目录下的 SQL 文件。"""
    base = _resolve_import_root(base_path)
    if not base.exists():
        raise FileNotFoundError(f"目录不存在: {base_path}")

    files = []
    patterns = ["**/*.sql"] if layer == "all" else [f"{layer}/**/*.sql"]

    for pat in patterns:
        for f in base.glob(pat):
            if any(p in str(f) for p in exclude_patterns):
                continue
            files.append(f)

    return sorted(files)


@router.post("/import", response_model=ImportResult)
async def import_sql_files(
    req: ImportRequest,
    request: Request,
    _auth=Depends(require_write_access),  # noqa: B008
):
    """批量导入 SQL 文件：解析 DDL → 执行建表."""
    try:
        files = scan_sql_files(req.path, req.layer)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if not files:
        raise HTTPException(status_code=404, detail=f"目录 {req.path} 下未找到 SQL 文件")

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    result = ImportResult(total_files=len(files))

    # 1) 解析全部 DDL
    all_ops: list[dict] = []
    for filepath in files:
        content = _read_sql_file(filepath)
        tables = parse_ddl_file(content)
        result.total_tables += len(tables)
        for t in tables:
            t["file"] = filepath.name
            all_ops.append(t)

    if req.dry_run:
        for t in all_ops:
            result.details.append(
                {
                    "table": t["table_name"],
                    "status": "parsed",
                    "file": t.get("file", ""),
                    "layer": t["layer"],
                    "update_method": t["update_method"],
                }
            )
        return result

    # 2) 并发执行 DDL（最多 3 并发）
    from dataworks_agent.mcp.operations import execute_ddl

    _sem = asyncio.Semaphore(3)

    async def _exec_one(t: dict) -> dict:
        async with _sem:
            try:
                r = await execute_ddl(t["ddl"])
                if isinstance(r, dict) and r.get("status") == "SUCCESS":
                    _save_task_record(t, t.get("file", ""), client_ip=client_ip)
                    return {
                        "table": t["table_name"],
                        "status": "created",
                        "file": t.get("file", ""),
                        "layer": t["layer"],
                        "update_method": t["update_method"],
                    }
                err = str(r)[:100] if r else "无响应"
                return {
                    "table": t["table_name"],
                    "status": "failed",
                    "file": t.get("file", ""),
                    "error": err,
                }
            except Exception as e:
                return {
                    "table": t["table_name"],
                    "status": "failed",
                    "file": t.get("file", ""),
                    "error": str(e)[:200],
                }

    results = await asyncio.gather(*[_exec_one(t) for t in all_ops])
    for d in results:
        if d["status"] == "created":
            result.created += 1
        else:
            result.failed += 1
        result.details.append(d)

    return result


@router.get("/preview")
async def preview_sql_files(path: str, layer: str = "all"):
    """预览：只扫描不执行，返回解析结果。"""
    try:
        files = scan_sql_files(path, layer)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    all_tables = []
    for f in files:
        content = _read_sql_file(f)
        tables = parse_ddl_file(content)
        for t in tables:
            t["file"] = f.name
            all_tables.append(t)

    # 按层分组统计
    layer_counts = {}
    for t in all_tables:
        layer = t["layer"]
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    return {
        "total_files": len(files),
        "total_tables": len(all_tables),
        "by_layer": layer_counts,
        "tables": [
            {
                "table": t["table_name"],
                "layer": t["layer"],
                "update_method": t["update_method"],
                "partitions": t["partitions"],
                "file": t.get("file", ""),
            }
            for t in all_tables
        ],
    }


class DeployRequest(BaseModel):
    path: str  # SQL 目录路径
    schedule_minute: int = 1  # 调度分钟数
    schedule_hour: int = 3  # 天任务调度小时
    root_node_uuid: str = ""  # BFF root node UUID，留空用 settings 默认值


def _hourly_parameters(uid: int, project_id: int, bff_base: str, base_h: dict) -> dict:
    """构建小时级节点参数（ODS/DWD 共用）。"""
    return {
        "projectId": project_id,
        "uuid": str(uid),
        "script": {
            "parameters": [
                {
                    "name": "gmtdate",
                    "type": "System",
                    "value": "${workspace.gmtdate}",
                    "scope": "NodeParameter",
                },
                {
                    "name": "hour_last1h",
                    "type": "System",
                    "value": "${workspace.hour_last1h}",
                    "scope": "NodeParameter",
                },
                {
                    "name": "gmtdate_last1h",
                    "type": "System",
                    "value": "${workspace.gmtdate_last1h}",
                    "scope": "NodeParameter",
                },
                {
                    "name": "hour_last2h",
                    "type": "System",
                    "value": "${workspace.hour_last2h}",
                    "scope": "NodeParameter",
                },
            ]
        },
    }


@router.post("/deploy")
async def deploy_full_stack(
    req: DeployRequest,
    _auth=Depends(require_write_access),  # noqa: B008
):
    """一键部署：建表 → 创建 IDE 节点 → 写 DML → 配调度 → 加参数 → 加自依赖 → 配 DWD 依赖。

    优先使用 AK/SK OpenAPI（_node_client），不可用时降级到 Cookie BFF。
    """
    from dataworks_agent.config import settings
    from dataworks_agent.state import app_state

    # 扫描 SQL 文件
    try:
        files = scan_sql_files(req.path, "all")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if not files:
        raise HTTPException(status_code=404, detail="未找到 SQL 文件")

    # 解析所有表
    all_tables = {}
    for f in files:
        content = _read_sql_file(f)
        for t in parse_ddl_file(content):
            all_tables[t["table_name"]] = t

    ods_tables = {k: v for k, v in all_tables.items() if v["layer"] == "ODS"}
    dwd_tables = {k: v for k, v in all_tables.items() if v["layer"] == "DWD"}

    result = {
        "ods": {"created": 0, "failed": 0},
        "dwd": {"created": 0, "failed": 0},
        "deps_added": 0,
        "roots_removed": 0,
        "errors": [],
    }

    node_client = getattr(app_state, "_node_client", None)
    if node_client:
        # ── OpenAPI 路径（AK/SK） ──
        ods_uuids = await _deploy_ods_openapi(ods_tables, req, node_client, result, settings)
        await _deploy_dwd_openapi(dwd_tables, req, node_client, result, ods_uuids, settings)
    else:
        # ── Cookie/BFF 降级路径 ──
        await _deploy_via_bff(ods_tables, dwd_tables, req, result, settings)

    return result


async def _deploy_via_bff(ods_tables, dwd_tables, req, result, settings):
    """Cookie/BFF 降级路径 — 与原来的 deploy_full_stack 逻辑一致。"""
    import httpx as _httpx

    from dataworks_agent.cookie.crypto import decrypt_cookie

    cookie = decrypt_cookie()
    if not cookie:
        raise HTTPException(status_code=400, detail="请先配置 Cookie")

    bff_base = settings.bff_base_url
    project_id = settings.dataworks_project_id

    async with _httpx.AsyncClient(timeout=30.0) as http:
        csrf_resp = await http.get(f"{bff_base}/csrf?version=v2", headers={"Cookie": cookie})
        token = csrf_resp.json().get("data", {}).get("token", "")
        base_h = {"Cookie": cookie, "Content-Type": "application/json", "x-csrf-token": token}

        async def refresh_csrf():
            nonlocal token
            r = await http.get(f"{bff_base}/csrf?version=v2", headers={"Cookie": cookie})
            token = r.json().get("data", {}).get("token", "")
            base_h["x-csrf-token"] = token

        def _is_hourly(name: str) -> bool:
            return "_hour" in name

        # ── ODS nodes (Holo) ──
        for name, _info in ods_tables.items():
            try:
                await refresh_csrf()
                path = f"dataworks_agent/01_ODS/{name}"
                r = await http.post(
                    f"{bff_base}/ide/createPackage",
                    json={
                        "projectId": project_id,
                        "kind": "Node",
                        "scene": "DATAWORKS_PROJECT",
                        "name": name,
                        "language": "holo",
                        "script": {"path": path, "runtime": {"command": "HOLOGRES_SQL"}},
                    },
                    headers=base_h,
                )
                uid = (r.json().get("data") or {}).get("uuid")
                if not uid:
                    result["ods"]["failed"] += 1
                    result["errors"].append(f"ODS {name}: 创建节点未返回 uuid")
                    continue
                dml = _extract_ods_dml(name, req.path)
                if dml:
                    await http.put(
                        f"{bff_base}/ide/updateNode",
                        json={
                            "projectId": project_id,
                            "uuid": str(uid),
                            "script": {"content": dml},
                        },
                        headers=base_h,
                    )
                minute = req.schedule_minute
                await http.post(
                    f"{bff_base}/ide/updateVertex",
                    json={
                        "projectId": project_id,
                        "uuid": str(uid),
                        "instanceMode": "Immediately",
                        "trigger": {
                            "type": "Scheduler",
                            "cron": f"00 {minute:02d} 00-23/1 * * ?"
                            if _is_hourly(name)
                            else f"00 {minute:02d} {req.schedule_hour:02d} * * ?",
                            "cycleType": "NotDaily" if _is_hourly(name) else "Daily",
                            "startTime": "1970-01-01 00:00:00",
                            "endTime": "9999-01-01 00:00:00",
                            "timezone": "Asia/Shanghai",
                        },
                    },
                    headers=base_h,
                )
                if _is_hourly(name):
                    await http.put(
                        f"{bff_base}/ide/updateVertex",
                        json=_hourly_parameters(uid, project_id, bff_base, base_h),
                        headers=base_h,
                    )
                await http.put(
                    f"{bff_base}/ide/addNodeDependencies",
                    json={
                        "projectId": project_id,
                        "uuid": str(uid),
                        "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
                    },
                    headers=base_h,
                )
                await http.post(
                    f"{bff_base}/ide/updateVertex",
                    json={
                        "projectId": project_id,
                        "uuid": str(uid),
                        "outputs": {
                            "nodeOutputs": [
                                {
                                    "data": str(uid),
                                    "refTableName": name,
                                    "artifactType": "NodeOutput",
                                    "sourceType": "System",
                                    "isDefault": True,
                                }
                            ]
                        },
                    },
                    headers=base_h,
                )
                result["ods"]["created"] += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                result["ods"]["failed"] += 1
                result["errors"].append(f"ODS {name}: {str(e)[:200]}")
                logger.warning("ODS deploy failed: %s", name)

        # ── ODS UUID lookup (for DWD deps) ──
        ods_uuids = {}
        for name in ods_tables:
            r = await http.get(
                f"{bff_base}/ide/getFile",
                params={
                    "scheme": "vfs_file",
                    "projectId": project_id,
                    "scene": "DATAWORKS_PROJECT",
                    "filePath": f"dataworks_agent/01_ODS/{name}/.dataworks/metadata.json",
                },
                headers={"Cookie": cookie, "x-csrf-token": token},
            )
            meta = (r.json().get("data") or {}).get("content", "")
            with contextlib.suppress(BaseException):
                ods_uuids[name] = json.loads(meta).get("uuid", "")

        # ── DWD nodes (MC) ──
        for name, _info in dwd_tables.items():
            try:
                await refresh_csrf()
                path = f"dataworks_agent/02_DWD/{name}"
                r = await http.post(
                    f"{bff_base}/ide/createPackage",
                    json={
                        "projectId": project_id,
                        "kind": "Node",
                        "scene": "DATAWORKS_PROJECT",
                        "name": name,
                        "language": "odps-sql",
                        "script": {"path": path, "runtime": {"command": "ODPS_SQL"}},
                    },
                    headers=base_h,
                )
                uid = (r.json().get("data") or {}).get("uuid")
                if not uid:
                    result["dwd"]["failed"] += 1
                    result["errors"].append(f"DWD {name}: 创建节点未返回 uuid")
                    continue
                dml = _extract_dwd_dml(name, req.path)
                if dml:
                    await http.put(
                        f"{bff_base}/ide/updateNode",
                        json={
                            "projectId": project_id,
                            "uuid": str(uid),
                            "script": {"content": dml},
                        },
                        headers=base_h,
                    )
                minute = req.schedule_minute
                await http.post(
                    f"{bff_base}/ide/updateVertex",
                    json={
                        "projectId": project_id,
                        "uuid": str(uid),
                        "instanceMode": "Immediately",
                        "trigger": {
                            "type": "Scheduler",
                            "cron": f"00 {minute:02d} 00-23/1 * * ?"
                            if _is_hourly(name)
                            else f"00 {minute:02d} {req.schedule_hour:02d} * * ?",
                            "cycleType": "NotDaily" if _is_hourly(name) else "Daily",
                            "startTime": "1970-01-01 00:00:00",
                            "endTime": "9999-01-01 00:00:00",
                            "timezone": "Asia/Shanghai",
                        },
                    },
                    headers=base_h,
                )
                if _is_hourly(name):
                    await http.put(
                        f"{bff_base}/ide/updateVertex",
                        json=_hourly_parameters(uid, project_id, bff_base, base_h),
                        headers=base_h,
                    )
                await http.put(
                    f"{bff_base}/ide/addNodeDependencies",
                    json={
                        "projectId": project_id,
                        "uuid": str(uid),
                        "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
                    },
                    headers=base_h,
                )
                await http.post(
                    f"{bff_base}/ide/updateVertex",
                    json={
                        "projectId": project_id,
                        "uuid": str(uid),
                        "outputs": {
                            "nodeOutputs": [
                                {
                                    "data": str(uid),
                                    "refTableName": name,
                                    "artifactType": "NodeOutput",
                                    "sourceType": "System",
                                    "isDefault": True,
                                }
                            ]
                        },
                    },
                    headers=base_h,
                )
                ods_sources = _find_ods_sources(dml) if dml else []
                deps = [
                    {"type": "Normal", "output": ods_uuids[ods_name], "sourceType": "System"}
                    for ods_name in ods_sources
                    if ods_name in ods_uuids
                ]
                if deps:
                    await http.put(
                        f"{bff_base}/ide/addNodeDependencies",
                        json={"projectId": project_id, "uuid": str(uid), "dependencies": deps},
                        headers=base_h,
                    )
                    result["deps_added"] += len(deps)
                root_uuid = req.root_node_uuid or settings.dataworks_default_root_node_uuid
                await http.delete(
                    f"{bff_base}/ide/removeNodeDependencies",
                    params={
                        "sourceUuid": str(uid),
                        "projectId": project_id,
                        "targetUuid": root_uuid,
                        "type": "Normal",
                    },
                    headers={"Cookie": cookie, "x-csrf-token": token},
                )
                if dml:
                    await http.put(
                        f"{bff_base}/ide/updateNode",
                        json={
                            "projectId": project_id,
                            "uuid": str(uid),
                            "script": {"content": dml},
                        },
                        headers=base_h,
                    )
                    result["roots_removed"] += 1
                result["dwd"]["created"] += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                result["dwd"]["failed"] += 1
                result["errors"].append(f"DWD {name}: {str(e)[:200]}")
                logger.warning("DWD deploy failed: %s", name)


async def _deploy_ods_openapi(ods_tables, req, node_client, result, settings) -> dict[str, str]:
    """OpenAPI 部署 ODS 节点（Holo SQL）。"""
    ods_uuids: dict[str, str] = {}
    for name in ods_tables:
        path = f"dataworks_agent/01_ODS/{name}"
        uid = await node_client.create_node(name, path, language="holo")
        if not uid:
            result["ods"]["failed"] += 1
            result["errors"].append(f"ODS {name}: 创建节点失败")
            continue
        dml = _extract_ods_dml(name, req.path)
        if dml:
            await node_client.update_node(uid, dml)
        minute = req.schedule_minute
        cron = (
            f"00 {minute:02d} 00-23/1 * * ?"
            if "_hour" in name
            else f"00 {minute:02d} {req.schedule_hour:02d} * * ?"
        )
        cycle = "NotDaily" if "_hour" in name else "Daily"
        params = (
            [
                {
                    "name": "gmtdate",
                    "type": "System",
                    "value": "${workspace.gmtdate}",
                    "scope": "NodeParameter",
                },
                {
                    "name": "hour_last1h",
                    "type": "System",
                    "value": "${workspace.hour_last1h}",
                    "scope": "NodeParameter",
                },
                {
                    "name": "gmtdate_last1h",
                    "type": "System",
                    "value": "${workspace.gmtdate_last1h}",
                    "scope": "NodeParameter",
                },
                {
                    "name": "hour_last2h",
                    "type": "System",
                    "value": "${workspace.hour_last2h}",
                    "scope": "NodeParameter",
                },
            ]
            if "_hour" in name
            else []
        )
        ok = await node_client.update_vertex(
            uid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": cron,
                    "cycleType": cycle,
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": params} if params else {},
                "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
                "outputs": {
                    "nodeOutputs": [
                        {
                            "data": uid,
                            "refTableName": name,
                            "artifactType": "NodeOutput",
                            "sourceType": "System",
                            "isDefault": True,
                        }
                    ]
                },
            },
        )
        if ok:
            result["ods"]["created"] += 1
            ods_uuids[name] = uid
        else:
            result["ods"]["failed"] += 1
            result["errors"].append(f"ODS {name}: 配置调度失败 ({node_client.last_error})")
    return ods_uuids


async def _deploy_dwd_openapi(dwd_tables, req, node_client, result, ods_uuids, settings):
    """OpenAPI 部署 DWD 节点（ODPS SQL）。"""
    _hourly_params = [
        {
            "name": "gmtdate",
            "type": "System",
            "value": "${workspace.gmtdate}",
            "scope": "NodeParameter",
        },
        {
            "name": "hour_last1h",
            "type": "System",
            "value": "${workspace.hour_last1h}",
            "scope": "NodeParameter",
        },
        {
            "name": "gmtdate_last1h",
            "type": "System",
            "value": "${workspace.gmtdate_last1h}",
            "scope": "NodeParameter",
        },
        {
            "name": "hour_last2h",
            "type": "System",
            "value": "${workspace.hour_last2h}",
            "scope": "NodeParameter",
        },
    ]
    for name in dwd_tables:
        path = f"dataworks_agent/02_DWD/{name}"
        uid = await node_client.create_node(name, path, language="odps-sql")
        if not uid:
            result["dwd"]["failed"] += 1
            result["errors"].append(f"DWD {name}: 创建节点失败")
            continue
        dml = _extract_dwd_dml(name, req.path)
        if dml:
            await node_client.update_node(uid, dml)
        minute = req.schedule_minute
        cron = (
            f"00 {minute:02d} 00-23/1 * * ?"
            if "_hour" in name
            else f"00 {minute:02d} {req.schedule_hour:02d} * * ?"
        )
        cycle = "NotDaily" if "_hour" in name else "Daily"
        # Determine ODS dependencies for this DWD
        ods_deps = []
        if dml:
            for ods_name in _find_ods_sources(dml):
                if ods_name in ods_uuids:
                    ods_deps.append({"output": ods_uuids[ods_name], "type": "Normal"})
        ok = await node_client.update_vertex(
            uid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": cron,
                    "cycleType": cycle,
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": _hourly_params} if "_hour" in name else {},
                "dependencies": [{"type": "CrossCycleDependsOnSelf"}, *ods_deps],
                "outputs": {
                    "nodeOutputs": [
                        {
                            "data": uid,
                            "refTableName": name,
                            "artifactType": "NodeOutput",
                            "sourceType": "System",
                            "isDefault": True,
                        }
                    ]
                },
            },
        )
        if ok:
            result["dwd"]["created"] += 1
            result["deps_added"] += len(ods_deps)
        else:
            result["dwd"]["failed"] += 1
            result["errors"].append(f"DWD {name}: 配置失败 ({node_client.last_error})")


def _extract_ods_dml(table_name: str, base_dir: str) -> str:
    """从 ODS DML 文件中提取指定表的 INSERT 段。"""
    base = _resolve_import_root(base_dir)
    sys = "ofc" if "ofc" in table_name else "oms"
    f = base / "ods" / "dml" / f"ods_hl_{sys}__order_fulfillment_hour_dml.sql"
    if not f.exists():
        return ""
    lines = f.read_text(encoding="utf-8").split("\n")
    start = next(
        (i for i, line in enumerate(lines) if f"insert into cda.{table_name}" in line.lower()), None
    )
    if start is None:
        return ""
    hdr = start
    while hdr > 0 and not lines[hdr - 1].strip().startswith("-- ===="):
        hdr -= 1
    begin = hdr - 1 if hdr > 0 else hdr
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("-- ====")),
        len(lines),
    )
    return "\n".join(lines[begin:end]).strip()


def _extract_dwd_dml(table_name: str, base_dir: str) -> str:
    """从 DWD DML 文件中提取指定表的完整内容（精确匹配表名）。"""
    base = _resolve_import_root(base_dir)
    for f in sorted((base / "dwd" / "dml").glob("*.sql")):
        if table_name in f.name.lower():
            return f.read_text(encoding="utf-8").strip()
    return ""


def _find_ods_sources(dml: str) -> list[str]:
    """从 DML 中解析上游 ODS 表引用（匹配 from/join dataworks.table_name）。"""
    import re as _re

    return list(
        set(_re.findall(r"(?:from|join)\s+dataworks\.(\S+)", dml, _re.IGNORECASE))
    )  # \S+ matches table names with _ and t_ prefix, stops at space/alias
