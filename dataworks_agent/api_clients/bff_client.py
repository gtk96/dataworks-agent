"""DataWorks BFF API 客户端 — 完整移植自 data-development-design 项目。

支持的端点:
- SQL 执行: createExecutorJobV3, getExecutorJobLog, getExecutorJobResult
- IDA 执行: createExecutorJob4Ida, getExecutorJobLog4Ida (免资源组)
- 节点管理: createPackage, getNodeList, updateNode, updateVertex, getVertex, getFile
- 元数据: geneCreationDdl, searchTables, getTableUpstreamTasks, listLineage
- 数据源: ListDatasources2, getTableListPost
- 部署: sceneTemplate, deployPackages
- 鉴权: 动态 CSRF token (/csrf?version=v2), Cookie 本地文件
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from dataworks_agent.config import settings
from dataworks_agent.cookie.crypto import decrypt_cookie
from dataworks_agent.middleware.circuit_breaker import bff_breaker
from dataworks_agent.services.ods_oss.directory_guard import (
    ExistingDirectoryEvidence,
    find_node_by_path,
    infer_existing_directory,
    node_record_uuid,
    normalize_node_path,
    parent_node_path,
)

logger = logging.getLogger(__name__)


# ── 域 mixin ───────────────────────────────────────────────
# 文件内拆分:把 22 个 public 方法按 CLAUDE.md §6 映射表的 5 个域切分,
# 主类只保留 __init__ + HTTP/Auth 基础设施(被所有域方法依赖)。
# 0 行为改动:方法体逐字保留,__init__ 不变,imports 不变。


class _SqlExecMixin:
    """SQL 执行:createExecutorJobV3 / IDA / 轮询日志 / 查询结果。"""

    # ── SQL 执行 ─────────────────────────────────────────────

    async def execute_sql(self, sql: str, params: dict | None = None) -> str | None:
        """通过 createExecutorJobV3 执行 SQL，返回 jobCode。"""
        payload = {
            "appName": "VS_CODE_IDE_PERSONAL_WORKSPACE",
            "paramMap": params or {},
            "projectId": self.project_id,
            "scriptContent": sql,
            "nodeType": 10,
            "resourceGroupCode": self.resource_group,
            "expandMap": {},
            "envMap": {"engineConfig": {}, "executorConfig": {"cu": "0.25"}, "version": 2},
        }
        try:
            resp = await self._post("ide/createExecutorJobV3", payload)
            job = (resp.get("data") or {}).get("jobCode")
            if not job:
                self.last_error = f"createExecutorJobV3: {resp.get('message', '?')}"
            return job
        except Exception as e:
            self.last_error = str(e)
            return None

    async def execute_sql_ida(self, sql: str) -> str | None:
        """通过 IDA 接口执行 SQL（免资源组，所有账号可执行）。"""
        payload = {
            "appName": "DATAWORKS_DATA_ANALYSIS",
            "paramMap": {},
            "projectId": self.project_id,
            "scriptContent": sql,
            "nodeType": 10,
            "dataSourcePolicyType": "DATASOURCE_CONFIG",
            "language": "odps-sql",
            "dataSourceId": settings.dataworks_datasource_id,
            "expandMap": {"FILE_ID_KEY": -1, "FILE_NAME_KEY": "dw_auto_query"},
            "envMap": {"engineConfig": {}, "executorConfig": {}, "version": 2},
        }
        try:
            resp = await self._post("da/createExecutorJob4Ida", payload)
            job = (resp.get("data") or {}).get("jobCode")
            if not job:
                self.last_error = f"createExecutorJob4Ida: code={resp.get('code')}, message={resp.get('message', '?')}"
                logger.warning("execute_sql_ida 响应无 jobCode: %s", resp)
            return job
        except Exception as e:
            self.last_error = str(e)
            return None

    async def wait_job(self, job_code: str, max_retry: int = 30, interval: int = 3) -> bool:
        """轮询 ide/getExecutorJobLog 等待 SQL 完成。"""
        offset = 0
        for _attempt in range(max_retry):
            try:
                resp = await self._get(
                    "ide/getExecutorJobLog",
                    {
                        "code": job_code,
                        "index": 0,
                        "offset": offset,
                        "extend": True,
                        "showScript": False,
                        "projectId": self.project_id,
                    },
                )
                if resp.get("code") != 200:
                    await asyncio.sleep(interval)
                    continue
                data = resp.get("data", {}) or {}
                status = (data.get("status") or "").upper()
                length = data.get("length")
                if isinstance(length, int) and length > 0:
                    offset += length
                if status in ("SUCCESS", "SUCCEED") and data.get("end"):
                    return True
                if status in ("FAILED", "FAIL", "CANCELLED", "CANCEL"):
                    err = (data.get("extended") or {}).get("errorMessage", "")
                    self.last_error = err[:400]
                    return False
                await asyncio.sleep(interval)
            except Exception:
                await asyncio.sleep(interval)
        return False

    async def get_query_result(self, job_code: str) -> dict | None:
        """获取 SQL 查询结果（v1/getExecutorJobResult）。"""
        resp = await self._get(
            "v1/getExecutorJobResult",
            {
                "code": job_code,
                "index": 0,
                "extend": True,
            },
        )
        if resp.get("code") == 200:
            return resp.get("data")
        return None

    async def wait_ida_job(self, job_code: str, max_retry: int = 30, interval: int = 3) -> bool:
        """轮询 IDA 执行日志等待完成（da/getExecutorJobLog4Ida）。"""
        offset = 0
        for _attempt in range(max_retry):
            try:
                resp = await self._get(
                    "da/getExecutorJobLog4Ida",
                    {
                        "projectId": str(self.project_id),
                        "jobCode": job_code,
                        "needExtend": "true",
                        "index": "0",
                        "offset": str(offset),
                        "needShowScript": "false",
                    },
                )
                if resp.get("code") != 200:
                    await asyncio.sleep(interval)
                    continue
                data = resp.get("data", {}) or {}
                status = (data.get("status") or "").upper()
                if status == "FAIL":
                    status = "FAILED"
                length = data.get("length")
                if isinstance(length, int) and length > 0:
                    offset += length
                if status in ("SUCCESS", "SUCCEED") and data.get("end") is True:
                    return True
                if status in ("FAILED", "CANCELLED", "CANCEL"):
                    err = (data.get("extended") or {}).get("errorMessage", data.get("content", ""))
                    self.last_error = str(err)[:400]
                    return False
                await asyncio.sleep(interval)
            except Exception:
                await asyncio.sleep(interval)
        self.last_error = f"IDA 执行超时 ({max_retry * interval}s)"
        return False


class _IntegrationMixin:
    """数据集成 (DI):节点创建 + 手动试跑执行器配置 + 响应解析。"""

    async def create_di_node(
        self, name: str, path: str, source_ds: str, source_table: str, target_table: str
    ) -> str | None:
        """创建数据集成 (DI) 节点，返回节点 UUID。"""
        import json as _json

        di_config = {
            "reader": {
                "plugin": "mysql",
                "datasource": source_ds,
                "table": source_table,
                "column": ["*"],
                "where": "",
                "splitPk": "",
            },
            "writer": {
                "plugin": "odps",
                "table": target_table,
                "column": ["*"],
                "partition": "dt='${bizdate}'",
            },
        }
        wrapped = {
            "extend": {"__new__": True, "formatType": "filespec"},
            "jobType": "SingleTableOfflineMigration",
            "migrationType": "SingleTableOffline",
            "externalCode": di_config,
        }
        script_content = _json.dumps(wrapped, ensure_ascii=False)

        payload = {
            "projectId": self.project_id,
            "kind": "Node",
            "scene": "DATAWORKS_PROJECT",
            "name": name,
            "script": {
                "path": path,
                "runtime": {"command": "DI"},
                "content": script_content,
            },
        }
        resp = await self._post("ide/createPackage", payload)
        data = resp.get("data")
        if isinstance(data, dict) and data.get("uuid"):
            return str(data["uuid"])
        return None

    async def create_di_executor_job(
        self,
        *,
        script_content: str,
        resource_group_code: str,
        package_uuid: str,
        file_name: str,
        param_map: dict | None = None,
    ) -> str | None:
        """通过 ide/createExecutorJobV3 手动运行未发布的 DI 节点。"""
        payload = {
            "appName": "VS_CODE_IDE",
            "paramMap": param_map or {},
            "projectId": self.project_id,
            "scriptContent": script_content,
            "nodeType": 23,
            "resourceGroupCode": resource_group_code,
            "expandMap": {
                "FILE_ID_KEY": package_uuid,
                "FILE_NAME_KEY": file_name,
            },
            "envMap": {"engineConfig": {}, "executorConfig": {}, "version": 2},
        }
        try:
            resp = await self._post("ide/createExecutorJobV3", payload)
            job = (resp.get("data") or {}).get("jobCode")
            if not job:
                self.last_error = f"createExecutorJobV3 DI: {resp.get('message', '?')}"
            return job
        except Exception as e:
            self.last_error = str(e)
            return None

    async def write_executor_config(
        self,
        *,
        entity_uuid: str,
        resource_group_identifier: str,
        script_params: dict | None = None,
    ) -> bool:
        """保存 DI 手动运行的执行器配置。"""
        payload = {
            "sourceAppName": "VS_CODE_IDE",
            "entityUuid": entity_uuid,
            "replaceAll": True,
            "nodeTypeName": "DI",
            "additionalOptions": {},
            "scriptParam": [
                {"name": name, "value": value} for name, value in (script_params or {}).items()
            ],
            "resourceGroupIdentifier": resource_group_identifier,
            "executeMode": "COMPUTE_RESOURCE",
        }
        try:
            resp = await self._post("ide/writeExecutorConfig", payload)
            return resp.get("code") == 200 and resp.get("data") is True
        except Exception as e:
            self.last_error = str(e)
            return False

    @staticmethod
    def parse_ide_file(resp: dict) -> dict:
        """从 ide/getFile 响应中提取 content/uuid/bizId。"""
        data = resp.get("data") if isinstance(resp, dict) else {}
        if not isinstance(data, dict):
            return {}
        content = data.get("content", "")
        if isinstance(content, dict):
            content = content.get("content") or content.get("text") or ""
        return {
            "content": str(content or ""),
            "uuid": str(data.get("uuid") or data.get("fileId") or ""),
            "bizId": str(data.get("bizId") or data.get("packageUuid") or ""),
        }


class _NodeLifecycleMixin:
    """节点生命周期:创建 / 列表(带缓存) / 更新脚本 / 读取 VFS / UUID 解析。"""

    async def create_node(self, name: str, path: str, language: str = "odps-sql") -> str | None:
        """Create or reuse a node under an existing DataWorks directory.

        Node creation is allowed. Folder creation is not: an exact existing
        node is reused, otherwise the parent directory must be positively
        confirmed before createPackage is called.
        """
        normalized_path = normalize_node_path(path)
        try:
            existing_uuid = await self.get_node_uuid_by_path(normalized_path)
        except Exception as exc:
            self.last_error = f"existing node lookup failed: {exc}"
            return None
        if existing_uuid:
            return existing_uuid

        parent_path = parent_node_path(normalized_path)
        evidence = await self.check_existing_directory(parent_path)
        if not evidence.confirmed:
            self.last_error = (
                f"parent directory not confirmed: {parent_path}; "
                "createPackage skipped to prevent folder creation"
            )
            return None

        runtime_cmd = "HOLOGRES_SQL" if language == "holo" else "ODPS_SQL"
        try:
            resp = await self._post(
                "ide/createPackage",
                {
                    "projectId": self.project_id,
                    "kind": "Node",
                    "scene": "DATAWORKS_PROJECT",
                    "name": name,
                    "language": language,
                    "script": {"path": normalized_path, "runtime": {"command": runtime_cmd}},
                },
            )
        except Exception as exc:
            self.last_error = f"createPackage: {exc}"
            return None

        data = resp.get("data")
        if isinstance(data, dict):
            uuid = data.get("uuid")
            if uuid:
                return str(uuid)

        if resp.get("code") == 200:
            await asyncio.sleep(2)
            existing_uuid = await self.get_node_uuid_by_path(normalized_path)
            if existing_uuid:
                return existing_uuid

        self.last_error = (
            f"createPackage: code={resp.get('code')}, "
            f"message={resp.get('message') or 'uuid not returned'}"
        )
        return None

    async def get_node_list(
        self, search: str = "", page_size: int = 100, env: str = "prod", force_refresh: bool = False
    ) -> list[dict]:
        """获取节点列表（workbench/getNodeList），支持翻页和缓存。"""
        if (
            not force_refresh
            and not search
            and self._node_list_cache
            and time.time() - self._node_list_cache_time < 600
        ):
            return self._node_list_cache

        all_nodes = []
        page_num = 1
        while True:
            params = {
                "projectId": self.project_id,
                "env": env,
                "tenantId": self.tenant_id,
                "pageNum": page_num,
                "pageSize": page_size,
                "sortOrder": "",
                "sortField": "",
                "includeRelation": "false",
                "expired": "false",
                "lonely": "false",
            }
            if search:
                params["searchText"] = search
            resp = await self._get("workbench/getNodeList", params)
            data_block = resp.get("data", {}) or {}
            page_nodes = data_block.get("data", []) or []
            total = data_block.get("totalNum", len(page_nodes))
            all_nodes.extend(page_nodes)

            total_pages = (total + page_size - 1) // page_size if page_size else 1
            if page_num >= total_pages:
                break
            page_num += 1

        if not search:
            self._node_list_cache = all_nodes
            self._node_list_cache_time = time.time()
        return all_nodes

    async def update_node(self, uuid: str, content: str) -> bool:
        """Write node script content through ide/updateNode."""
        try:
            resp = await self._put(
                "ide/updateNode",
                {
                    "projectId": self.project_id,
                    "uuid": str(uuid),
                    "script": {"content": content},
                },
            )
        except Exception as exc:
            self.last_error = f"updateNode: {exc}"
            return False
        if resp.get("code") != 200:
            self.last_error = (
                f"updateNode: code={resp.get('code')}, "
                f"message={resp.get('message') or 'request failed'}"
            )
            return False
        return True

    async def get_file(self, file_path: str) -> dict:
        """读取 VFS 文件内容（ide/getFile, scheme=vfs_file）。"""
        return await self._get(
            "ide/getFile",
            {
                "scheme": "vfs_file",
                "projectId": self.project_id,
                "scene": "DATAWORKS_PROJECT",
                "filePath": file_path,
            },
        )

    async def get_node_uuid_by_path(self, node_dir: str) -> str | None:
        """Resolve a node UUID by exact DataWorks script path, read-only."""
        target = normalize_node_path(node_dir)
        records = await self.get_node_list(force_refresh=True)
        match = find_node_by_path(records, target)
        if match:
            return node_record_uuid(match) or None

        # Some BFF deployments do not expose Script.Path in getNodeList.
        # Keep metadata.json as a read-only fallback, never fuzzy name matching.
        resp = await self.get_file(f"{target}/.dataworks/metadata.json")
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        content_str = data.get("content", "") if isinstance(data, dict) else ""
        if not content_str:
            return None
        try:
            import json

            uuid = json.loads(content_str).get("uuid", "")
            return str(uuid) if uuid else None
        except Exception:
            return None

    async def check_existing_directory(self, directory_path: str) -> ExistingDirectoryEvidence:
        """Confirm an existing parent directory without creating or deleting it."""
        target = normalize_node_path(directory_path)
        if not target:
            return ExistingDirectoryEvidence.from_check(target, "invalid_path", False)

        try:
            records = await self.get_node_list(force_refresh=True)
            if infer_existing_directory(records, target):
                return ExistingDirectoryEvidence.from_check(target, "node_path", True)
        except Exception as exc:
            logger.debug("directory node evidence lookup failed: %s", exc)

        try:
            resp = await self.get_file(f"{target}/.dataworks/metadata.json")
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            if isinstance(data, dict) and (
                data.get("content") or data.get("uuid") or data.get("kind")
            ):
                return ExistingDirectoryEvidence.from_check(target, "vfs_metadata", True)
        except Exception as exc:
            logger.debug("directory metadata lookup failed: %s", exc)

        return ExistingDirectoryEvidence.from_check(target, "no_positive_evidence", False)

    async def get_node_code(self, node_id: int, *, env: str = "prod") -> dict | None:
        """获取节点代码（workbench/getNodeCode）。"""
        try:
            resp = await self._get(
                "workbench/getNodeCode",
                {
                    "projectId": self.project_id,
                    "env": env,
                    "nodeId": node_id,
                },
            )
            if resp.get("code") != 200:
                self.last_error = resp.get("message", "getNodeCode failed")
                return None
            data = resp.get("data")
            if data is None:
                return None
            return data if isinstance(data, dict) else {"code": data}
        except Exception as exc:
            self.last_error = str(exc)
            return None

    async def delete_package(self, vertex_uuid: str) -> bool:
        """删除 IDE 节点包（ide/deletePackage）。执行层拦截破坏性操作（v9 §3.1）。"""
        from dataworks_agent.api_clients.destructive_guard import (
            DestructiveOpBlockedError,
            guard_node_op,
        )

        try:
            guard_node_op("DELETE_NODE")
        except DestructiveOpBlockedError as exc:
            self.last_error = str(exc)
            return False

        resp = await self._post(
            "ide/deletePackage",
            {"projectId": self.project_id, "uuid": str(vertex_uuid)},
        )
        return resp.get("code") == 200


class _ScheduleMixin:
    """调度 / 工作流依赖 / 部署发布。"""

    async def update_vertex(
        self, uuid: str, config: dict | None = None, instance_mode: str = "Immediately"
    ) -> bool:
        """Update scheduling, dependency, and output configuration."""
        if config is None:
            config = {}
        payload = {
            "projectId": self.project_id,
            "uuid": str(uuid),
            "instanceMode": instance_mode,
        }
        for key in ("trigger", "script", "strategy", "dependencies", "resourceGroup", "outputs"):
            if key in config:
                payload[key] = config[key]
        try:
            resp = await self._post("ide/updateVertex", payload)
        except Exception as exc:
            self.last_error = f"updateVertex: {exc}"
            return False
        if resp.get("code") != 200:
            self.last_error = (
                f"updateVertex: code={resp.get('code')}, "
                f"message={resp.get('message') or 'request failed'}"
            )
            return False
        return True

    async def get_vertex(self, uuid: str) -> dict:
        """获取节点详情。"""
        return await self._get(
            "ide/getVertex",
            {
                "projectId": self.project_id,
                "uuid": str(uuid),
            },
        )

    async def get_node_parents_by_depth(
        self,
        node_id: int,
        *,
        env: str = "prod",
        depth: int = 1,
    ) -> list[dict] | None:
        """获取节点上游父依赖（workbench/getNodeListByDepth）。"""
        try:
            resp = await self._get(
                "workbench/getNodeListByDepth",
                {
                    "projectId": self.project_id,
                    "env": env,
                    "tenantId": self.tenant_id,
                    "relation": "parent",
                    "nodeIds": str(node_id),
                    "nodeId": str(node_id),
                    "depth": depth,
                    "detail": "false",
                    "dagScene": 1,
                },
            )
            if resp.get("code") != 200:
                self.last_error = resp.get("message", "getNodeListByDepth failed")
                return None
            data = resp.get("data") or []
            return data if isinstance(data, list) else []
        except Exception as exc:
            self.last_error = str(exc)
            return None

    async def deploy_nodes(self, node_uuids: list[str], comment: str = "") -> bool:
        """部署/发布节点到生产环境。"""
        template = await self._post(
            "ide/sceneTemplate",
            {
                "projectId": self.project_id,
                "product": "DATA_STUDIO_V2",
                "module": "DEPLOY_NODE_WITH_CHECK",
            },
        )
        scene_id = (template.get("data") or {}).get("uuid")
        if not scene_id:
            return False
        resp = await self._post(
            "ide/deployPackages",
            {
                "projectId": self.project_id,
                "sceneId": scene_id,
                "nodeUuidList": node_uuids,
                "comment": comment or "dw-agent auto deploy",
            },
        )
        return resp.get("code") == 200


class _MetadataLineageMixin:
    """元数据 / 血缘 / 数据源浏览。"""

    # -- Data albums (DataMap, Cookie fallback) ------------------------------

    @staticmethod
    def _album_page_items(data: object) -> list[dict]:
        """Extract list items from the BFF's known paged response variants."""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("data", "list", "items", "records", "albumList", "entityList"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    async def list_meta_albums(self, page_size: int = 100) -> list[dict]:
        """List visible DataMap albums through the long-lived Cookie fallback."""
        resp = await self._get(
            "dma/list",
            {"pageSize": page_size, "pageNum": 1, "scene": "all"},
        )
        if resp.get("code") not in (200, "200"):
            return []
        return self._album_page_items(resp.get("data"))

    async def get_meta_album(self, album_id: int) -> dict | None:
        """Return one album's detail block."""
        resp = await self._get("dma/detail_2", {"albumId": album_id})
        data = resp.get("data")
        return data if resp.get("code") in (200, "200") and isinstance(data, dict) else None

    async def list_meta_album_categories(self, album_id: int) -> list[dict]:
        """List the album's business category tree."""
        resp = await self._get("dma/listCategory", {"albumId": album_id})
        if resp.get("code") not in (200, "200"):
            return []
        return self._album_page_items(resp.get("data"))

    async def list_meta_album_entities(
        self,
        album_id: int,
        *,
        page_size: int = 500,
        entity_type: str | None = "odps-table",
    ) -> list[dict]:
        """List album entities and flatten the nested entity metadata."""
        params: dict[str, object] = {
            "albumId": album_id,
            "pageSize": page_size,
            "pageNum": 1,
        }
        if entity_type:
            params["entityType"] = entity_type
        resp = await self._get("dma/listAlbumEntity", params)
        if resp.get("code") not in (200, "200"):
            return []

        results: list[dict] = []
        for relation in self._album_page_items(resp.get("data")):
            entity = relation.get("entity")
            if not isinstance(entity, dict):
                continue
            results.append(
                {
                    "album_id": relation.get("albumId", album_id),
                    "relation_id": relation.get("relationId"),
                    "category_id": relation.get("categoryId"),
                    "remark": relation.get("remark") or "",
                    "project": entity.get("databaseName") or "",
                    "table_name": entity.get("name") or "",
                    "comment": entity.get("comment") or "",
                    "entity_guid": entity.get("entityGuid") or "",
                    "qualified_name": entity.get("qualifiedName") or "",
                    "entity_type": entity.get("entityType") or "",
                    "owner": entity.get("ownerName") or "",
                }
            )
        return results

    async def get_meta_album_wiki(self, album_id: int) -> str | None:
        """Return album wiki text when maintained; most albums currently have none."""
        resp = await self._get("dma/getWiki", {"type": "album", "entityId": album_id})
        if resp.get("code") not in (200, "200"):
            return None
        data = resp.get("data")
        if isinstance(data, str):
            return data.strip() or None
        if isinstance(data, dict):
            for key in ("content", "wiki", "text"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    # ── 元数据 (DataMap) ─────────────────────────────────────

    async def get_creation_ddl(self, table_guid: str) -> str | None:
        """获取建表 DDL（dma/geneCreationDdl）。"""
        resp = await self._get("dma/geneCreationDdl", {"tableGuid": table_guid})
        if resp.get("code") == 200:
            ddl = resp.get("data")
            return ddl if isinstance(ddl, str) and ddl.strip() else None
        return None

    async def search_tables(self, keyword: str, page_size: int = 50) -> list[dict]:
        """搜索 MC 表（dma/searchTables），支持中文注释匹配。"""
        resp = await self._get(
            "dma/searchTables",
            {
                "keyword": keyword.strip(),
                "entityType": "odps-table",
                "pageNum": "1",
                "pageSize": str(page_size),
            },
        )
        if resp.get("code") != 200:
            return []
        page = resp.get("data") or {}
        items = page.get("data") if isinstance(page, dict) else []
        return [
            {
                "project": t.get("databaseName", ""),
                "table_name": t.get("name", ""),
                "comment": t.get("comment", ""),
                "entity_guid": t.get("entityGuid", ""),
                "owner": t.get("ownerName", ""),
            }
            for t in (items or [])
            if isinstance(t, dict)
        ]

    async def get_upstream_tasks(self, table_guid: str) -> list[dict]:
        """获取上游任务（血缘）。"""
        resp = await self._get(
            "dma/getTableUpstreamTasks",
            {
                "entityGuid": table_guid,
                "entityType": "odps-table",
            },
        )
        return resp.get("data") or [] if resp.get("code") == 200 else []

    async def list_lineage(self, table_guid: str) -> dict | None:
        """获取完整血缘 DAG（dma/listLineage）。"""
        resp = await self._get(
            "dma/listLineage",
            {
                "entityGuid": table_guid,
                "entityType": "odps-table",
                "attributeListCode": 10,
                "brief": "true",
            },
        )
        return resp.get("data") if resp.get("code") == 200 else None

    # ── 数据源 ───────────────────────────────────────────────

    async def list_datasources(self, keyword: str = "") -> list[dict]:
        """获取数据源列表（v1/ListDatasources2），带缓存。"""
        if (
            not keyword
            and self._datasource_cache
            and time.time() - self._datasource_cache_time < 600
        ):
            return self._datasource_cache
        resp = await self._get(
            "v1/ListDatasources2",
            {
                "projectId": self.project_id,
                "tenantId": self.tenant_id,
                "productCode": "di",
                "pageSize": 100,
                "onlyShowDiSupport": "false",
            },
        )
        if resp.get("code") not in (200, "200"):
            self.last_error = str(resp.get("message") or resp.get("msg") or resp.get("code"))
            logger.warning("ListDatasources2 业务失败: %s", self.last_error)
            return []
        sources = (resp.get("data") or {}).get("dataSources") or []
        if not keyword:
            self._datasource_cache = sources
            self._datasource_cache_time = time.time()
        return sources

    async def list_datasource_tables(self, ds_name: str, ds_type: str) -> list[dict]:
        """列出数据源下的表（di/getTableListPost，完整参数参照参考项目）。"""
        params = {"projectId": self.project_id, "tenantId": self.tenant_id}
        body = {
            "projectId": self.project_id,
            "tenantId": self.tenant_id,
            "table": None,
            "envType": 0,
            "datasourceName": ds_name,
            "resourceGroup": self.resource_group,
            "subType": "public",
            "stepType": ds_type,
            "datasourceType": ds_type,
            "pageNum": 1,
            "pageSize": 1000,
        }
        resp = await self._post("di/getTableListPost", body, params=params)

        data = resp.get("data", {}) or {}
        # 兼容多种返回格式
        for key in ("tableNames", "tables", "tableList", "data"):
            val = data.get(key)
            if val and isinstance(val, list):
                return [
                    {"name": t if isinstance(t, str) else t.get("tableName") or t.get("name", "")}
                    for t in val
                ]

        return []


class DataWorksClient(
    _SqlExecMixin,
    _IntegrationMixin,
    _NodeLifecycleMixin,
    _ScheduleMixin,
    _MetadataLineageMixin,
):
    """DataWorks BFF API 全功能客户端。"""

    BASE_URL: str = settings.bff_base_url

    def __init__(self) -> None:
        self.project_id = settings.dataworks_project_id
        self.tenant_id = settings.dataworks_tenant_id
        self.resource_group = settings.dataworks_resource_group
        self.di_resource_group = settings.di_resource_group or settings.dataworks_resource_group
        self._tenant_detected = False

        # Cookie/CSRF 缓存
        self._cookie: str = ""
        self._csrf_token: str = ""
        self._csrf_time: float = 0
        self._csrf_ttl: int = 60  # 1 分钟

        # HTTP 客户端
        self._http: httpx.AsyncClient | None = None

        # 缓存
        self._datasource_cache: list | None = None
        self._datasource_cache_time: float = 0
        self._node_list_cache: list | None = None
        self._node_list_cache_time: float = 0

        self.last_error: str | None = None

    # ── HTTP 基础 ────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=httpx.Timeout(30.0),
                follow_redirects=False,
            )
        return self._http

    def reset_auth_cache(self) -> None:
        """Discard cached Cookie/CSRF so the next request reloads refreshed credentials."""
        self._cookie = ""
        self._csrf_token = ""
        self._csrf_time = 0
        self.last_error = None

    async def _refresh_cookie(self) -> str:
        if not self._cookie:
            self._cookie = decrypt_cookie()
        return self._cookie

    async def _refresh_csrf(self) -> str:
        # 每次都获取新 token（CSRF token 验证严格，不复用）
        try:
            resp = await self._client().get(
                "/csrf",
                params={"version": "v2"},
                headers={"Cookie": await self._refresh_cookie()},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._csrf_token = data.get("data", {}).get("token", "")
                self._csrf_time = time.time()
        except Exception:
            pass
        return self._csrf_token

    async def _base_headers(self) -> dict:
        cookie = await self._refresh_cookie()
        csrf = await self._refresh_csrf()
        h = {"Cookie": cookie, "Content-Type": "application/json"}
        if csrf:
            h["x-csrf-token"] = csrf
        return h

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        async def _do() -> dict:
            resp = await self._client().get(
                f"/{endpoint}",
                params=params or {},
                headers=await self._base_headers(),
            )
            resp.raise_for_status()
            return resp.json()

        return await bff_breaker.call(_do)

    async def _post(
        self, endpoint: str, data: dict | None = None, params: dict | None = None
    ) -> dict:
        async def _do() -> dict:
            resp = await self._client().post(
                f"/{endpoint}",
                json=data or {},
                params=params or {},
                headers=await self._base_headers(),
            )
            resp.raise_for_status()
            return resp.json()

        return await bff_breaker.call(_do)

    async def _put(self, endpoint: str, data: dict | None = None) -> dict:
        async def _do() -> dict:
            resp = await self._client().put(
                f"/{endpoint}",
                json=data or {},
                headers=await self._base_headers(),
            )
            resp.raise_for_status()
            return resp.json()

        return await bff_breaker.call(_do)

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
