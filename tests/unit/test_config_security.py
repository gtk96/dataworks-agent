"""Settings 安全校验单元测试 — v10 §6.1。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dataworks_agent.config import Settings


def test_cookie_encryption_key_rejects_short_value() -> None:
    with pytest.raises(ValidationError, match="COOKIE_ENCRYPTION_KEY"):
        Settings(cookie_encryption_key="too-short")


def test_cookie_encryption_key_accepts_min_length() -> None:
    s = Settings(cookie_encryption_key="test-cookie-key-for-ci-min16")
    assert len(s.cookie_encryption_key) >= 16
