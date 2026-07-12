"""闭环验收器单元测试 — Loop Engineering 验收标准。"""

import pytest

from dataworks_agent.governance.closed_loop_verifier import (
    CheckResult,
    CheckSeverity,
    ClosedLoopVerifier,
    VerificationResult,
    VerificationStatus,
)


@pytest.fixture
def verifier():
    """创建验收器实例。"""
    return ClosedLoopVerifier()


@pytest.mark.asyncio
async def test_verify_ods_success(verifier):
    """ODS 任务验收通过。"""
    result = await verifier.verify(
        task_id="task_test_001",
        task_type="ODS",
        context={
            "ddl": "CREATE TABLE ods_ord_order_hour (id STRING, name STRING) PARTITIONED BY (dt STRING);",
            "fields": [],  # 跳过词根校验（需要 MCP）
            "holo_sql": "IMPORT FOREIGN SCHEMA public FROM SERVER dataworks_holo INTO cda;",
            "dml": "INSERT INTO cda.ods_ord_order_hour SELECT id, name FROM source WHERE dt = '${bizdate}';",
        },
    )

    assert result.status == VerificationStatus.PASSED
    assert result.passed_count > 0
    assert result.failed_count == 0


@pytest.mark.asyncio
async def test_verify_ods_failed_ddl(verifier):
    """ODS 任务验收失败 — DDL 语法错误（缺少 CREATE TABLE）。"""
    result = await verifier.verify(
        task_id="task_test_002",
        task_type="ODS",
        context={
            "ddl": "INSERT INTO table VALUES (1);",  # 不是有效的 DDL
            "fields": [],
            "holo_sql": "",
            "dml": "",
        },
    )

    # DDL 命名检查应该失败
    failed_checks = [c for c in result.checks if not c.passed]
    assert len(failed_checks) > 0


@pytest.mark.asyncio
async def test_verify_dwd_success(verifier):
    """DWD 任务验收通过。"""
    result = await verifier.verify(
        task_id="task_test_003",
        task_type="DWD",
        context={
            "ddl": "CREATE TABLE dwd_ord_order_detail_day (id STRING, name STRING) PARTITIONED BY (dt STRING);",
            "fields": [],  # 跳过词根校验（需要 MCP）
            "sql": "SELECT id, name FROM ods_ord_order_hour WHERE dt = '${bizdate}';",
            "target_layer": "DWD",
            "source_tables": ["ods_ord_order_hour"],
        },
    )

    assert result.status == VerificationStatus.PASSED


@pytest.mark.asyncio
async def test_verify_dwd_failed_layer_dependency(verifier):
    """DWD 任务验收失败 — 层间依赖校验。"""
    result = await verifier.verify(
        task_id="task_test_004",
        task_type="DWD",
        context={
            "ddl": "CREATE TABLE dwd_ord_order_detail_day (id STRING);",
            "fields": [],
            "sql": "",
            "target_layer": "DWD",
            "source_tables": ["dws_wrong_layer"],  # DWD 不能引用 DWS
        },
    )

    # 层间依赖检查应该失败
    failed_checks = [c for c in result.checks if c.check_name == "layer_dependency"]
    assert len(failed_checks) == 1
    assert not failed_checks[0].passed


@pytest.mark.asyncio
async def test_verify_empty_task_type(verifier):
    """Unconfigured task types must fail closed instead of silently passing."""
    result = await verifier.verify(
        task_id="task_test_005",
        task_type="UNKNOWN",
        context={},
    )

    assert result.status == VerificationStatus.FAILED
    assert result.failed_count == 1
    assert result.checks[0].check_name == "supported_task_type"


@pytest.mark.asyncio
async def test_verify_sql_syntax_error(verifier):
    """SQL 语法错误验收失败。"""
    result = await verifier.verify(
        task_id="task_test_006",
        task_type="DWD",
        context={
            "ddl": "CREATE TABLE dwd_test_day (id STRING);",
            "fields": [],
            "sql": "SELECT * FROM WHERE;",  # 语法错误
            "target_layer": "DWD",
            "source_tables": [],
        },
    )

    # SQL 语法检查应该失败
    sql_checks = [c for c in result.checks if c.check_name == "sql_syntax"]
    assert len(sql_checks) == 1
    assert not sql_checks[0].passed


def test_verification_result_summary():
    """验收结果摘要。"""
    # 通过
    result = VerificationResult(
        task_id="task_001",
        task_type="ODS",
        status=VerificationStatus.PASSED,
        passed_count=4,
        failed_count=0,
    )
    assert "验收通过" in result.summary

    # 失败
    result = VerificationResult(
        task_id="task_002",
        task_type="ODS",
        status=VerificationStatus.FAILED,
        checks=[
            CheckResult(check_name="ddl_naming_check", passed=False, severity=CheckSeverity.ERROR),
        ],
        passed_count=3,
        failed_count=1,
    )
    assert "验收失败" in result.summary
    assert "ddl_naming_check" in result.summary


def test_register_custom_check():
    """注册自定义检查。"""
    verifier = ClosedLoopVerifier()

    async def custom_check(task_id: str, **kwargs) -> CheckResult:
        return CheckResult(
            check_name="custom_check",
            passed=True,
            severity=CheckSeverity.WARNING,
            message="自定义检查通过",
        )

    verifier.register_check("custom_check", custom_check)
    assert "custom_check" in verifier._checks


@pytest.mark.asyncio
async def test_verify_ask_data_success(verifier):
    result = await verifier.verify(
        task_id="ask_data_test",
        task_type="ASK_DATA",
        context={
            "sql": "SELECT family_name, effective_order_cnt FROM sample",
            "executed": True,
            "columns": ["family_name", "effective_order_cnt"],
            "rows": [["family-a", 1]],
            "row_count": 1,
        },
    )
    assert result.status == VerificationStatus.PASSED
    assert result.passed_count == 3


@pytest.mark.asyncio
async def test_verify_ask_data_rejects_plan_only_result(verifier):
    result = await verifier.verify(
        task_id="ask_data_plan_only",
        task_type="ASK_DATA",
        context={
            "sql": "SELECT * FROM sample",
            "executed": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
        },
    )
    assert result.status == VerificationStatus.FAILED
    failed = {check.check_name for check in result.checks if not check.passed}
    assert {"query_executed", "query_result_shape"} <= failed
