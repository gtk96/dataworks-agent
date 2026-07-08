"""审计日志 — 关键操作记录（谁/何时/做了什么）。"""

from __future__ import annotations

import logging

audit_logger = logging.getLogger("dataworks_agent.audit")


def audit_log(action: str, *, ip: str = "", detail: str = "", **kwargs) -> None:
    """记录审计事件。"""
    parts = [f"action={action}"]
    if ip:
        parts.append(f"ip={ip}")
    if detail:
        parts.append(f"detail={detail}")
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    audit_logger.info("AUDIT | %s", " | ".join(parts))
