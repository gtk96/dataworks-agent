"""Shared utilities for DWD dependency resolution."""

from __future__ import annotations

import re


def find_ods_sources(dml: str) -> list[str]:
    """从 DML 中解析所有上游 ODS 表引用（FROM + JOIN）。

    匹配模式: ``dataworks.ods_*`` 形式的完整限定表名，排除别名和注释。
    返回去重后的表名列表（不含 schema 前缀）。
    """
    # 逐行处理，跳过注释行
    lines = dml.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        # 跳过行尾注释
        if stripped.startswith("--"):
            continue
        # 剥离行尾注释（-- 后内容）
        if "--" in stripped:
            stripped = stripped[: stripped.index("--")].rstrip()
        cleaned.append(stripped)
    full_sql = " ".join(cleaned)

    # 匹配 FROM/JOIN 后的 qualified table name: dataworks.ods_xxx
    # 排除别名: dataworks.ods_xxx t1 → 只取 ods_xxx
    pattern = r"(?:from|join)\s+dataworks\.(\w+(?:_\w+)*)"
    matches = re.findall(pattern, full_sql, re.IGNORECASE)
    # 去重但保留顺序
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result
