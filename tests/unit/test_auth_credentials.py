"""Auth_Provider 单元测试 — AK/SK 加载、缺失快速失败、脱敏（Requirement 2, 22）。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from dataworks_agent.auth import (
    AliyunCredentials,
    CredentialMissingError,
    load_credentials,
)
from dataworks_agent.auth import credentials as cred_mod


@pytest.fixture
def _set_creds(monkeypatch):
    """临时设置 settings 上的 AK/SK 值。"""

    def _apply(key_id: str, key_secret: str) -> None:
        monkeypatch.setattr(cred_mod.settings, "aliyun_access_key_id", key_id)
        monkeypatch.setattr(cred_mod.settings, "aliyun_access_key_secret", key_secret)

    return _apply


class TestLoadCredentials:
    def test_load_success(self, _set_creds) -> None:
        _set_creds("LTAI_test_id", "secret_value_1234")
        creds = load_credentials()
        assert isinstance(creds, AliyunCredentials)
        assert creds.access_key_id == "LTAI_test_id"
        assert creds.access_key_secret == "secret_value_1234"

    def test_missing_both_raises(self, _set_creds) -> None:
        _set_creds("", "")
        with pytest.raises(CredentialMissingError) as exc:
            load_credentials()
        assert "ALIYUN_ACCESS_KEY_ID" in str(exc.value)
        assert "ALIYUN_ACCESS_KEY_SECRET" in str(exc.value)

    def test_missing_id_only_raises(self, _set_creds) -> None:
        _set_creds("", "secret_value_1234")
        with pytest.raises(CredentialMissingError) as exc:
            load_credentials()
        assert "ALIYUN_ACCESS_KEY_ID" in str(exc.value)
        assert "ALIYUN_ACCESS_KEY_SECRET" not in str(exc.value)

    def test_missing_secret_only_raises(self, _set_creds) -> None:
        _set_creds("LTAI_test_id", "")
        with pytest.raises(CredentialMissingError) as exc:
            load_credentials()
        assert "ALIYUN_ACCESS_KEY_SECRET" in str(exc.value)
        assert "ALIYUN_ACCESS_KEY_ID" not in str(exc.value)

    def test_whitespace_treated_as_missing(self, _set_creds) -> None:
        _set_creds("   ", "\t\n")
        with pytest.raises(CredentialMissingError):
            load_credentials()

    def test_values_are_stripped(self, _set_creds) -> None:
        _set_creds("  LTAI_test_id  ", "  secret_value_1234  ")
        creds = load_credentials()
        assert creds.access_key_id == "LTAI_test_id"
        assert creds.access_key_secret == "secret_value_1234"


class TestMasking:
    def test_repr_masks_secret(self) -> None:
        creds = AliyunCredentials(access_key_id="LTAI_abcdefgh", access_key_secret="topsecret9999")
        text = repr(creds)
        assert "topsecret9999" not in text
        assert "LTAI_abcdefgh" not in text
        # 末 4 位保留用于排障
        assert "9999" in text
        assert "efgh" in text

    def test_credentials_are_immutable(self) -> None:
        creds = AliyunCredentials(access_key_id="a", access_key_secret="b")
        with pytest.raises(FrozenInstanceError):
            creds.access_key_id = "c"  # type: ignore[misc]
