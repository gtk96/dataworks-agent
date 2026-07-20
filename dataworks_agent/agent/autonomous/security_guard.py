"""安全守卫 — 防止越权发布、新建目录、非法数据源等操作。"""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.agent.autonomous.state import AutonomousContext, TaskType
from dataworks_agent.api_clients.destructive_guard import (
    DestructiveOpBlockedError,
    guard_node_op,
)

logger = logging.getLogger(__name__)

# 广告报告业务文件夹白名单前缀
_ALLOWED_FOLDER_PREFIXES = (
    "业务流程/106_广告报告/",
    "业务流程\\106_广告报告\\",
)

# 破坏性操作映射：发布/下线/删除节点
_DESTRUCTIVE_OPS = {
    "deploy",
    "publish",
    "offline",
    "delete_node",
    "undeploy",
}


class AutonomousSecurityGuard:
    """自主 Agent 的安全边界守卫。

    硬规则：
    - 禁止发布操作（deploy/publish/offline/delete）
    - 禁止新建业务流程目录
    - 业务文件夹必须在允许的白名单内（广告报告目录）
    - 数据源类型必须在上下文中声明的允许列表内
    """

    def __init__(self, context: AutonomousContext, destructive_guard: Any = None) -> None:
        self._context = context
        self._destructive_guard = destructive_guard

    async def validate_request(self, task_type: TaskType, params: dict[str, Any]) -> bool:
        """校验请求是否通过安全守卫。

        Raises:
            SecurityViolationError: 违反安全规则时抛出。

        Returns:
            True 表示通过校验。
        """
        self._check_no_publish_intent(task_type, params)
        self._check_business_folder(params)
        self._check_data_source(params)
        self._check_destructive_ops(params)
        logger.info(
            "安全守卫通过: task_type=%s, folder=%s",
            task_type,
            self._context.business_folder,
        )
        return True

    def _check_no_publish_intent(self, task_type: TaskType, params: dict[str, Any]) -> None:
        """禁止发布意图。"""
        intent_text = f"{task_type.value} {' '.join(str(v) for v in params.values())}".lower()
        publish_signals = ("deploy", "publish", "发布", "上线", "offline", "下线", "delete", "删除")
        if any(sig in intent_text for sig in publish_signals):
            raise SecurityViolationError(
                "自主 Agent 禁止执行发布/下线/删除操作，必须经 Publish Gate 人工审批。"
            )

    def _check_business_folder(self, params: dict[str, Any]) -> None:
        """验证业务文件夹在允许范围内。"""
        folder = str(params.get("business_folder") or params.get("node_path") or "")
        if not folder:
            return  # 未显式指定时不阻断

        for prefix in _ALLOWED_FOLDER_PREFIXES:
            if folder.startswith(prefix):
                return

        raise SecurityViolationError(
            f"业务文件夹不在允许范围内: '{folder}'。"
            f"测试环境限定在广告报告目录: {', '.join(_ALLOWED_FOLDER_PREFIXES)}"
        )

    def _check_data_source(self, params: dict[str, Any]) -> None:
        """验证数据源类型是否在允许列表中。"""
        allowed = self._context.allowed_data_sources
        if not allowed:
            return  # 未限制时放行

        ds_type = str(params.get("datasource_type") or params.get("source_type") or "").lower()
        if not ds_type:
            return

        normalized_allowed = {str(t).lower() for t in allowed}
        if ds_type not in normalized_allowed:
            raise SecurityViolationError(f"数据源类型 '{ds_type}' 不在允许列表中: {allowed}")

    def _check_destructive_ops(self, params: dict[str, Any]) -> None:
        """检查破坏性操作（通过 DestructiveOpGuard 的 guard_node_op）。"""
        op = str(params.get("operation") or params.get("op") or "").strip().upper()
        if not op:
            return

        if op in _DESTRUCTIVE_OPS or op in {"DELETE_NODE", "OFFLINE_NODE", "UNDEPLOY"}:
            try:
                guard_node_op(op)
            except DestructiveOpBlockedError as exc:
                raise SecurityViolationError(str(exc)) from exc


class SecurityViolationError(RuntimeError):
    """安全守卫拦截违规请求时抛出的异常。"""
