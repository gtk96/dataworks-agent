"""DDL 规范检查器 — 验证 DDL 是否符合数仓建设规范。"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DdlCheckResult:
    """DDL 检查结果。"""

    table_name: str
    passed: bool
    errors: list[str]
    warnings: list[str]


# 表命名规范
_TABLE_NAME_PATTERNS = {
    "ODS": re.compile(r"^ods_[a-z0-9]+_[a-z0-9]+__[a-z0-9]+_(hour|hourly|day|all|static)$"),
    "DWD": re.compile(r"^dwd_[a-z0-9]+_[a-z0-9_]+_(hour|hourly|day|all|his)$"),
    "DWS": re.compile(r"^dws_[a-z0-9]+_[a-z0-9_]+_(hour|hourly|day|all)$"),
    "DMR": re.compile(r"^dmr_[a-z0-9_]+_(hour|hourly|day|all)$"),
    "DIM": re.compile(r"^dim_[a-z0-9]+_[a-z0-9_]+_(hour|hourly|day|all|static)$"),
    "TMP": re.compile(r"^tmp_[a-z0-9_]+_(\d+)$"),
}

# 字段类型规范
_AMOUNT_SUFFIXES = re.compile(
    r"(amt|cost|price|fee|spend|budget|revenue|income|profit|loss|payment|refund)$", re.IGNORECASE
)
_COUNT_SUFFIXES = re.compile(
    r"(cnt|count|num|total|sales|clicks|impressions|views|pv|uv|orders|qty|quantity)$",
    re.IGNORECASE,
)
_RATIO_SUFFIXES = re.compile(r"(ratio|rate|cnv|ctr|roi|cpm|cpc|cpa|cvr|arpu|arppu)$", re.IGNORECASE)


def _infer_expected_type(field_name: str) -> str:
    """根据字段名推断期望的类型。"""
    lower = field_name.lower()

    if lower.endswith("id"):
        return "string"
    if _AMOUNT_SUFFIXES.search(lower):
        return "decimal(24,6)"
    if _COUNT_SUFFIXES.search(lower):
        return "bigint"
    if _RATIO_SUFFIXES.search(lower):
        return "decimal(24,6)"
    return "string"


def _normalize_type(type_str: str) -> str:
    """规范化类型字符串用于比较。"""
    return re.sub(r"\s+", "", type_str.upper())


def check_ddl(ddl_text: str) -> DdlCheckResult:
    """检查 DDL 是否符合数仓规范。

    检查项：
    1. 表命名规范
    2. DDL 语法（drop table if exists + create table）
    3. LIFECYCLE 规范
    4. 字段类型规范
    5. 分区字段规范
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not ddl_text or not ddl_text.strip():
        return DdlCheckResult(table_name="", passed=False, errors=["DDL 为空"], warnings=[])

    # 解析 DDL
    ddl_upper = ddl_text.upper()

    # 提取表名
    table_match = re.search(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
        ddl_text,
        re.IGNORECASE,
    )
    if not table_match:
        return DdlCheckResult(table_name="", passed=False, errors=["无法解析表名"], warnings=[])

    table_name = table_match.group(1).strip('`"')
    bare_table = table_name.split(".")[-1] if "." in table_name else table_name

    # 1. 检查表命名规范
    layer = _identify_layer(bare_table)
    if layer and layer in _TABLE_NAME_PATTERNS:
        pattern = _TABLE_NAME_PATTERNS[layer]
        if not pattern.match(bare_table.lower()):
            warnings.append(f"表名 '{bare_table}' 不符合 {layer} 层命名规范")

    # 2. 检查 DDL 语法
    has_drop = "DROP TABLE IF EXISTS" in ddl_upper
    has_create = "CREATE TABLE" in ddl_upper
    has_if_not_exists = "IF NOT EXISTS" in ddl_upper

    if not has_drop:
        warnings.append("缺少 'drop table if exists' 语句")
    if not has_create:
        errors.append("缺少 'create table' 语句")
    if has_if_not_exists:
        warnings.append("DDL 包含 'if not exists'，规范建议不加")

    # 3. 检查 LIFECYCLE
    has_lifecycle = "LIFECYCLE" in ddl_upper
    if has_lifecycle and layer in ("ODS", "DWD", "DWS", "DMR", "DIM"):
        errors.append(f"{layer} 层表不应设置 LIFECYCLE（应永久保存）")

    # 4. 检查字段类型
    columns = _extract_columns(ddl_text)
    for col in columns:
        if col["name"].lower() in ("dt", "ht", "hh", "mt", "update_ht", "begin_dt", "end_dt"):
            continue  # 跳过分区字段

        expected_type = _infer_expected_type(col["name"])
        actual_type = _normalize_type(col["type"])
        expected_normalized = _normalize_type(expected_type)

        if actual_type != expected_normalized:
            # 检查是否是已知的类型不匹配
            if expected_type == "string" and actual_type in ("STRING", "VARCHAR", "TEXT"):
                continue  # 可接受
            if expected_type == "bigint" and actual_type in ("BIGINT", "INT", "INTEGER"):
                continue  # 可接受
            warnings.append(
                f"字段 '{col['name']}' 类型 '{col['type']}' "
                f"可能不符合规范（期望 '{expected_type}'）"
            )

    # 5. 检查分区字段
    partitions = _extract_partitions(ddl_text)
    if layer and layer in ("ODS", "DWD", "DWS", "DMR", "DIM") and not partitions:
        warnings.append(f"{layer} 层表通常需要分区字段（dt）")

    passed = len(errors) == 0
    return DdlCheckResult(
        table_name=bare_table,
        passed=passed,
        errors=errors,
        warnings=warnings,
    )


def _identify_layer(table_name: str) -> str | None:
    """识别表所属层。"""
    lower = table_name.lower()
    for prefix in ("ods_", "dwd_", "dws_", "dmr_", "dim_", "tmp_"):
        if lower.startswith(prefix):
            return prefix.rstrip("_").upper()
    return None


def _extract_columns(ddl_text: str) -> list[dict[str, str]]:
    """从 DDL 中提取列定义。"""
    columns = []
    in_columns = False
    in_partitions = False

    for line in ddl_text.split("\n"):
        line = line.strip().rstrip(",")
        if not line:
            continue

        if "CREATE TABLE" in line.upper():
            in_columns = True
            continue
        if "PARTITIONED BY" in line.upper():
            in_partitions = True
            in_columns = False
            continue

        # v14 F6-3: 字段行可能含 'COMMENT xxx' 后缀（`id BIGINT COMMENT '主键'`）；
        # 整行 skip 会丢字段。处理顺序：先解析字段部分，再把残余注释整行 skip。
        is_meta_line = line.upper().startswith(("COMMENT", "LIFECYCLE", "STORED", "TBLPROPERTIES"))
        if is_meta_line:
            continue

        if in_columns and not in_partitions:
            # 截断 COMMENT / LIFECYCLE 等元数据后缀，只解析 'name dtype' 前缀
            for keyword in ("COMMENT", "LIFECYCLE"):
                idx = line.upper().find(keyword)
                if idx > 0:
                    line = line[:idx].strip().rstrip(",")
                    break
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0].strip('`"')
                dtype = parts[1].strip(",").upper()
                if name and dtype and not name.startswith(("CREATE", "(", ")")):
                    columns.append({"name": name, "type": dtype})

    return columns


def _extract_partitions(ddl_text: str) -> list[str]:
    """从 DDL 中提取分区字段。"""
    partitions = []
    match = re.search(r"PARTITIONED\s+BY\s*\(([^)]+)\)", ddl_text, re.IGNORECASE)
    if match:
        part_block = match.group(1)
        for part in part_block.split(","):
            part = part.strip()
            if part:
                name = part.split()[0].strip('`"')
                if name:
                    partitions.append(name)
    return partitions


def check_ddl_text(ddl_text: str) -> dict:
    """检查 DDL 文本并返回结果字典。"""
    result = check_ddl(ddl_text)
    return {
        "table_name": result.table_name,
        "passed": result.passed,
        "errors": result.errors,
        "warnings": result.warnings,
    }
