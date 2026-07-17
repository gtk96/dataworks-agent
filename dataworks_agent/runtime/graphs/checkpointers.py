"""LangGraph Checkpointer 配置。

替代原有的 memory_layering.py + memory_service.py。
生产环境使用 PostgresSaver，开发环境使用 MemorySaver。
"""

from __future__ import annotations

import os
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

# 从环境变量读取 Checkpointer 后端
_CHECKPOINT_BACKEND = os.getenv("LANGGRAPH_CHECKPOINT_BACKEND", "memory")


def get_checkpointer(config: dict[str, Any] | None = None) -> Any:
    """获取 LangGraph Checkpointer 实例。

    支持的后端:
    - memory: 内存 Checkpointer（开发/测试用，默认）
    - postgres: PostgreSQL Checkpointer（生产用）

    注意: PostgresSaver 需要额外安装 langgraph-checkpoint-postgres。
    """
    if _CHECKPOINT_BACKEND == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            uri = os.getenv("LANGGRAPH_CHECKPOINT_URI", "")
            if not uri:
                raise ValueError("LANGGRAPH_CHECKPOINT_URI not set for postgres backend")
            return PostgresSaver.from_conn_string(uri)
        except ImportError:
            # 降级到 memory
            return MemorySaver()
    else:
        # 默认: MemorySaver（开发/测试）
        return MemorySaver()
