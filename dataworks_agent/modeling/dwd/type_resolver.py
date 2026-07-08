"""Deterministic DWD target-field type resolver (LLM-free default)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

AMOUNT_KEYWORDS = {"amount", "amt", "cost", "fee", "price", "money", "金额", "成本", "费用", "价格"}
QUANTITY_KEYWORDS = {"qty", "quantity", "count", "num", "cnt", "数量", "次数", "个数"}


@lru_cache(maxsize=1)
def _load_dwd_suffix_types() -> dict[str, str]:
    from dataworks_agent.governance.warehouse_config import load_field_suffix_rules

    suffix_map: dict[str, str] = {}
    for rule in load_field_suffix_rules():
        suffix = str(rule.get("suffix", "")).strip().lower()
        if not suffix:
            continue
        mc_type = rule.get("dwd_type") or rule.get("type")
        if mc_type:
            suffix_map[suffix] = str(mc_type).lower()
    return suffix_map


@dataclass(frozen=True)
class TypeIssue:
    severity: str
    element: str
    description: str


@dataclass(frozen=True)
class ResolvedDwdType:
    type: str
    category: str
    issues: list[TypeIssue] = field(default_factory=list)


class DwdTypeResolver:
    """Resolve MaxCompute column type from field name and comment."""

    def resolve(self, field_name: str, comment: str | None = None) -> ResolvedDwdType:
        normalized = field_name.strip().lower()
        suffix = normalized.rsplit("_", 1)[-1]
        suffix_types = _load_dwd_suffix_types()
        if suffix in suffix_types:
            return ResolvedDwdType(type=suffix_types[suffix], category="normal")

        haystack = f"{normalized} {comment or ''}".lower()
        if any(keyword in haystack for keyword in AMOUNT_KEYWORDS):
            return ResolvedDwdType(type="decimal(24,6)", category="amount")
        if any(keyword in haystack for keyword in QUANTITY_KEYWORDS):
            return ResolvedDwdType(type="bigint", category="quantity")

        if any(word in haystack for word in ("total", "sum", "number", "numeric", "数", "量")):
            return ResolvedDwdType(
                type="string",
                category="normal",
                issues=[
                    TypeIssue(
                        severity="warning",
                        element=field_name,
                        description="Numeric semantics ambiguous; defaulted to string.",
                    )
                ],
            )

        return ResolvedDwdType(type="string", category="normal")
