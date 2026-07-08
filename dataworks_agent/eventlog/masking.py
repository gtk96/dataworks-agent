"""密钥脱敏写入层（Requirement 22.2/22.4）。

在事件 payload 写入 Event_Log 前，排除 AK/SK 与 LLM_API_Key 明文：
- 按 key 名启发式（含 secret/api_key/password/token/access_key）整体打码；
- 按已配置的已知密钥字面值，在任意字符串中替换为打码串。
"""

from __future__ import annotations

from typing import Any

from dataworks_agent.config import settings

_REDACTED = "***REDACTED***"

_SENSITIVE_KEY_HINTS = (
    "secret",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "token",
    "access_key",
    "accesskey",
)


def _known_secret_values() -> list[str]:
    """从配置收集需在任意文本中打码的已知密钥字面值。"""
    candidates = [
        settings.aliyun_access_key_secret,
        settings.llm_api_key,
        settings.cookie_encryption_key,
    ]
    # 仅对足够长的真实密钥打码，避免误伤空值 / 占位符
    return [v for v in candidates if v and len(v) >= 8]


def _is_sensitive_key(key: Any) -> bool:
    kl = str(key).lower()
    return any(hint in kl for hint in _SENSITIVE_KEY_HINTS)


def _mask_str(text: str) -> str:
    masked = text
    for secret in _known_secret_values():
        if secret in masked:
            masked = masked.replace(secret, _REDACTED)

    # 脱敏 Cookie 头值（只保留 Cookie: 前缀，后面替换为 ***）
    if "Cookie:" in masked:
        import re

        masked = re.sub(
            r"(Cookie:\s*)(.+?)(\s*$)",
            r"\1***",
            masked,
            flags=re.IGNORECASE,
        )

    return masked


def mask_payload(payload: Any) -> Any:
    """递归脱敏 payload，返回可安全序列化写入的结构。"""
    if isinstance(payload, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(k) else mask_payload(v)) for k, v in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [mask_payload(v) for v in payload]
    if isinstance(payload, str):
        return _mask_str(payload)
    return payload
