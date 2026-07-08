"""Auth_Provider — 阿里云 AK/SK 凭证的唯一来源。

单一职责：从环境变量（经 pydantic-settings 落入 config.settings）提供 AK/SK，
供 OpenAPI_Client、MaxCompute_Client、MCP_Server 复用同一份凭证。

硬约束（Requirement 2）：
- 仅从环境变量 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET 读取；
- 不从 ECS RAM Role 获取；
- 不读取本地 credentials 文件（如 ~/.alibabacloud/credentials）；
- 缺失时抛 CredentialMissingError，在启动阶段快速失败，阻止依赖阿里云的操作。
"""

from __future__ import annotations

from dataclasses import dataclass

from dataworks_agent.config import settings


class CredentialMissingError(RuntimeError):
    """AK/SK 凭证缺失 — 阻止一切依赖阿里云的操作。"""


def _mask(secret: str) -> str:
    """脱敏展示：仅保留末 4 位，其余以 * 掩盖（Requirement 22）。"""
    if not secret:
        return "<empty>"
    if len(secret) <= 4:
        return "*" * len(secret)
    return "*" * (len(secret) - 4) + secret[-4:]


@dataclass(frozen=True)
class AliyunCredentials:
    """不可变的阿里云访问凭证。

    __repr__ 对 secret 脱敏，避免凭证明文进入日志 / Event_Log。
    """

    access_key_id: str
    access_key_secret: str

    def __repr__(self) -> str:  # pragma: no cover - 仅日志展示
        return (
            f"AliyunCredentials(access_key_id={_mask(self.access_key_id)!r}, "
            f"access_key_secret={_mask(self.access_key_secret)!r})"
        )


def load_credentials() -> AliyunCredentials:
    """从环境变量加载 AK/SK 并校验。

    Returns:
        AliyunCredentials: 已校验非空的凭证。

    Raises:
        CredentialMissingError: 当 ALIYUN_ACCESS_KEY_ID 或
            ALIYUN_ACCESS_KEY_SECRET 缺失 / 为空时。
    """
    access_key_id = (settings.aliyun_access_key_id or "").strip()
    access_key_secret = (settings.aliyun_access_key_secret or "").strip()

    missing = []
    if not access_key_id:
        missing.append("ALIYUN_ACCESS_KEY_ID")
    if not access_key_secret:
        missing.append("ALIYUN_ACCESS_KEY_SECRET")
    if missing:
        raise CredentialMissingError(
            "缺少阿里云访问凭证环境变量: "
            + ", ".join(missing)
            + "。请在 .env 或环境变量中配置后重试（不支持 ECS RAM Role / 本地 credentials 文件）。"
        )

    return AliyunCredentials(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
    )
