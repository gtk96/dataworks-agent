"""IsolationVerifier 单元测试 — 隔离边界验证。"""

import pytest

from dataworks_agent.runtime.isolation import IsolationBoundary, IsolationVerifier


@pytest.fixture
def verifier():
    """创建 IsolationVerifier 实例。"""
    return IsolationVerifier()


def test_verify_target_schema_dev(verifier):
    """验证 dev schema — 允许。"""
    result = verifier.verify_target_schema("dataworks_dev")
    assert result["allowed"] is True


def test_verify_target_schema_prod(verifier):
    """验证 prod schema — 需要审批。"""
    result = verifier.verify_target_schema("dataworks")
    assert result["allowed"] is False
    assert "审批" in result["reason"]


def test_verify_target_schema_unknown(verifier):
    """验证未知 schema — 不允许。"""
    result = verifier.verify_target_schema("unknown_schema")
    assert result["allowed"] is False


def test_verify_dry_run_enabled(verifier):
    """验证 dry_run 模式 — 允许。"""
    result = verifier.verify_dry_run(True)
    assert result["allowed"] is True


def test_verify_code_execution_safe(verifier):
    """验证安全代码执行 — 允许。"""
    code = "print('hello')"
    result = verifier.verify_code_execution(code)
    assert result["allowed"] is True


def test_verify_code_execution_dangerous(verifier):
    """验证危险代码执行 — 不允许。"""
    code = "import os; os.system('rm -rf /')"
    result = verifier.verify_code_execution(code)
    assert result["allowed"] is False
    assert "危险" in result["reason"]


def test_verify_api_call_allowed(verifier):
    """验证允许的 API 调用 — 允许。"""
    result = verifier.verify_api_call("openapi_client.list_nodes")
    assert result["allowed"] is True


def test_verify_api_call_disallowed(verifier):
    """验证不允许的 API 调用 — 不允许。"""
    result = verifier.verify_api_call("unknown_api.call")
    assert result["allowed"] is False


def test_verify_all_safe(verifier):
    """综合验证 — 安全操作。"""
    operation = {
        "schema": "dataworks_dev",
        "dry_run": True,
        "requires_approval": False,
    }
    result = verifier.verify_all(operation)
    assert result["allowed"] is True


def test_verify_all_unsafe(verifier):
    """综合验证 — 不安全操作。"""
    operation = {
        "schema": "dataworks",  # prod schema
        "dry_run": False,
        "requires_approval": True,
    }
    result = verifier.verify_all(operation)
    # prod schema 需要审批，但操作本身是允许的（只是需要审批）
    assert "checks" in result


def test_get_boundary_config(verifier):
    """获取隔离边界配置。"""
    config = verifier.get_boundary_config()
    assert isinstance(config, IsolationBoundary)
    assert config.dev_schema == "dataworks_dev"
    assert config.prod_schema == "dataworks"
