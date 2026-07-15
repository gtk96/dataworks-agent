"""OpenAPINodeAdapter（Task 8b）— 用 AK/SK OpenAPI + FlowSpec 复刻 bff_client 的
节点 5 方法接口，作为 `self.bff` 的 drop-in 替换，供 modeling / services / routers 无改动切换。

复刻的方法（签名与 bff_client 对齐）：
  create_node(name, path, language) -> uuid|None
  update_node(uuid, content) -> bool
  update_vertex(uuid, config, instance_mode) -> bool
  deploy_nodes(uuids, comment) -> bool          # 生产写，调用方须先过 Publish_Gate
  get_node_uuid_by_path(node_dir) -> uuid|None

实现模式：create 用 build_node_flowspec 一次成型；update/vertex 用 get-modify-write
（get_node 取 Spec → 改 → update_node）。错误经 last_error 暴露（与 bff 兼容），
不抛异常。**只建/改草稿；发布 create_deployment 是生产写。**
"""

from __future__ import annotations

import json
import logging
from typing import Any

from dataworks_agent.api_clients.flowspec import build_node_flowspec
from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient, OpenAPIError
from dataworks_agent.services.ods_oss.directory_guard import (
    ExistingDirectoryEvidence,
    infer_existing_directory,
    normalize_node_path,
    parent_node_path,
)

logger = logging.getLogger(__name__)


def _to_map(body: Any) -> dict:
    """SDK 响应 body（TeaModel）→ dict；已是 dict 则原样返回。"""
    if hasattr(body, "to_map"):
        return body.to_map()
    return body if isinstance(body, dict) else {}


def _map_parameters(parameters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """把 DAILY/HOURLY_SQL_PARAMETERS 形态映射为 FlowSpec 的 Variable 参数。"""
    return [
        {
            "artifactType": "Variable",
            "name": p["name"],
            "scope": p.get("scope", "NodeParameter"),
            "type": p.get("type", "System"),
            "value": p["value"],
        }
        for p in parameters or []
    ]


class OpenAPINodeAdapter:
    """AK/SK 版节点操作，接口对齐 bff_client 的节点 5 方法。"""

    def __init__(
        self,
        api: DataWorksOpenAPIClient,
        *,
        project: str = "dataworks",
        scene: str = "DATAWORKS_PROJECT",
        default_cron: str = "00 00 06 * * ?",
        holo_datasource: str = "dataworks_holo",
        max_scan_pages: int = 50,
    ) -> None:
        self._api = api
        self._project = project
        self._scene = scene
        self._default_cron = default_cron
        self._holo_datasource = holo_datasource
        self._max_scan_pages = max_scan_pages
        self.last_error: str | None = None

    # ── 建节点 ───────────────────────────────────────────────

    async def create_node(self, name: str, path: str, language: str = "odps-sql") -> str | None:
        """Create or reuse a node under an already existing DataWorks directory."""
        normalized_path = normalize_node_path(path)
        try:
            existing_uuid = await self.get_node_uuid_by_path(normalized_path)
            if existing_uuid:
                return existing_uuid
        except Exception as exc:
            self.last_error = f"existing node lookup failed: {exc}"
            return None

        parent_path = parent_node_path(normalized_path)
        evidence = await self.check_existing_directory(parent_path)
        if not evidence.confirmed:
            self.last_error = (
                f"parent directory not confirmed: {parent_path}; "
                "OpenAPI directory evidence is required; node creation skipped"
            )
            return None

        # Hologres uses a different datasource; MaxCompute and DI use project/default settings.
        datasource_name = self._holo_datasource if language == "holo" else self._project
        try:
            spec = build_node_flowspec(
                name=name,
                script_content=f"-- {name}\n",
                script_path=normalized_path,
                output_ref=f"{self._project}.{name}",
                language=language,
                datasource_name=datasource_name,
                cron=self._default_cron,
                cycle_type="Daily",
                self_dependency=False,
                auto_parse=False,
            )
        except ValueError as e:
            self.last_error = str(e)
            return None
        try:
            body = await self._api.create_node(spec=spec, container_id=None, scene=self._scene)
        except OpenAPIError as e:
            self.last_error = f"{e.code}: {e.message}"
            return None
        node_id = _to_map(body).get("Id")
        if not node_id:
            self.last_error = "create_node did not return Id"
            return None
        return str(node_id)

    # ── 读取 Spec（get-modify-write 基础）─────────────────────

    async def _load_spec(self, uuid: str) -> dict | None:
        try:
            body = await self._api.get_node(str(uuid))
        except OpenAPIError as e:
            self.last_error = f"{e.code}: {e.message}"
            return None
        node = _to_map(body).get("Node") or {}
        raw = node.get("Spec")
        if not raw:
            self.last_error = f"节点 {uuid} 无 Spec"
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            self.last_error = f"Spec 解析失败: {e}"
            return None

    async def _save_spec(self, uuid: str, spec: dict) -> bool:
        try:
            await self._api.update_node(
                node_id=str(uuid), spec=json.dumps(spec, ensure_ascii=False)
            )
            return True
        except OpenAPIError as e:
            self.last_error = f"{e.code}: {e.message}"
            return False

    @staticmethod
    def _first_node(spec: dict) -> dict | None:
        nodes = (spec.get("spec") or {}).get("nodes") or []
        return nodes[0] if nodes else None

    @staticmethod
    def _default_output_ref(node: dict) -> str | None:
        for o in (node.get("outputs") or {}).get("nodeOutputs") or []:
            if o.get("isDefault") and isinstance(o.get("data"), str) and "." in o["data"]:
                return o["data"]
        for o in (node.get("outputs") or {}).get("nodeOutputs") or []:
            if isinstance(o.get("data"), str) and "." in o["data"]:
                return o["data"]
        return None

    # ── 写脚本正文 ───────────────────────────────────────────

    async def update_node(self, uuid: str, content: str) -> bool:
        spec = await self._load_spec(uuid)
        if spec is None:
            return False
        node = self._first_node(spec)
        if node is None:
            self.last_error = f"节点 {uuid} Spec 无 nodes"
            return False
        node.setdefault("script", {})["content"] = content
        return await self._save_spec(uuid, spec)

    # ── 写调度（trigger / 参数 / 依赖 / instanceMode）─────────

    async def update_vertex(
        self, uuid: str, config: dict | None = None, instance_mode: str = "Immediately"
    ) -> bool:
        config = config or {}
        spec = await self._load_spec(uuid)
        if spec is None:
            return False
        node = self._first_node(spec)
        if node is None:
            self.last_error = f"节点 {uuid} Spec 无 nodes"
            return False

        node["instanceMode"] = instance_mode

        trigger = config.get("trigger")
        if isinstance(trigger, dict):
            node.setdefault("trigger", {}).update(trigger)

        script_cfg = config.get("script")
        if isinstance(script_cfg, dict) and "parameters" in script_cfg:
            node.setdefault("script", {})["parameters"] = _map_parameters(script_cfg["parameters"])

        strategy = config.get("strategy")
        if isinstance(strategy, dict):
            for k in ("rerunMode", "rerunTimes", "rerunInterval", "timeout"):
                if k in strategy:
                    node[k] = strategy[k]

        outputs = config.get("outputs")
        if isinstance(outputs, dict):
            node["outputs"] = outputs

        deps = config.get("dependencies")
        if deps is not None:
            output_ref = (
                self._default_output_ref(node) or f"{self._project}.{node.get('name', uuid)}"
            )
            depends: list[dict[str, Any]] = []
            for d in deps:
                dtype = d.get("type", "Normal")
                if dtype == "CrossCycleDependsOnSelf":
                    depends.append(
                        {"type": dtype, "output": output_ref, "refTableName": output_ref}
                    )
                else:
                    ref = d.get("output") or d.get("refTableName")
                    if ref:
                        depends.append(
                            {
                                "type": "Normal",
                                "sourceType": "Manual",
                                "output": ref,
                                "refTableName": ref,
                            }
                        )
            spec["spec"]["flow"] = [{"nodeId": node.get("id") or str(uuid), "depends": depends}]

        return await self._save_spec(uuid, spec)

    # ── 发布（生产写，须先过 Publish_Gate）────────────────────

    async def deploy_nodes(self, node_uuids: list[str], comment: str = "") -> bool:
        try:
            body = await self._api.create_deployment(
                object_ids=[str(u) for u in node_uuids],
                description=comment or "dw-agent deploy",
            )
        except OpenAPIError as e:
            self.last_error = f"{e.code}: {e.message}"
            return False
        return _to_map(body).get("Id") is not None

    # ── 按路径反查节点 uuid（list_nodes 扫描匹配 Script.Path）──

    async def check_existing_directory(self, directory_path: str) -> ExistingDirectoryEvidence:
        """Confirm a parent directory from read-only ListNodes evidence."""
        target = normalize_node_path(directory_path)
        if not target:
            return ExistingDirectoryEvidence.from_check(target, "invalid_path", False)
        records: list[dict[str, Any]] = []
        for page in range(1, self._max_scan_pages + 1):
            try:
                body = await self._api.list_nodes(
                    page_number=page, page_size=100, scene=self._scene
                )
            except OpenAPIError as e:
                self.last_error = f"{e.code}: {e.message}"
                return ExistingDirectoryEvidence.from_check(target, "list_nodes_error", False)
            paging = _to_map(body).get("PagingInfo") or {}
            nodes = paging.get("Nodes") or []
            records.extend(n for n in nodes if isinstance(n, dict))
            if not nodes or page * 100 >= (paging.get("TotalCount") or 0):
                break
        if infer_existing_directory(records, target):
            return ExistingDirectoryEvidence.from_check(target, "node_path", True)
        return ExistingDirectoryEvidence.from_check(target, "no_positive_evidence", False)

    async def get_node_uuid_by_path(self, node_dir: str) -> str | None:
        target = node_dir.rstrip("/")
        for page in range(1, self._max_scan_pages + 1):
            try:
                body = await self._api.list_nodes(
                    page_number=page, page_size=100, scene=self._scene
                )
            except OpenAPIError as e:
                self.last_error = f"{e.code}: {e.message}"
                return None
            paging = _to_map(body).get("PagingInfo") or {}
            nodes = paging.get("Nodes") or []
            if not nodes:
                break
            for n in nodes:
                path = (n.get("Script") or {}).get("Path")
                if path and path.rstrip("/") == target:
                    return str(n.get("Id"))
            total = paging.get("TotalCount") or 0
            if page * 100 >= total:
                break
        return None
