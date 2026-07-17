"""词根校验服务 — 校验 DWD/DIM/DWS 表的列名是否符合数据仓库词根规范。

校验规则：
1. 列名必须在 dim_pub_column_dictionary_static（词根表）中存在
2. 或使用标准词根组合（如 user_id = user + id）
3. 或使用通用后缀（如 dt, hr, pt）
4. 或使用数字后缀（如 col_1, col_2）

校验报告格式：
{
    "table": "dwd_order_detail",
    "total_columns": 15,
    "passed": 12,
    "warnings": 2,
    "failures": 1,
    "details": [...]
}
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from dataworks_agent.config import settings
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import WordRootCacheModel
from dataworks_agent.standards.loader import load_word_root_entries

logger = logging.getLogger(__name__)

# 通用后缀（允许不使用词根表）
COMMON_SUFFIXES = {"dt", "hr", "pt", "id", "type", "status", "flag", "count", "num", "rate", "ratio"}

# 数字列模式
NUMERIC_COL_PATTERN = re.compile(r"^col_\d+$")


@dataclass
class ColumnValidationResult:
    """单个列的校验结果。"""

    column_name: str
    status: str  # "passed" | "warning" | "failure"
    root: str | None = None
    suggestion: str = ""
    reason: str = ""


@dataclass
class ColumnValidationReport:
    """列名校验报告。"""

    table_name: str
    total_columns: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    details: list[ColumnValidationResult] = field(default_factory=list)

    def summary(self) -> str:
        """生成人类可读的摘要。"""
        lines = [
            f"词根校验报告: {self.table_name}",
            f"总计 {self.total_columns} 列: ✅ {self.passed} 通过, ⚠️ {self.warnings} 警告, ❌ {self.failures} 失败",
        ]
        if self.details:
            lines.append("")
            for d in self.details:
                icon = {"passed": "✅", "warning": "⚠️", "failure": "❌"}.get(d.status, "❓")
                line = f"  {icon} {d.column_name}"
                if d.root:
                    line += f" (词根: {d.root})"
                if d.suggestion:
                    line += f" → 建议: {d.suggestion}"
                lines.append(line)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "table_name": self.table_name,
            "total_columns": self.total_columns,
            "passed": self.passed,
            "warnings": self.warnings,
            "failures": self.failures,
            "details": [
                {
                    "column_name": d.column_name,
                    "status": d.status,
                    "root": d.root,
                    "suggestion": d.suggestion,
                    "reason": d.reason,
                }
                for d in self.details
            ],
        }


class WordRootValidator:
    """
    校验 DWD/DIM/DWS 表的列名是否符合词根规范。
    """

    def __init__(self) -> None:
        self._load_func = load_word_root_entries

    def validate_columns(
        self,
        table_name: str,
        columns: list[str] | list[dict[str, Any]],
    ) -> ColumnValidationReport:
        """
        校验列名。

        Args:
            table_name: 表名（用于报告）
            columns: 列名列表，或包含 name/type 的字典列表

        Returns:
            校验报告
        """
        # 规范化列名列表
        col_names: list[str] = []
        for c in columns:
            if isinstance(c, str):
                col_names.append(c.lower().strip())
            elif isinstance(c, dict):
                col_names.append(c.get("name", c.get("column_name", "")).lower().strip())

        report = ColumnValidationReport(table_name=table_name, total_columns=len(col_names))

        # 加载词根缓存
        roots = self._load_word_roots()

        for col_name in col_names:
            result = self._validate_single_column(col_name, roots)
            report.details.append(result)
            if result.status == "passed":
                report.passed += 1
            elif result.status == "warning":
                report.warnings += 1
            else:
                report.failures += 1

        return report

    def _validate_single_column(
        self,
        column_name: str,
        roots: dict[str, str],
    ) -> ColumnValidationResult:
        """
        校验单个列名。

        规则：
        1. 完全匹配词根表 → passed
        2. 词根组合（如 user_id = user + id）→ passed
        3. 通用后缀（dt/hr/id 等）→ passed
        4. 数字列（col_1）→ passed
        5. 部分匹配 → warning
        6. 完全不匹配 → failure
        """
        # 规则 1: 完全匹配
        if column_name in roots:
            return ColumnValidationResult(
                column_name=column_name,
                status="passed",
                root=column_name,
                reason="词根表直接匹配",
            )

        # 规则 2: 词根组合（以下划线分割，逐段匹配）
        parts = column_name.split("_")
        if len(parts) > 1:
            matched_parts = [p for p in parts if p in roots]
            if matched_parts:
                # 至少有一个部分匹配词根
                unmatched = [p for p in parts if p not in roots]
                if not unmatched:
                    return ColumnValidationResult(
                        column_name=column_name,
                        status="passed",
                        root="+".join(matched_parts),
                        reason=f"词根组合: {' + '.join(matched_parts)}",
                    )
                else:
                    suggestion = self._suggest_fix(column_name, roots)
                    return ColumnValidationResult(
                        column_name=column_name,
                        status="warning",
                        root="+".join(matched_parts),
                        suggestion=suggestion,
                        reason=f"部分匹配: {' + '.join(matched_parts)}",
                    )

        # 规则 3: 通用后缀
        if column_name in COMMON_SUFFIXES:
            return ColumnValidationResult(
                column_name=column_name,
                status="passed",
                root=column_name,
                reason="通用后缀",
            )

        # 规则 4: 数字列模式
        if NUMERIC_COL_PATTERN.match(column_name):
            return ColumnValidationResult(
                column_name=column_name,
                status="passed",
                root=column_name,
                reason="数字列模式",
            )

        # 规则 5: 部分匹配（列名包含词根）
        for root_name, root_desc in roots.items():
            if root_name in column_name or column_name in root_name:
                return ColumnValidationResult(
                    column_name=column_name,
                    status="warning",
                    root=root_name,
                    suggestion=f"建议改为标准词根组合，参考: {root_name} ({root_desc})",
                    reason=f"部分匹配词根: {root_name}",
                )

        # 规则 6: 完全不匹配
        suggestion = self._suggest_fix(column_name, roots)
        return ColumnValidationResult(
            column_name=column_name,
            status="failure",
            suggestion=suggestion,
            reason="未在词根表中找到匹配",
        )

    def _suggest_fix(self, column_name: str, roots: dict[str, str]) -> str:
        """
        为不合规列名提供修正建议。

        策略：
        1. 尝试以下划线拆分，寻找最接近的词根
        2. 提供相似词根推荐
        """
        parts = column_name.split("_")
        suggestions: list[str] = []

        for part in parts:
            if part in roots:
                continue
            # 查找相似词根（编辑距离 <= 2）
            closest = self._find_closest_root(part, roots)
            if closest:
                suggestions.append(f"{part} → {closest}")

        if suggestions:
            return "、".join(suggestions)
        return "建议使用标准词根组合，参考词根表 dim_pub_column_dictionary_static"

    def _find_closest_root(self, text: str, roots: dict[str, str], max_distance: int = 2) -> str | None:
        """
        查找最接近的词根（基于编辑距离）。
        """
        best_match: str | None = None
        best_distance = max_distance + 1

        for root_name in roots:
            distance = self._edit_distance(text, root_name)
            if distance < best_distance:
                best_distance = distance
                best_match = root_name

        return best_match if best_distance <= max_distance else None

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """计算两个字符串的编辑距离。"""
        if len(s1) < len(s2):
            return WordRootValidator._edit_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def _load_word_roots(self) -> dict[str, str]:
        """
        加载词根缓存。

        优先从 loader 获取（LRU 缓存），回退到直接数据库读取。
        """
        roots: dict[str, str] = {}

        try:
            # 从 loader 获取
            entries = self._load_func()
            if entries:
                roots = {e["column_name"]: e.get("column_desc", "") for e in entries}
                return roots
        except Exception:
            pass

        # 降级：直接从数据库读取
        try:
            with SessionLocal() as db:
                stmt = select(WordRootCacheModel)
                results = db.execute(stmt).scalars().all()
                for row in results:
                    roots[row.column_name] = row.column_desc or ""
        except Exception as exc:
            logger.warning("加载词根缓存失败: %s", exc)

        return roots

    async def suggest_fixes(self, invalid_column: str) -> list[str]:
        """
        为不合规列名提供修正建议。

        便捷方法，返回建议列表。
        """
        roots = self._load_word_roots()
        result = self._validate_single_column(invalid_column.lower(), roots)
        suggestions: list[str] = []
        if result.suggestion:
            suggestions.append(result.suggestion)
        if result.root:
            suggestions.append(f"当前匹配词根: {result.root}")
        return suggestions if suggestions else ["建议使用标准词根组合"]


# ── 单例 ──────────────────────────────────────────────────────────

_validator_instance: WordRootValidator | None = None


def get_word_root_validator() -> WordRootValidator:
    """获取词根校验器单例。"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = WordRootValidator()
    return _validator_instance
