"""网络工具 — IP 获取、等待可用等辅助函数。"""

from __future__ import annotations

import socket


def get_local_ip() -> str:
    """获取本机局域网 IP。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
