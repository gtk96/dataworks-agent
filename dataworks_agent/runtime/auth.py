"""Web 钉钉扫码登录 — 身份解析与团队/组织编码。

实现 Requirement 34 和 35：
- Web 后端 `/auth/dingtalk/callback` + 前端扫码登录
- 解析团队/组织编码
- 渠道适配器统一接口
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DingTalkUserInfo:
    """钉钉用户信息。"""

    dingtalk_id: str
    name: str = ""
    avatar: str = ""
    team: str = ""
    org_code: str = ""
    email: str = ""
    phone: str = ""


@dataclass
class AuthToken:
    """认证令牌。"""

    user_id: str
    access_token: str
    refresh_token: str = ""
    expires_at: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


class DingTalkAuth:
    """钉钉扫码登录。"""

    def __init__(self) -> None:
        from dataworks_agent.auth.permission import UserDirectory

        self.user_directory = UserDirectory()

    async def handle_callback(self, code: str) -> AuthToken | None:
        """处理钉钉回调。"""
        # 简化实现：模拟钉钉 OAuth 流程
        # 实际应调用钉钉 OAuth API
        try:
            # 1. 用 code 换取 access_token
            token_info = await self._exchange_code(code)
            if not token_info:
                return None

            # 2. 获取用户信息
            user_info = await self._get_user_info(token_info["access_token"])
            if not user_info:
                return None

            # 3. 解析用户身份
            user = self.user_directory.resolve_from_dingtalk(
                user_info.dingtalk_id,
                {
                    "name": user_info.name,
                    "team": user_info.team,
                    "org_code": user_info.org_code,
                },
            )

            # 4. 生成认证令牌
            token = AuthToken(
                user_id=user.user_id,
                access_token=token_info["access_token"],
                refresh_token=token_info.get("refresh_token", ""),
                expires_at=token_info.get("expires_at", ""),
            )

            logger.info("钉钉扫码登录成功: %s", user.user_id)
            return token

        except Exception as e:
            logger.error("钉钉扫码登录失败: %s", e)
            return None

    async def _exchange_code(self, code: str) -> dict[str, Any] | None:
        """用 code 换取 access_token。"""
        # 简化实现：模拟钉钉 OAuth API
        return {
            "access_token": f"at_{code}",
            "refresh_token": f"rt_{code}",
            "expires_in": 7200,
        }

    async def _get_user_info(self, access_token: str) -> DingTalkUserInfo | None:
        """获取用户信息。"""
        # 简化实现：模拟钉钉用户信息 API
        return DingTalkUserInfo(
            dingtalk_id=f"dt_{access_token[:8]}",
            name="测试用户",
            team="data_team",
            org_code="org_001",
        )

    async def refresh_token(self, refresh_token: str) -> AuthToken | None:
        """刷新令牌。"""
        # 简化实现
        return AuthToken(
            user_id="user_001",
            access_token=f"at_{refresh_token[:8]}",
            refresh_token=refresh_token,
        )
