"""ClosedLoopVerifier — 任务闭环验收器，实现 Loop Engineering 的验收标准。

任务完成后自动运行客观验收检查，全绿才算完。
参考 Loop Engineering 理念：验收是客观的，测试、typecheck、benchmark 给的是硬信号。

Validates: Requirements 37
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class VerificationStatus(StrEnum):
    """验收状态。"""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class CheckSeverity(StrEnum):
    """检查严重程度。"""

    ERROR = "error"  # 必须通过，否则验收失败
    WARNING = "warning"  # 建议通过，但不阻塞验收


@dataclass
class CheckResult:
    """单项检查结果。"""

    check_name: str
    passed: bool
    severity: CheckSeverity
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """验收结果。"""

    task_id: str
    task_type: str
    status: VerificationStatus
    checks: list[CheckResult] = field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    warning_count: int = 0

    @property
    def summary(self) -> str:
        """验收摘要。"""
        if self.status == VerificationStatus.PASSED:
            return f"验收通过 ({self.passed_count}/{self.passed_count + self.failed_count} 项)"
        elif self.status == VerificationStatus.FAILED:
            failed_names = [
                c.check_name
                for c in self.checks
                if not c.passed and c.severity == CheckSeverity.ERROR
            ]
            return f"验收失败: {', '.join(failed_names)}"
        else:
            return "待验收"


# 验收检查清单配置
VERIFICATION_CHECKLISTS: dict[str, list[str]] = {
    "ODS": [
        "ddl_naming_check",
        "root_check",
        "holo_sql_syntax",
        "dml_completeness",
    ],
    "DWD": [
        "ddl_naming_check",
        "root_check",
        "sql_syntax",
        "layer_dependency",
    ],
    "DIM": [
        "ddl_naming_check",
        "root_check",
        "sql_syntax",
        "daily_schedule_params",
    ],
    "DWS": [
        "ddl_naming_check",
        "root_check",
        "sql_syntax",
        "layer_dependency",
    ],
    "ASK_DATA": [
        "readonly_sql",
        "query_executed",
        "query_result_shape",
    ],
}


class ClosedLoopVerifier:
    """闭环验收器。

    任务完成后自动运行客观验收检查，全绿才算完。
    """

    def __init__(self) -> None:
        self._checks: dict[str, Callable[..., Coroutine[Any, Any, CheckResult]]] = {}
        self._register_builtin_checks()

    def _register_builtin_checks(self) -> None:
        """注册内置检查函数。"""
        self._checks["ddl_naming_check"] = self._check_ddl_naming
        self._checks["root_check"] = self._check_root
        self._checks["sql_syntax"] = self._check_sql_syntax
        self._checks["holo_sql_syntax"] = self._check_holo_sql_syntax
        self._checks["dml_completeness"] = self._check_dml_completeness
        self._checks["layer_dependency"] = self._check_layer_dependency
        self._checks["daily_schedule_params"] = self._check_daily_schedule_params
        self._checks["readonly_sql"] = self._check_readonly_sql
        self._checks["query_executed"] = self._check_query_executed
        self._checks["query_result_shape"] = self._check_query_result_shape

    def register_check(
        self,
        name: str,
        check_fn: Callable[..., Coroutine[Any, Any, CheckResult]],
    ) -> None:
        """注册自定义检查函数。"""
        self._checks[name] = check_fn

    async def verify(
        self, task_id: str, task_type: str, context: dict[str, Any]
    ) -> VerificationResult:
        """执行验收检查。

        Args:
            task_id: 任务ID
            task_type: 任务类型 (ODS/DWD/DIM/DWS)
            context: 上下文信息，包含 DDL/DML/SQL 等

        Returns:
            VerificationResult: 验收结果
        """
        result = VerificationResult(
            task_id=task_id,
            task_type=task_type,
            status=VerificationStatus.PENDING,
        )

        # 获取该任务类型的检查清单
        checklist = VERIFICATION_CHECKLISTS.get(task_type, [])
        if not checklist:
            logger.warning("\u4efb\u52a1\u7c7b\u578b %s \u65e0\u9a8c\u6536\u68c0\u67e5\u6e05\u5355\uff0c\u9a8c\u6536\u5931\u8d25", task_type)
            result.checks.append(
                CheckResult(
                    check_name="supported_task_type",
                    passed=False,
                    severity=CheckSeverity.ERROR,
                    message=f"\u4efb\u52a1\u7c7b\u578b {task_type} \u672a\u914d\u7f6e\u95ed\u73af\u9a8c\u6536\u6e05\u5355",
                )
            )
            result.failed_count = 1
            result.status = VerificationStatus.FAILED
            return result

        # 执行每项检查
        for check_name in checklist:
            check_fn = self._checks.get(check_name)
            if not check_fn:
                logger.warning("检查项 %s 未注册，跳过", check_name)
                continue

            try:
                check_result = await check_fn(task_id=task_id, **context)
                result.checks.append(check_result)

                if check_result.passed:
                    result.passed_count += 1
                elif check_result.severity == CheckSeverity.ERROR:
                    result.failed_count += 1
                else:
                    result.warning_count += 1
            except Exception as e:
                logger.error("检查项 %s 执行异常: %s", check_name, e)
                result.checks.append(
                    CheckResult(
                        check_name=check_name,
                        passed=False,
                        severity=CheckSeverity.ERROR,
                        message=f"执行异常: {e}",
                    )
                )
                result.failed_count += 1

        # 判定验收状态
        if result.failed_count == 0:
            result.status = VerificationStatus.PASSED
        else:
            result.status = VerificationStatus.FAILED

        logger.info(
            "任务 %s 验收完成: %s (通过=%d, 失败=%d, 警告=%d)",
            task_id,
            result.status.value,
            result.passed_count,
            result.failed_count,
            result.warning_count,
        )

        return result

    # ── 内置检查函数 ──

    async def _check_ddl_naming(self, task_id: str, ddl: str = "", **kwargs: Any) -> CheckResult:
        """DDL 命名规范检查。"""
        from dataworks_agent.governance.ddl_checker import check_ddl

        if not ddl:
            return CheckResult(
                check_name="ddl_naming_check",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无 DDL，跳过命名检查",
            )

        result = check_ddl(ddl)
        return CheckResult(
            check_name="ddl_naming_check",
            passed=result.passed,
            severity=CheckSeverity.ERROR,
            message="; ".join(result.errors) if result.errors else "DDL 命名规范通过",
            details={"table_name": result.table_name, "warnings": result.warnings},
        )

    async def _check_root(
        self, task_id: str, fields: list[str] | None = None, **kwargs: Any
    ) -> CheckResult:
        """词根校验。"""
        from dataworks_agent.modeling.root_checker import RootChecker

        if not fields:
            return CheckResult(
                check_name="root_check",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无字段列表，跳过词根校验",
            )

        checker = RootChecker()
        result = await checker.check_fields(fields)

        return CheckResult(
            check_name="root_check",
            passed=result.passed,
            severity=CheckSeverity.ERROR,
            message=result.summary,
            details={
                "invalid_fields": [f.field_name for f in result.field_results if not f.passed]
            },
        )

    async def _check_sql_syntax(self, task_id: str, sql: str = "", **kwargs: Any) -> CheckResult:
        """SQL 语法检查 (sqlglot)。"""
        if not sql:
            return CheckResult(
                check_name="sql_syntax",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无 SQL，跳过语法检查",
            )

        try:
            import sqlglot

            sqlglot.parse(sql, read="hive")
            return CheckResult(
                check_name="sql_syntax",
                passed=True,
                severity=CheckSeverity.ERROR,
                message="SQL 语法正确",
            )
        except Exception as e:
            return CheckResult(
                check_name="sql_syntax",
                passed=False,
                severity=CheckSeverity.ERROR,
                message=f"SQL 语法错误: {e}",
            )

    async def _check_holo_sql_syntax(
        self, task_id: str, holo_sql: str = "", **kwargs: Any
    ) -> CheckResult:
        """Holo SQL 语法检查。"""
        if not holo_sql:
            return CheckResult(
                check_name="holo_sql_syntax",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无 Holo SQL，跳过语法检查",
            )

        # Holo SQL 基本检查：必须包含 IMPORT FOREIGN SCHEMA 或有效的 DDL/DML
        has_import = "IMPORT FOREIGN SCHEMA" in holo_sql.upper()
        has_ddl = any(
            kw in holo_sql.upper() for kw in ["CREATE TABLE", "ALTER TABLE", "DROP TABLE"]
        )
        has_dml = any(kw in holo_sql.upper() for kw in ["INSERT", "UPDATE", "DELETE"])

        if has_import or has_ddl or has_dml:
            return CheckResult(
                check_name="holo_sql_syntax",
                passed=True,
                severity=CheckSeverity.ERROR,
                message="Holo SQL 结构正确",
            )
        else:
            return CheckResult(
                check_name="holo_sql_syntax",
                passed=False,
                severity=CheckSeverity.ERROR,
                message="Holo SQL 缺少有效的 IMPORT/DDL/DML 语句",
            )

    async def _check_dml_completeness(
        self, task_id: str, dml: str = "", **kwargs: Any
    ) -> CheckResult:
        """DML 完整性检查：必须包含 from/where/;"""
        if not dml:
            return CheckResult(
                check_name="dml_completeness",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无 DML，跳过完整性检查",
            )

        errors = []
        if "from" not in dml.lower():
            errors.append("缺少 FROM 子句")
        if "where" not in dml.lower():
            errors.append("缺少 WHERE 子句")
        if not dml.strip().endswith(";"):
            errors.append("缺少结尾分号")

        return CheckResult(
            check_name="dml_completeness",
            passed=len(errors) == 0,
            severity=CheckSeverity.ERROR,
            message="; ".join(errors) if errors else "DML 完整性通过",
        )

    async def _check_layer_dependency(
        self,
        task_id: str,
        target_layer: str = "",
        source_tables: list[str] | None = None,
        **kwargs: Any,
    ) -> CheckResult:
        """层间依赖校验。"""
        if not target_layer or not source_tables:
            return CheckResult(
                check_name="layer_dependency",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无层/源表信息，跳过依赖校验",
            )

        # 层间依赖规则
        valid_prefixes = {
            "DWD": {"ods"},
            "DIM": {"ods"},
            "DWS": {"dwd", "dim"},
            "DMR": {"dws"},
        }

        expected = valid_prefixes.get(target_layer.upper(), set())
        if not expected:
            return CheckResult(
                check_name="layer_dependency",
                passed=True,
                severity=CheckSeverity.WARNING,
                message=f"层 {target_layer} 无需校验依赖",
            )

        # 检查每个源表的前缀
        invalid_sources = []
        for table in source_tables:
            prefix = table.split("_")[0].lower() if "_" in table else table.lower()
            if prefix not in expected:
                invalid_sources.append(f"{table} (前缀: {prefix})")

        if invalid_sources:
            return CheckResult(
                check_name="layer_dependency",
                passed=False,
                severity=CheckSeverity.ERROR,
                message=f"层间依赖校验失败: {target_layer} 层的源表必须来自 {'/'.join(expected)} 层",
                details={"invalid_sources": invalid_sources},
            )
        else:
            return CheckResult(
                check_name="layer_dependency",
                passed=True,
                severity=CheckSeverity.ERROR,
                message="层间依赖校验通过",
            )

    async def _check_readonly_sql(
        self, task_id: str, sql: str = "", **kwargs: Any
    ) -> CheckResult:
        """\u95ee\u6570 SQL \u5fc5\u987b\u662f\u5355\u6761\u53ea\u8bfb\u67e5\u8be2\u3002"""
        normalized = sql.strip().lower()
        forbidden = ("insert", "update", "delete", "drop", "alter", "truncate", "create")
        passed = bool(normalized) and normalized.startswith(("select", "with")) and not any(
            token in normalized for token in forbidden
        )
        return CheckResult(
            check_name="readonly_sql",
            passed=passed,
            severity=CheckSeverity.ERROR,
            message="\u53ea\u8bfb SQL \u6821\u9a8c\u901a\u8fc7" if passed else "SQL \u4e0d\u662f\u5b89\u5168\u7684\u53ea\u8bfb\u67e5\u8be2",
        )

    async def _check_query_executed(
        self, task_id: str, executed: bool = False, **kwargs: Any
    ) -> CheckResult:
        """\u95ee\u6570\u4e0d\u80fd\u4ee5\u4ec5\u751f\u6210\u8ba1\u5212\u5192\u5145\u771f\u5b9e\u6267\u884c\u3002"""
        return CheckResult(
            check_name="query_executed",
            passed=executed,
            severity=CheckSeverity.ERROR,
            message="\u67e5\u8be2\u5df2\u771f\u5b9e\u6267\u884c" if executed else "\u67e5\u8be2\u672a\u771f\u5b9e\u6267\u884c",
        )

    async def _check_query_result_shape(
        self,
        task_id: str,
        columns: list[Any] | None = None,
        rows: list[Any] | None = None,
        row_count: int | None = None,
        **kwargs: Any,
    ) -> CheckResult:
        """\u67e5\u8be2\u7ed3\u679c\u5fc5\u987b\u6709\u53ef\u6e32\u67d3\u5217\u5b9a\u4e49\uff0c\u4e14\u884c\u6570\u4e0e\u6570\u636e\u4e00\u81f4\u3002"""
        columns = columns or []
        rows = rows or []
        passed = bool(columns) and row_count == len(rows)
        return CheckResult(
            check_name="query_result_shape",
            passed=passed,
            severity=CheckSeverity.ERROR,
            message="\u67e5\u8be2\u7ed3\u679c\u7ed3\u6784\u6821\u9a8c\u901a\u8fc7" if passed else "\u67e5\u8be2\u7ed3\u679c\u7f3a\u5c11\u5217\u6216\u884c\u6570\u4e0d\u4e00\u81f4",
            details={"column_count": len(columns), "row_count": len(rows)},
        )

    async def _check_daily_schedule_params(
        self, task_id: str, schedule_params: dict | None = None, **kwargs: Any
    ) -> CheckResult:
        """日全量调度参数检查。"""
        if not schedule_params:
            return CheckResult(
                check_name="daily_schedule_params",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="无调度参数，跳过检查",
            )

        # 日全量必须有 bizdate 参数
        has_bizdate = any("bizdate" in str(v).lower() for v in schedule_params.values())

        if has_bizdate:
            return CheckResult(
                check_name="daily_schedule_params",
                passed=True,
                severity=CheckSeverity.ERROR,
                message="日全量调度参数正确",
            )
        else:
            return CheckResult(
                check_name="daily_schedule_params",
                passed=False,
                severity=CheckSeverity.ERROR,
                message="日全量调度参数缺少 bizdate",
            )
