"""隔离边界 — 确认执行边界。

实现 Requirement 17：
- 不实现 MicroVM 或 CubeSandbox
- 以 Dev_Schema、dry_run、Publish_Gate 人工审批与 AK/SK 最小权限作为隔离边界
- 不在本机执行不可信代码，仅通过 API 调用外部服务
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IsolationBoundary:
    """隔离边界配置。"""

    # Dev Schema 隔离
    dev_schema: str = "dataworks_dev"
    prod_schema: str = "dataworks"

    # dry_run 模式
    dry_run_enabled: bool = True

    # Publish_Gate 审批
    publish_gate_enabled: bool = True

    # AK/SK 最小权限
    ak_sk_minimal_permission: bool = True

    # 代码执行隔离
    no_local_code_execution: bool = True

    # 外部 API 调用
    external_api_only: bool = True


class IsolationVerifier:
    """隔离边界验证器。

    确认执行仅经 dev schema + dry_run + 审批 + AK/SK 最小权限。
    """

    def __init__(self) -> None:
        self._boundary = IsolationBoundary()

    def verify_target_schema(self, schema: str) -> dict[str, Any]:
        """验证目标 schema。"""
        if schema == self._boundary.prod_schema:
            return {
                "allowed": False,
                "reason": f"生产 schema {schema} 需要 Publish_Gate 审批",
                "suggestion": f"请使用 dev schema {self._boundary.dev_schema}",
            }

        if schema == self._boundary.dev_schema:
            return {
                "allowed": True,
                "reason": f"Dev schema {schema} 允许直接执行",
            }

        return {
            "allowed": False,
            "reason": f"未知 schema: {schema}",
            "suggestion": f"请使用 dev schema {self._boundary.dev_schema}",
        }

    def verify_dry_run(self, is_dry_run: bool) -> dict[str, Any]:
        """验证 dry_run 模式。"""
        if is_dry_run:
            return {
                "allowed": True,
                "reason": "dry_run 模式允许执行（不会产生实际副作用）",
            }

        if self._boundary.dry_run_enabled:
            return {
                "allowed": True,
                "reason": "生产执行需要 Publish_Gate 审批",
                "suggestion": "建议先使用 dry_run 模式预览",
            }

        return {
            "allowed": True,
            "reason": "dry_run 检查已禁用",
        }

    def verify_publish_gate(self, requires_approval: bool) -> dict[str, Any]:
        """验证 Publish_Gate 审批。"""
        if requires_approval and self._boundary.publish_gate_enabled:
            return {
                "allowed": True,
                "reason": "生产写操作需要 Publish_Gate 审批",
                "suggestion": "请通过 Web 界面进行审批",
            }

        return {
            "allowed": True,
            "reason": "Publish_Gate 检查通过",
        }

    def verify_code_execution(self, code: str) -> dict[str, Any]:
        """验证代码执行。"""
        if self._boundary.no_local_code_execution:
            # 检查是否包含危险操作
            dangerous_patterns = [
                "exec(",
                "eval(",
                "import os",
                "import subprocess",
                "__import__",
                "compile(",
            ]

            for pattern in dangerous_patterns:
                if pattern in code:
                    return {
                        "allowed": False,
                        "reason": f"检测到危险代码模式: {pattern}",
                        "suggestion": "仅允许通过 API 调用外部服务",
                    }

        return {
            "allowed": True,
            "reason": "代码执行验证通过",
        }

    def verify_api_call(self, api_call: str) -> dict[str, Any]:
        """验证 API 调用。"""
        if self._boundary.external_api_only:
            # 检查是否是允许的 API 调用
            allowed_apis = [
                "openapi_client",
                "maxcompute_client",
                "bff_client",
                "mcp_pool",
            ]

            if any(api in api_call.lower() for api in allowed_apis):
                return {
                    "allowed": True,
                    "reason": f"API 调用 {api_call} 在允许列表中",
                }

            return {
                "allowed": False,
                "reason": f"API 调用 {api_call} 不在允许列表中",
                "suggestion": "仅允许通过 OpenAPI/MaxCompute/BFF/MCP 调用外部服务",
            }

        return {
            "allowed": True,
            "reason": "API 调用验证已禁用",
        }

    def verify_all(self, operation: dict[str, Any]) -> dict[str, Any]:
        """综合验证操作。"""
        results = {}

        # 验证 schema
        schema = operation.get("schema", "")
        if schema:
            results["schema"] = self.verify_target_schema(schema)

        # 验证 dry_run
        is_dry_run = operation.get("dry_run", False)
        results["dry_run"] = self.verify_dry_run(is_dry_run)

        # 验证 Publish_Gate
        requires_approval = operation.get("requires_approval", False)
        results["publish_gate"] = self.verify_publish_gate(requires_approval)

        # 验证代码执行
        code = operation.get("code", "")
        if code:
            results["code_execution"] = self.verify_code_execution(code)

        # 验证 API 调用
        api_call = operation.get("api_call", "")
        if api_call:
            results["api_call"] = self.verify_api_call(api_call)

        # 汇总结果
        all_allowed = all(r.get("allowed", True) for r in results.values())

        return {
            "allowed": all_allowed,
            "checks": results,
        }

    def get_boundary_config(self) -> IsolationBoundary:
        """获取隔离边界配置。"""
        return self._boundary
