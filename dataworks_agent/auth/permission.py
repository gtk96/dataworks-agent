"""Permission_Model — 身份解析与团队/组织编码鉴权。

实现 Requirement 34：
- 基于 User_Directory 将钉钉用户解析为内部用户及其团队与组织编码
- 依据团队与组织编码决定数据范围与可执行操作
- 未登录回退到 IP_Identity 归属
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class UserIdentity:
    """用户身份。"""

    user_id: str
    username: str = ""
    team: str = ""
    org_code: str = ""
    role: str = "viewer"  # viewer/editor/admin
    source: str = ""  # dingtalk/web/ip
    ip_address: str = ""


@dataclass
class Permission:
    """权限定义。"""

    resource: str  # 资源类型（table/metric/rule）
    action: str  # 操作（read/write/delete）
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionCheckResult:
    """权限检查结果。"""

    allowed: bool
    reason: str = ""
    required_permissions: list[Permission] = field(default_factory=list)


class UserDirectory:
    """用户目录 — 钉钉用户解析为内部用户。

    缓存钉钉表 join 内部用户表。
    """

    def __init__(self) -> None:
        self._users: dict[str, UserIdentity] = {}

    def get_user(self, user_id: str) -> UserIdentity | None:
        """获取用户。"""
        return self._users.get(user_id)

    def resolve_from_dingtalk(
        self, dingtalk_id: str, dingtalk_info: dict[str, Any]
    ) -> UserIdentity:
        """从钉钉信息解析用户。"""
        # 简化实现：直接使用钉钉信息
        user = UserIdentity(
            user_id=dingtalk_id,
            username=dingtalk_info.get("name", ""),
            team=dingtalk_info.get("team", ""),
            org_code=dingtalk_info.get("org_code", ""),
            role=dingtalk_info.get("role", "viewer"),
            source="dingtalk",
        )
        self._users[dingtalk_id] = user
        return user

    def resolve_from_ip(self, ip_address: str) -> UserIdentity:
        """从 IP 解析用户（回退）。"""
        user = UserIdentity(
            user_id=f"ip_{ip_address}",
            username=f"anonymous@{ip_address}",
            team="",
            org_code="",
            role="viewer",  # 只读权限
            source="ip",
            ip_address=ip_address,
        )
        return user


class PermissionModel:
    """权限模型 — 依据团队与组织编码授权。

    统一接入 MCP/查询/归因。
    """

    def __init__(self) -> None:
        self._permissions: dict[str, list[Permission]] = {}

    def check_permission(
        self,
        user: UserIdentity,
        resource: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> PermissionCheckResult:
        """检查权限。"""
        context = context or {}

        # 1. 检查角色权限
        if user.role == "admin":
            return PermissionCheckResult(allowed=True, reason="管理员权限")

        # 2. 检查团队权限
        if user.team:
            team_permissions = self._get_team_permissions(user.team)
            for perm in team_permissions:
                if (
                    perm.resource == resource
                    and perm.action == action
                    and self._check_conditions(perm.conditions, context)
                ):
                    return PermissionCheckResult(
                        allowed=True,
                        reason=f"团队 {user.team} 权限",
                    )

        # 3. 检查组织权限
        if user.org_code:
            org_permissions = self._get_org_permissions(user.org_code)
            for perm in org_permissions:
                if (
                    perm.resource == resource
                    and perm.action == action
                    and self._check_conditions(perm.conditions, context)
                ):
                    return PermissionCheckResult(
                        allowed=True,
                        reason=f"组织 {user.org_code} 权限",
                    )

        # 4. 检查默认权限
        default_permissions = self._get_default_permissions(user.role)
        for perm in default_permissions:
            if perm.resource == resource and perm.action == action:
                return PermissionCheckResult(
                    allowed=True,
                    reason=f"默认 {user.role} 权限",
                )

        # 5. 无权限
        return PermissionCheckResult(
            allowed=False,
            reason=f"用户 {user.user_id} 无权执行 {action} on {resource}",
        )

    def _get_team_permissions(self, team: str) -> list[Permission]:
        """获取团队权限。"""
        return self._permissions.get(f"team:{team}", [])

    def _get_org_permissions(self, org_code: str) -> list[Permission]:
        """获取组织权限。"""
        return self._permissions.get(f"org:{org_code}", [])

    def _get_default_permissions(self, role: str) -> list[Permission]:
        """获取默认权限。"""
        return self._permissions.get(f"default:{role}", [])

    def _check_conditions(self, conditions: dict[str, Any], context: dict[str, Any]) -> bool:
        """检查条件。"""
        for key, value in conditions.items():
            if key not in context:
                return False
            if context[key] != value:
                return False
        return True

    def add_permission(self, scope: str, permission: Permission) -> None:
        """添加权限。"""
        if scope not in self._permissions:
            self._permissions[scope] = []
        self._permissions[scope].append(permission)

    def get_user_from_request(self, request: dict[str, Any]) -> UserIdentity:
        """从请求中获取用户。"""
        # 优先从钉钉身份获取
        dingtalk_id = request.get("dingtalk_id")
        if dingtalk_id:
            dingtalk_info = request.get("dingtalk_info", {})
            return UserDirectory().resolve_from_dingtalk(dingtalk_id, dingtalk_info)

        # 回退到 IP
        ip_address = request.get("ip_address", "127.0.0.1")
        return UserDirectory().resolve_from_ip(ip_address)
