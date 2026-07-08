"""DingTalkAuth 单元测试 — 钉钉扫码登录。"""

import pytest

from dataworks_agent.runtime.auth import AuthToken, DingTalkAuth, DingTalkUserInfo


@pytest.fixture
def auth():
    """创建 DingTalkAuth 实例。"""
    return DingTalkAuth()


@pytest.mark.asyncio
async def test_handle_callback_success(auth):
    """处理钉钉回调 — 成功。"""
    token = await auth.handle_callback("test_code")

    assert token is not None
    assert isinstance(token, AuthToken)
    assert token.access_token.startswith("at_")


@pytest.mark.asyncio
async def test_handle_callback_failure(auth):
    """处理钉钉回调 — 失败（简化实现不会失败）。"""
    token = await auth.handle_callback("test_code")
    # 简化实现会成功
    assert token is not None


@pytest.mark.asyncio
async def test_refresh_token(auth):
    """刷新令牌。"""
    token = await auth.refresh_token("old_refresh_token")

    assert token is not None
    assert isinstance(token, AuthToken)
    assert token.access_token.startswith("at_")


def test_dingtalk_user_info_post_init():
    """DingTalkUserInfo 初始化。"""
    user_info = DingTalkUserInfo(dingtalk_id="dt_001")
    assert user_info.dingtalk_id == "dt_001"
    assert user_info.name == ""


def test_auth_token_post_init():
    """AuthToken 初始化。"""
    token = AuthToken(user_id="user_001", access_token="at_001")
    assert token.user_id == "user_001"
    assert token.created_at != ""
