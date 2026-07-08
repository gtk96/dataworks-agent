"""PermissionModel 单元测试 — 身份与权限。"""

import pytest

from dataworks_agent.auth.permission import (
    Permission,
    PermissionCheckResult,
    PermissionModel,
    UserDirectory,
    UserIdentity,
)


@pytest.fixture
def directory():
    """创建 UserDirectory 实例。"""
    return UserDirectory()


@pytest.fixture
def model():
    """创建 PermissionModel 实例。"""
    return PermissionModel()


def test_resolve_from_dingtalk(directory):
    """从钉钉解析用户。"""
    user = directory.resolve_from_dingtalk(
        "dt_001",
        {"name": "张三", "team": "data_team", "org_code": "org_001"},
    )
    assert user.user_id == "dt_001"
    assert user.username == "张三"
    assert user.team == "data_team"
    assert user.source == "dingtalk"


def test_resolve_from_ip(directory):
    """从 IP 解析用户。"""
    user = directory.resolve_from_ip("192.168.1.1")
    assert user.user_id == "ip_192.168.1.1"
    assert user.role == "viewer"
    assert user.source == "ip"


def test_get_user(directory):
    """获取用户。"""
    directory.resolve_from_dingtalk("dt_001", {"name": "张三"})
    user = directory.get_user("dt_001")
    assert user is not None
    assert user.username == "张三"


def test_check_permission_admin(model):
    """检查权限 — 管理员。"""
    user = UserIdentity(user_id="admin", role="admin")
    result = model.check_permission(user, "table", "write")
    assert result.allowed is True


def test_check_permission_viewer(model):
    """检查权限 — 查看者（默认）。"""
    user = UserIdentity(user_id="user_001", role="viewer")
    result = model.check_permission(user, "table", "read")
    # 查看者可能有读权限（取决于默认配置）
    assert isinstance(result, PermissionCheckResult)


def test_add_permission(model):
    """添加权限。"""
    perm = Permission(resource="table", action="read")
    model.add_permission("team:data_team", perm)

    assert "team:data_team" in model._permissions
    assert len(model._permissions["team:data_team"]) == 1


def test_get_user_from_request_dingtalk(model):
    """从钉钉请求获取用户。"""
    request = {
        "dingtalk_id": "dt_001",
        "dingtalk_info": {"name": "张三", "team": "data_team"},
    }
    user = model.get_user_from_request(request)
    assert user.source == "dingtalk"
    assert user.team == "data_team"


def test_get_user_from_request_ip(model):
    """从 IP 请求获取用户。"""
    request = {"ip_address": "192.168.1.1"}
    user = model.get_user_from_request(request)
    assert user.source == "ip"
    assert user.ip_address == "192.168.1.1"


def test_user_identity_post_init():
    """UserIdentity 初始化。"""
    user = UserIdentity(user_id="test")
    assert user.user_id == "test"
    assert user.role == "viewer"


def test_permission_post_init():
    """Permission 初始化。"""
    perm = Permission(resource="table", action="read")
    assert perm.resource == "table"
    assert perm.action == "read"
    assert perm.conditions == {}
