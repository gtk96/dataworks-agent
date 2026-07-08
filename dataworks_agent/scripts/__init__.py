"""项目脚本入口 — 包内 CLI 工具，可被外部 import。

- deploy_ods: 批量部署 ODS 表到 DataWorks
- repush_ods_dml: 仅重推节点 DML + 调度配置（不动 DDL/IMPORT）
- verify_ods_params: VFS 拉线上 DML 字节级 diff + 语义校验

CLI 运行:
    uv run python -m dataworks_agent.scripts.deploy_ods
    uv run python -m dataworks_agent.scripts.repush_ods_dml [--dry-run]
    uv run python -m dataworks_agent.scripts.verify_ods_params
"""

from __future__ import annotations

from dataworks_agent.scripts.deploy_ods import deploy_batch
from dataworks_agent.scripts.repush_ods_dml import repush_batch, repush_one
from dataworks_agent.scripts.verify_ods_params import (
    first_diff,
    list_ods_tables,
    read_online_dml,
    semantic_check,
)

__all__ = [
    "deploy_batch",
    "first_diff",
    "list_ods_tables",
    "read_online_dml",
    "repush_batch",
    "repush_one",
    "semantic_check",
]
