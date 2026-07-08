"""OpenAPI_Client — DataWorks OpenAPI 2024-05-18 执行底座（Requirement 3, 5, 28）。

基于 alibabacloud_dataworks_public20240518 + alibabacloud_tea_openapi。
本模块只对接 2024-05-18 版本，不与 2020-05-18 混用。

设计取舍（重要）：design.md 假设的部分方法名（update_node_script /
get_node_script / update_node_schedule / deploy_node / search_meta_tables /
get_column_lineage / create_sync_task / list_dqc_rules 等）在真实 SDK 中
并不存在——脚本/调度内嵌于节点 Spec，发布走 Deployment，元数据走
list_tables/get_table，血缘走 list_lineages，DQC 走 list_data_quality_rules。
因此本客户端方法名一律以真实 SDK 表面为准（见类内各域方法）。

本文件当前覆盖 Task 3.1（骨架 + AK/SK + 指数退避重试 + 错误分类）与
3.2（节点域）。3.3-3.6 其余域在方法映射按真实 SDK 校正后逐域补齐。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from alibabacloud_dataworks_public20240518.client import Client
from alibabacloud_tea_openapi import models as open_api_models
from Tea.exceptions import TeaException

from dataworks_agent.auth import AliyunCredentials

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)

# 可重试的错误码前缀 / 精确码（流控与瞬时服务不可用）
_RETRYABLE_CODE_PREFIXES = ("Throttling", "ServiceUnavailable")
_RETRYABLE_CODES = {"RequestTimeout", "ServiceUnavailableTemporary"}
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class OpenAPIError(RuntimeError):
    """不可重试的 DataWorks OpenAPI 错误 — 携带错误码与信息。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _is_retryable(exc: TeaException) -> bool:
    """判断 TeaException 是否为可重试的流控 / 瞬时错误。"""
    code = getattr(exc, "code", "") or ""
    if code.startswith(_RETRYABLE_CODE_PREFIXES):
        return True
    if code in _RETRYABLE_CODES:
        return True
    data = getattr(exc, "data", None)
    if isinstance(data, dict):
        return data.get("statusCode") in _RETRYABLE_HTTP
    return False


class DataWorksOpenAPIClient:
    """DataWorks OpenAPI 2024-05-18 异步客户端。"""

    def __init__(
        self,
        creds: AliyunCredentials,
        region: str,
        endpoint: str,
        project_id: int,
        *,
        max_retry: int = 5,
        base_delay: float = 0.5,
    ) -> None:
        self._creds = creds
        self._region = region
        self._endpoint = endpoint
        self._project_id = project_id
        self._max_retry = max_retry
        self._base_delay = base_delay
        self._client: Client | None = None

    def _ensure_client(self) -> Client:
        """惰性构造 SDK Client（AK/SK 签名鉴权）。"""
        if self._client is None:
            config = open_api_models.Config(
                access_key_id=self._creds.access_key_id,
                access_key_secret=self._creds.access_key_secret,
                region_id=self._region,
                endpoint=self._endpoint,
            )
            self._client = Client(config)
        return self._client

    async def _invoke(self, method_name: str, request: Any) -> Any:
        """调用 SDK 异步方法，带指数退避重试与错误分类。

        Args:
            method_name: SDK 上的异步方法名（如 "get_node_async"）。
            request: 对应的请求模型实例。

        Returns:
            SDK 响应对象的 body。

        Raises:
            OpenAPIError: 不可重试错误，或重试耗尽后仍失败。
        """
        client = self._ensure_client()
        fn = getattr(client, method_name)

        last_exc: TeaException | None = None
        for attempt in range(self._max_retry):
            try:
                coro: Awaitable[Any] = fn(request)
                resp = await coro
                return getattr(resp, "body", resp)
            except TeaException as e:
                last_exc = e
                if _is_retryable(e) and attempt < self._max_retry - 1:
                    delay = self._base_delay * (2**attempt)
                    logger.warning(
                        "OpenAPI %s 可重试错误 [%s]，第 %d 次退避 %.1fs",
                        method_name,
                        getattr(e, "code", "?"),
                        attempt + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise OpenAPIError(
                    code=getattr(e, "code", "") or "Unknown",
                    message=getattr(e, "message", None) or str(e),
                ) from e
            except (ConnectionError, TimeoutError, OSError) as ce:
                raise OpenAPIError(
                    code="TransportError",
                    message=f"请求传输失败: {ce}",
                ) from ce

        # 理论不可达：循环要么 return 要么 raise
        raise OpenAPIError(
            code=getattr(last_exc, "code", "") or "Unknown",
            message=getattr(last_exc, "message", None) or "重试耗尽",
        )

    # ── 节点域（Task 3.2；真实 SDK 方法名） ──

    async def get_node(self, node_id: str) -> Any:
        """获取节点详情。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.GetNodeRequest(id=node_id, project_id=self._project_id)
        return await self._invoke("get_node_async", req)

    async def list_nodes(
        self,
        *,
        container_id: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
        scene: str | None = None,
    ) -> Any:
        """列出节点（分页）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListNodesRequest(
            project_id=self._project_id,
            container_id=container_id,
            page_number=page_number,
            page_size=page_size,
            scene=scene,
        )
        return await self._invoke("list_nodes_async", req)

    async def create_node(
        self,
        *,
        spec: str,
        container_id: str,
        scene: str | None = None,
    ) -> Any:
        """创建节点。spec 为 FlowSpec JSON（含脚本内容与调度配置）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.CreateNodeRequest(
            project_id=self._project_id,
            spec=spec,
            container_id=container_id,
            scene=scene,
        )
        return await self._invoke("create_node_async", req)

    async def update_node(self, *, node_id: str, spec: str) -> Any:
        """更新节点。spec 内嵌脚本与调度（替代 design 假设的 update_node_script / _schedule）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.UpdateNodeRequest(id=node_id, project_id=self._project_id, spec=spec)
        return await self._invoke("update_node_async", req)

    async def list_node_dependencies(
        self,
        node_id: str,
        *,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出节点依赖（替代 design 假设的 get_node_parents_by_depth 域）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListNodeDependenciesRequest(
            id=node_id,
            project_id=self._project_id,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_node_dependencies_async", req)

    # ── 元数据与血缘域（Task 3.4；真实 SDK 方法名） ──

    async def get_table(self, table_id: str, *, include_business_metadata: bool = False) -> Any:
        """获取元数据表详情（替代 design 假设的 get_meta_table）。

        table_id 为 DataMap 实体 id；用于逆向建模取结构与业务元数据。
        """
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.GetTableRequest(id=table_id, include_business_metadata=include_business_metadata)
        return await self._invoke("get_table_async", req)

    async def list_tables(
        self,
        *,
        name: str | None = None,
        comment: str | None = None,
        parent_meta_entity_id: str | None = None,
        table_types: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """搜索/列出元数据表（替代 design 假设的 search_meta_tables）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListTablesRequest(
            name=name,
            comment=comment,
            parent_meta_entity_id=parent_meta_entity_id,
            table_types=table_types,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_tables_async", req)

    async def list_catalogs(
        self,
        *,
        name: str | None = None,
        comment: str | None = None,
        parent_meta_entity_id: str | None = None,
        types: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出元数据 Catalog（数据目录/引擎层，DataMap 层级下钻起点）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListCatalogsRequest(
            name=name,
            comment=comment,
            parent_meta_entity_id=parent_meta_entity_id,
            types=types,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_catalogs_async", req)

    async def list_databases(
        self,
        *,
        name: str | None = None,
        comment: str | None = None,
        parent_meta_entity_id: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出元数据 Database（parent 为 catalog 实体 id）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListDatabasesRequest(
            name=name,
            comment=comment,
            parent_meta_entity_id=parent_meta_entity_id,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_databases_async", req)

    async def list_schemas(
        self,
        *,
        name: str | None = None,
        comment: str | None = None,
        parent_meta_entity_id: str | None = None,
        types: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出元数据 Schema（parent 为 database 实体 id）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListSchemasRequest(
            name=name,
            comment=comment,
            parent_meta_entity_id=parent_meta_entity_id,
            types=types,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_schemas_async", req)

    async def list_columns(
        self,
        table_id: str,
        *,
        name: str | None = None,
        comment: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出表的列元数据（table_id 为 DataMap 表实体 id）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListColumnsRequest(
            table_id=table_id,
            name=name,
            comment=comment,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_columns_async", req)

    async def list_lineages(
        self,
        *,
        src_entity_id: str | None = None,
        dst_entity_id: str | None = None,
        src_entity_name: str | None = None,
        dst_entity_name: str | None = None,
        need_attach_relationship: bool | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """查询血缘（替代 design 假设的 get_column_lineage）。

        上游：给定 dst_entity_* 查其 src；下游：给定 src_entity_* 查其 dst。
        """
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListLineagesRequest(
            src_entity_id=src_entity_id,
            dst_entity_id=dst_entity_id,
            src_entity_name=src_entity_name,
            dst_entity_name=dst_entity_name,
            need_attach_relationship=need_attach_relationship,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_lineages_async", req)

    # ── 发布域（Task 3.3；Deployment 系）──
    # 注意：发布是生产写操作，调用方须先经 Publish_Gate 人工授权（Requirement 14）。

    async def create_deployment(
        self,
        *,
        object_ids: list[str],
        deploy_type: str = "Online",
        description: str = "",
    ) -> Any:
        """创建发布单（替代 design 假设的 deploy_node）。

        object_ids 为待发布的节点 id 列表；deploy_type 发布类型（Online/Offline，
        真实取值以 OpenAPI 调试器为准）。**发布前须经人工授权。**
        """
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.CreateDeploymentRequest(
            project_id=self._project_id,
            object_ids=object_ids,
            type=deploy_type,
            description=description,
        )
        return await self._invoke("create_deployment_async", req)

    async def get_deployment(self, deployment_id: str) -> Any:
        """查询发布单状态。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.GetDeploymentRequest(id=deployment_id, project_id=self._project_id)
        return await self._invoke("get_deployment_async", req)

    async def exec_deployment_stage(self, *, deployment_id: str, code: str) -> Any:
        """驱动发布单进入下一阶段（如触发实际发布）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ExecDeploymentStageRequest(id=deployment_id, code=code, project_id=self._project_id)
        return await self._invoke("exec_deployment_stage_async", req)

    # ── 数据源域（Task 3.5；真实 SDK 方法名） ──
    # 注意：DI 同步在 2024-05-18 为 task/node 类型（无 create_sync_task），
    # 建/改 DI 同步节点复用节点域 create_node/update_node（script 语言为 DI），此处仅覆盖数据源读。

    async def list_data_sources(
        self,
        *,
        name: str | None = None,
        types: str | None = None,
        env_type: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出数据源（替代 bff.list_datasources）。

        types 为数据源类型过滤（如 "odps,mysql"）；env_type 环境（Prod/Dev）。
        """
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListDataSourcesRequest(
            project_id=self._project_id,
            name=name,
            types=types,
            env_type=env_type,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_data_sources_async", req)

    async def get_data_source(self, data_source_id: str) -> Any:
        """获取单个数据源详情。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.GetDataSourceRequest(id=data_source_id)
        return await self._invoke("get_data_source_async", req)

    # ── 数据集成 DI 域（Task 3.5；DIJob 系；真实 SDK 方法名） ──
    # 修正早期"DI 复用 create_node"的误判：2024-05-18 有完整 DIJob 域。
    # bff 的手动跑 DI（create_di_executor_job + write_executor_config）对应 start_dijob(force_to_rerun)。

    async def create_dijob(
        self,
        *,
        job_name: str,
        source_data_source_type: str,
        destination_data_source_type: str,
        migration_type: str,
        table_mappings: list[dict[str, Any]] | None = None,
        transformation_rules: list[dict[str, Any]] | None = None,
        source_data_source_settings: list[dict[str, Any]] | None = None,
        destination_data_source_settings: list[dict[str, Any]] | None = None,
        resource_settings: dict[str, Any] | None = None,
        job_settings: dict[str, Any] | None = None,
        job_type: str | None = None,
        description: str = "",
    ) -> Any:
        """创建数据集成同步作业（替代 bff.create_di_node 的 filespec 建法）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.CreateDIJobRequest(
            project_id=self._project_id,
            job_name=job_name,
            source_data_source_type=source_data_source_type,
            destination_data_source_type=destination_data_source_type,
            migration_type=migration_type,
            table_mappings=table_mappings,
            transformation_rules=transformation_rules,
            source_data_source_settings=source_data_source_settings,
            destination_data_source_settings=destination_data_source_settings,
            resource_settings=resource_settings,
            job_settings=job_settings,
            job_type=job_type,
            description=description,
        )
        return await self._invoke("create_dijob_async", req)

    async def get_dijob(self, dijob_id: str, *, with_details: bool = False) -> Any:
        """获取 DI 作业详情。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.GetDIJobRequest(
            dijob_id=dijob_id, project_id=self._project_id, with_details=with_details
        )
        return await self._invoke("get_dijob_async", req)

    async def list_dijobs(
        self,
        *,
        name: str | None = None,
        source_data_source_type: str | None = None,
        destination_data_source_type: str | None = None,
        migration_type: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出 DI 作业。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListDIJobsRequest(
            project_id=self._project_id,
            name=name,
            source_data_source_type=source_data_source_type,
            destination_data_source_type=destination_data_source_type,
            migration_type=migration_type,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_dijobs_async", req)

    async def start_dijob(
        self,
        dijob_id: str,
        *,
        force_to_rerun: bool = False,
        realtime_start_settings: dict[str, Any] | None = None,
    ) -> Any:
        """启动 DI 作业（force_to_rerun=手动重跑，替代 bff 手动跑 DI）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.StartDIJobRequest(
            dijob_id=dijob_id,
            force_to_rerun=force_to_rerun,
            realtime_start_settings=realtime_start_settings,
        )
        return await self._invoke("start_dijob_async", req)

    async def stop_dijob(self, dijob_id: str, *, instance_id: str | None = None) -> Any:
        """停止 DI 作业。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.StopDIJobRequest(dijob_id=dijob_id, instance_id=instance_id)
        return await self._invoke("stop_dijob_async", req)

    # ── 数据质量域（Task 3.6；真实 SDK 方法名） ──
    # DQC 消费只读：评估任务 → 规则 → 结果。规则/任务的创建为生产写，须经 Publish_Gate。

    async def list_data_quality_evaluation_tasks(
        self,
        *,
        name: str | None = None,
        table_guid: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出数据质量评估任务（规则/结果的父实体入口）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListDataQualityEvaluationTasksRequest(
            project_id=self._project_id,
            name=name,
            table_guid=table_guid,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_data_quality_evaluation_tasks_async", req)

    async def list_data_quality_rules(
        self,
        *,
        data_quality_evaluation_task_id: str | None = None,
        table_guid: str | None = None,
        name: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出数据质量规则（替代 design 假设的 list_dqc_rules）。"""
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListDataQualityRulesRequest(
            project_id=self._project_id,
            data_quality_evaluation_task_id=data_quality_evaluation_task_id,
            table_guid=table_guid,
            name=name,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_data_quality_rules_async", req)

    async def list_data_quality_results(
        self,
        *,
        data_quality_evaluation_task_id: str | None = None,
        data_quality_evaluation_task_instance_id: str | None = None,
        data_quality_rule_id: str | None = None,
        bizdate_from: str | None = None,
        bizdate_to: str | None = None,
        page_number: int = 1,
        page_size: int = 100,
    ) -> Any:
        """列出数据质量校验结果（替代 design 假设的 get_dqc_result）。

        转 Quality_Signal 进语义层（Task 26 消费）；只读元数据/校验结论，不读数据行。
        """
        from alibabacloud_dataworks_public20240518 import models as m

        req = m.ListDataQualityResultsRequest(
            project_id=self._project_id,
            data_quality_evaluation_task_id=data_quality_evaluation_task_id,
            data_quality_evaluation_task_instance_id=data_quality_evaluation_task_instance_id,
            data_quality_rule_id=data_quality_rule_id,
            bizdate_from=bizdate_from,
            bizdate_to=bizdate_to,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._invoke("list_data_quality_results_async", req)
