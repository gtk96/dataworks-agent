"""DestructiveOpGuard — 执行层破坏性操作拦截闸（Requirement 36）。

仅在执行提交前生效（MaxCompute_Client 提交 SQL、OpenAPI_Client 删除/下线节点
之前），不在生成/提议/校验层拦截——agent 可生成并预览这类代码作为 Artifact
供人工评审，平台只是不代为执行。

拦截规则：
- DELETE / TRUNCATE：一律拒绝执行；
- DROP TABLE：仅放行 tmp_ / test_ 前缀表，其余拒绝；
- DROP PARTITION、ALTER TABLE ... DROP COLUMN：默认拒绝；
- 节点删除 / 下线：一律拒绝；
- INSERT OVERWRITE / INSERT INTO / CREATE / ALTER(非删列) / SELECT：放行。

拦截事件记入 Event_Log（Task 7 落地后接入；当前经 logger 记录）。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 允许放行的 DROP TABLE 前缀
_DROPPABLE_TABLE_PREFIXES = ("tmp_", "test_")

# 节点操作黑名单（大写归一后匹配）
_FORBIDDEN_NODE_OPS: frozenset[str] = frozenset(
    {"DELETE_NODE", "OFFLINE_NODE", "DELETE", "OFFLINE", "DEPLOY_OFFLINE", "UNDEPLOY"}
)

# 行注释 / 块注释
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# 语句分类
_RE_DELETE = re.compile(r"^\s*DELETE\s+(FROM\b|\w)", re.IGNORECASE)
_RE_TRUNCATE = re.compile(r"^\s*TRUNCATE\b", re.IGNORECASE)
_RE_DROP_PARTITION = re.compile(r"\bDROP\s+(IF\s+EXISTS\s+)?PARTITION\b", re.IGNORECASE)
_RE_ALTER_DROP_COLUMN = re.compile(
    r"\bALTER\s+TABLE\b.*\bDROP\s+COLUMNS?\b", re.IGNORECASE | re.DOTALL
)
_RE_DROP_TABLE = re.compile(
    r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([`\"]?[\w.]+[`\"]?)", re.IGNORECASE
)


class DestructiveOpBlockedError(RuntimeError):
    """破坏性操作在执行层被拦截 — 不予执行。"""


def _strip_comments(sql: str) -> str:
    """剥离行注释与块注释，避免注释里的关键字误伤或绕过。"""
    return _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql))


def _split_statements(sql: str) -> list[str]:
    """按分号粗分语句（注释已剥离），过滤空白语句。"""
    return [s.strip() for s in sql.split(";") if s.strip()]


def _bare_table_name(raw: str) -> str:
    """从 DROP TABLE 捕获的表名取裸表名（去 schema 前缀与引号）。"""
    name = raw.strip().strip('`"')
    return name.split(".")[-1].lower()


def _reject(reason: str, summary: str) -> None:
    logger.warning("DestructiveOpGuard 拦截执行：%s | 语句摘要: %s", reason, summary[:200])
    raise DestructiveOpBlockedError(f"{reason}（已在执行层拦截，不予执行）")


def guard_sql(sql: str) -> None:
    """在提交执行前校验 SQL；命中破坏性操作则拦截并抛错。

    Raises:
        DestructiveOpBlockedError: SQL 含被禁止执行的破坏性操作。
    """
    cleaned = _strip_comments(sql)
    for stmt in _split_statements(cleaned):
        summary = re.sub(r"\s+", " ", stmt)

        if _RE_DELETE.search(stmt):
            _reject("禁止执行 DELETE 语句", summary)
        if _RE_TRUNCATE.search(stmt):
            _reject("禁止执行 TRUNCATE 语句", summary)
        if _RE_DROP_PARTITION.search(stmt):
            _reject("禁止执行 DROP PARTITION", summary)
        if _RE_ALTER_DROP_COLUMN.search(stmt):
            _reject("禁止执行 ALTER TABLE ... DROP COLUMN", summary)

        m = _RE_DROP_TABLE.match(stmt)
        if m:
            table = _bare_table_name(m.group(1))
            if not table.startswith(_DROPPABLE_TABLE_PREFIXES):
                _reject(
                    f"禁止 DROP 非 tmp_/test_ 表: {table}",
                    summary,
                )


def guard_node_op(op: str) -> None:
    """在提交执行前校验调度节点操作；删除/下线一律拦截。

    Raises:
        DestructiveOpBlockedError: 节点删除或下线操作。
    """
    normalized = (op or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in _FORBIDDEN_NODE_OPS:
        _reject(f"禁止执行节点删除/下线操作: {op}", op)
