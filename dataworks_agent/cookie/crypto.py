"""Cookie 加密存储 — 使用 Fernet 对称加密保证 cookie.dat 安全。

安全增强：
- PBKDF2-HMAC-SHA256 迭代次数升级到 600k+（OWASP 2026 推荐）
- 使用 per-install random salt（从环境变量或随机生成）
- cookie.dat 文件权限设为 0o600
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from dataworks_agent.config import settings

logger = logging.getLogger(__name__)

COOKIE_FILE = Path(settings.data_dir) / "cookie.dat"
SALT_FILE = Path(settings.data_dir) / "cookie.salt"


def _get_or_create_salt() -> bytes:
    """获取或创建 per-install salt。"""
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()

    # 生成随机 salt
    salt = os.urandom(16)
    SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SALT_FILE.write_bytes(salt)

    # 设置文件权限为 0o600（仅所有者可读写；Windows 可能不支持）
    try:
        os.chmod(str(SALT_FILE), 0o600)
    except OSError as exc:
        logger.error("无法设置 cookie.salt 文件权限 0o600: %s", exc)

    return salt


def _get_fernet() -> Fernet:
    """从 COOKIE_ENCRYPTION_KEY 派生 Fernet 密钥。"""
    raw_key = settings.cookie_encryption_key.encode("utf-8")
    salt = _get_or_create_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,  # OWASP 2026 推荐 600k+
    )
    key = base64.urlsafe_b64encode(kdf.derive(raw_key))
    return Fernet(key)


def encrypt_cookie(cookie_string: str) -> str:
    """加密 Cookie 字符串，返回 base64 密文。"""
    f = _get_fernet()
    token = f.encrypt(cookie_string.encode("utf-8"))
    return base64.urlsafe_b64encode(token).decode("utf-8")


def decrypt_cookie() -> str:
    """解密 cookie.dat，返回明文 Cookie 字符串。"""
    if not COOKIE_FILE.exists():
        return ""
    with open(COOKIE_FILE, "rb") as fh:
        token_b64 = fh.read()
    token = base64.urlsafe_b64decode(token_b64)
    f = _get_fernet()
    return f.decrypt(token).decode("utf-8")


def save_cookie(cookie_string: str) -> None:
    """加密并持久化 Cookie 到 data/cookie.dat。"""
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    encrypted = encrypt_cookie(cookie_string)
    # 使用临时文件 + 原子重命名保证写入安全
    tmp_path = COOKIE_FILE.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(encrypted)
    os.replace(tmp_path, COOKIE_FILE)

    # 设置文件权限为 0o600（仅所有者可读写；Windows 可能不支持）
    try:
        os.chmod(str(COOKIE_FILE), 0o600)
    except OSError as exc:
        logger.error("无法设置 cookie.dat 文件权限 0o600: %s", exc)


def has_cookie() -> bool:
    return COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 0
