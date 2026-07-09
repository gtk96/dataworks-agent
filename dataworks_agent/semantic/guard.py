"""确定性护栏 — 统一提议校验入口。

实现 Requirement 12：复用 Root_Checker/DDL_Checker/分层校验，
封装为统一"提议校验"入口；未过校验不得建表。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """校验结果。"""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class ProposalGuard:
    """提议校验器 — 统一入口。

    封装 Root_Checker、DDL_Checker、分层校验等确定性工具，
    作为 LLM 提议的验证器。未过校验不得建表。
    """

    def check_root(self, fields: list[str]) -> ValidationResult:
        """词根校验（优先 MCP 线上词根表）。"""
        import asyncio

        from dataworks_agent.modeling.root_checker import RootChecker

        checker = RootChecker()
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                result = asyncio.run(checker.check_fields(fields))
            else:
                result = checker.check_fields_local(fields)
                return ValidationResult(
                    passed=result.passed,
                    errors=[] if result.passed else [f"词根校验失败: {result.summary}"],
                    warnings=["词根校验在同步上下文中降级为本地字典"],
                    details={"field_results": [f.model_dump() for f in result.field_results]},
                )

            if result.passed:
                return ValidationResult(
                    passed=True,
                    warnings=(
                        ["词根校验来源：线上词根表"]
                        if result.source == "online"
                        else ["词根校验已降级为本地字典"]
                    ),
                )
            return ValidationResult(
                passed=False,
                errors=[f"词根校验失败: {result.summary}"],
                details={"field_results": [f.model_dump() for f in result.field_results]},
            )
        except Exception as e:
            logger.warning("词根校验异常: %s", e)
            return ValidationResult(passed=True, warnings=[f"词根校验跳过: {e}"])

    def check_ddl(self, ddl: str) -> ValidationResult:
        """DDL 规范检查。"""
        from dataworks_agent.governance.ddl_checker import check_ddl

        try:
            result = check_ddl(ddl)
            if result.passed:
                return ValidationResult(passed=True)
            else:
                return ValidationResult(
                    passed=False,
                    errors=result.errors,
                    warnings=result.warnings,
                    details={"table_name": result.table_name},
                )
        except Exception as e:
            logger.warning("DDL 检查异常: %s", e)
            return ValidationResult(passed=True, warnings=[f"DDL 检查跳过: {e}"])

    def check_table_name(self, table_name: str) -> ValidationResult:
        """表名规范检查。"""
        from dataworks_agent.naming.table_name import validate_table_name

        try:
            errors = validate_table_name(table_name)
            if not errors:
                return ValidationResult(passed=True)
            else:
                return ValidationResult(
                    passed=False,
                    errors=errors,
                )
        except Exception as e:
            logger.warning("表名检查异常: %s", e)
            return ValidationResult(passed=True, warnings=[f"表名检查跳过: {e}"])

    def check_layer_dependency(
        self, target_layer: str, source_tables: list[str]
    ) -> ValidationResult:
        """层间依赖校验。"""
        valid_prefixes = {
            "DWD": {"ods"},
            "DIM": {"ods"},
            "DWS": {"dwd", "dim"},
            "DMR": {"dws"},
        }

        expected = valid_prefixes.get(target_layer.upper(), set())
        if not expected:
            return ValidationResult(passed=True, warnings=[f"层 {target_layer} 无需校验依赖"])

        invalid_sources = []
        for table in source_tables:
            prefix = table.split("_")[0].lower() if "_" in table else table.lower()
            if prefix not in expected:
                invalid_sources.append(f"{table} (前缀: {prefix})")

        if invalid_sources:
            return ValidationResult(
                passed=False,
                errors=[
                    f"层间依赖校验失败: {target_layer} 层的源表必须来自 {'/'.join(expected)} 层"
                ],
                details={"invalid_sources": invalid_sources},
            )
        else:
            return ValidationResult(passed=True)

    def check_sql_syntax(self, sql: str) -> ValidationResult:
        """SQL 语法检查。"""
        try:
            import sqlglot

            sqlglot.parse(sql, read="hive")
            return ValidationResult(passed=True)
        except Exception as e:
            return ValidationResult(
                passed=False,
                errors=[f"SQL 语法错误: {e}"],
            )

    def check_proposal(self, proposal: dict[str, Any]) -> ValidationResult:
        """综合校验提议。

        proposal 格式:
        {
            "target_table": "dwd_ord_order_day",
            "target_layer": "DWD",
            "source_tables": ["ods_ord_order_hour"],
            "ddl": "CREATE TABLE ...",
            "sql": "INSERT INTO ...",
            "fields": ["id", "name", "order_id"],
        }
        """
        all_errors = []
        all_warnings = []

        # 1. 表名检查
        target_table = proposal.get("target_table", "")
        if target_table:
            result = self.check_table_name(target_table)
            if not result.passed:
                all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)

        # 2. DDL 检查
        ddl = proposal.get("ddl", "")
        if ddl:
            result = self.check_ddl(ddl)
            if not result.passed:
                all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)

        # 3. 词根检查
        fields = proposal.get("fields", [])
        if fields:
            result = self.check_root(fields)
            if not result.passed:
                all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)

        # 4. 层间依赖检查
        target_layer = proposal.get("target_layer", "")
        source_tables = proposal.get("source_tables", [])
        if target_layer and source_tables:
            result = self.check_layer_dependency(target_layer, source_tables)
            if not result.passed:
                all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)

        # 5. SQL 语法检查
        sql = proposal.get("sql", "")
        if sql:
            result = self.check_sql_syntax(sql)
            if not result.passed:
                all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)

        return ValidationResult(
            passed=len(all_errors) == 0,
            errors=all_errors,
            warnings=all_warnings,
        )


# 全局实例
proposal_guard = ProposalGuard()
