"""Deterministic, no-write metadata provider for Agent runtime acceptance."""

from __future__ import annotations

from typing import Any

from dataworks_agent.agent.context.metadata_provider import MetadataQueryResult
from dataworks_agent.api_clients.provider_errors import ProviderAuthenticationError


class DeterministicNoWriteProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_search = False
        self.failure_mode = ""

    async def search_table(self, keyword: str, message: str) -> MetadataQueryResult:
        self.calls.append(
            {
                "tool": "find_table",
                "arguments": {"keyword": keyword, "message": message},
                "side_effect": "read",
            }
        )
        if self.failure_mode == "auth":
            raise ProviderAuthenticationError(
                "cookie_auth_required",
                "USER_NOT_LOGGED_IN",
                provider="cookie_bff",
            )
        if self.failure_mode == "unavailable" or self.fail_search:
            raise RuntimeError("deterministic metadata dependency unavailable")
        if self.failure_mode == "no_match":
            return MetadataQueryResult(keyword=keyword, candidates=[])
        domain = "refund" if "退款" in keyword else "orders"
        if "宽" in keyword:
            candidates = [
                {
                    "full_name": f"dw.{layer}_{domain}_{index}",
                    "layer": layer,
                    "comment": f"{layer.upper()} {domain} {index}",
                }
                for index, layer in enumerate(["dwd"] * 5 + ["ods"] * 5)
            ]
        else:
            candidates = [
                {
                    "full_name": f"dw.dwd_{domain}_detail",
                    "layer": "dwd",
                    "comment": "明细表",
                },
                {
                    "full_name": f"dw.dws_{domain}_summary",
                    "layer": "dws",
                    "comment": "汇总表",
                },
            ]
        return MetadataQueryResult(keyword=keyword, candidates=candidates)

    async def get_columns(self, table_name: str) -> list[dict[str, str]]:
        self.calls.append(
            {
                "tool": "inspect_table",
                "arguments": {"table_name": table_name},
                "side_effect": "read",
            }
        )
        return [
            {"name": "order_id", "type": "STRING", "comment": "订单 ID"},
            {"name": "pay_amount", "type": "DECIMAL(18,2)", "comment": "支付金额"},
        ]

    def assert_no_writes(self) -> None:
        assert self.calls
        assert all(call["side_effect"] == "read" for call in self.calls)
