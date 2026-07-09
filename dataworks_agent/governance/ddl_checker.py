"""DDL 规范检查器 — 验证 DDL 是否符合数仓建设规范。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from dataworks_agent.schemas import RootCheckField, RootCheckResult

# 跳过分区/时间字段（不参与类型与词根检查）
_SKIP_FIELD_NAMES = frozenset(
    {"dt", "ht", "hh", "mt", "update_ht", "begin_dt", "end_dt"}
)

# 表命名规范
_TABLE_NAME_PATTERNS = {
    "ODS": re.compile(r"^ods_[a-z0-9]+_[a-z0-9]+__[a-z0-9]+_(hour|hourly|day|all|static)$"),
    "DWD": re.compile(r"^dwd_[a-z0-9]+_[a-z0-9_]+_(hour|hourly|day|all|his)$"),
    "DWS": re.compile(r"^dws_[a-z0-9]+_[a-z0-9_]+_(hour|hourly|day|all)$"),
    "DMR": re.compile(r"^dmr_[a-z0-9_]+_(hour|hourly|day|all)$"),
    "DIM": re.compile(r"^dim_[a-z0-9]+_[a-z0-9_]+_(hour|hourly|day|all|static)$"),
    "TMP": re.compile(r"^tmp_[a-z0-9_]+_(\d+)$"),
}

_RATIO_SUFFIXES = ("ratio", "rate", "cnv", "ctr", "roi", "cpm", "cpc", "cpa", "cvr", "arpu", "arppu")
_AMOUNT_SUFFIXES = (
    "amt",
    "cost",
    "price",
    "fee",
    "spend",
    "budget",
    "revenue",
    "income",
    "profit",
    "loss",
    "payment",
    "refund",
)
_COUNT_SUFFIXES = (
    "cnt",
    "count",
    "num",
    "total",
    "sales",
    "clicks",
    "impressions",
    "views",
    "pv",
    "uv",
    "orders",
    "qty",
    "quantity",
)


@dataclass
class DdlCheckResult:
    """DDL 检查结果。"""

    table_name: str
    passed: bool
    errors: list[str]
    warnings: list[str]
    root_source: str = ""


def _matches_suffix(field_name: str, suffixes: tuple[str, ...]) -> bool:
    """字段名须为 `suffix` 或 `*_suffix`，避免 `order_aamt` 误匹配 `amt`。"""
    lower = field_name.lower()
    return any(lower == suffix or lower.endswith(f"_{suffix}") for suffix in suffixes)


def _infer_expected_type(field_name: str) -> str:
    """根据字段名推断期望的类型。"""
    lower = field_name.lower()

    if _matches_suffix(lower, ("id",)):
        return "string"
    if _matches_suffix(lower, _AMOUNT_SUFFIXES):
        return "decimal(24,6)"
    if _matches_suffix(lower, _COUNT_SUFFIXES):
        return "bigint"
    if _matches_suffix(lower, _RATIO_SUFFIXES):
        return "decimal(24,6)"
    return "string"


def _normalize_type(type_str: str) -> str:
    """规范化类型字符串用于比较。"""
    return re.sub(r"\s+", "", type_str.upper())


def _root_errors_from_result(field_results: list[RootCheckField]) -> list[str]:
    errors: list[str] = []
    for item in field_results:
        if item.valid:
            continue
        segments = ", ".join(item.invalid_segments)
        suffix = f"，建议 {item.suggested_name}" if item.suggested_name else ""
        errors.append(f"字段 '{item.field_name}' 词根不合规：未知词根段 [{segments}]{suffix}")
    return errors


def _check_ddl_structure(ddl_text: str) -> DdlCheckResult:
    """结构/命名/类型/分区检查（不含词根）。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not ddl_text or not ddl_text.strip():
        return DdlCheckResult(table_name="", passed=False, errors=["DDL 为空"], warnings=[])

    ddl_upper = ddl_text.upper()

    table_match = re.search(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
        ddl_text,
        re.IGNORECASE,
    )
    if not table_match:
        return DdlCheckResult(table_name="", passed=False, errors=["无法解析表名"], warnings=[])

    table_name = table_match.group(1).strip('`"')
    bare_table = table_name.split(".")[-1] if "." in table_name else table_name

    layer = _identify_layer(bare_table)
    if layer and layer in _TABLE_NAME_PATTERNS:
        pattern = _TABLE_NAME_PATTERNS[layer]
        if not pattern.match(bare_table.lower()):
            warnings.append(f"表名 '{bare_table}' 不符合 {layer} 层命名规范")

    has_drop = "DROP TABLE IF EXISTS" in ddl_upper
    has_create = "CREATE TABLE" in ddl_upper
    has_if_not_exists = "IF NOT EXISTS" in ddl_upper

    if not has_drop:
        warnings.append("缺少 'drop table if exists' 语句")
    if not has_create:
        errors.append("缺少 'create table' 语句")
    if has_if_not_exists:
        warnings.append("DDL 包含 'if not exists'，规范建议不加")

    has_lifecycle = "LIFECYCLE" in ddl_upper
    if has_lifecycle and layer in ("ODS", "DWD", "DWS", "DMR", "DIM"):
        errors.append(f"{layer} 层表不应设置 LIFECYCLE（应永久保存）")

    columns = _extract_columns(ddl_text)

    for col in columns:
        if col["name"].lower() in _SKIP_FIELD_NAMES:
            continue

        expected_type = _infer_expected_type(col["name"])
        actual_type = _normalize_type(col["type"])
        expected_normalized = _normalize_type(expected_type)

        if actual_type != expected_normalized:
            if expected_type == "string" and actual_type in ("STRING", "VARCHAR", "TEXT"):
                continue
            if expected_type == "bigint" and actual_type in ("BIGINT", "INT", "INTEGER"):
                continue
            warnings.append(
                f"字段 '{col['name']}' 类型 '{col['type']}' "
                f"可能不符合规范（期望 '{expected_type}'）"
            )

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


def check_ddl(ddl_text: str) -> DdlCheckResult:
    """同步 DDL 检查（结构/类型/分区，不含线上词根）。"""
    return _check_ddl_structure(ddl_text)


async def check_ddl_async(ddl_text: str) -> DdlCheckResult:
    """异步 DDL 检查：结构规范 + MCP 线上词根表校验。"""
    result = _check_ddl_structure(ddl_text)
    if not result.table_name:
        return result

    field_names = [
        col["name"]
        for col in _extract_columns(ddl_text)
        if col["name"].lower() not in _SKIP_FIELD_NAMES
    ]
    if not field_names:
        return result

    from dataworks_agent.modeling.root_checker import RootChecker

    root_result: RootCheckResult = await RootChecker().check_fields(field_names)
    root_errors = _root_errors_from_result(root_result.field_results)

    warnings = list(result.warnings)
    if root_result.source == "online":
        warnings.insert(0, "词根校验来源：线上词根表 dim_pub_column_dictionary_static（MCP 实时查询）")
    else:
        warnings.insert(
            0,
            "词根校验已降级为本地字典（MCP/线上词根表不可用，结果可能滞后于线上）",
        )

    errors = list(result.errors) + root_errors
    return replace(
        result,
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        root_source=root_result.source,
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

        is_meta_line = line.upper().startswith(("COMMENT", "LIFECYCLE", "STORED", "TBLPROPERTIES"))
        if is_meta_line:
            continue

        if in_columns and not in_partitions:
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
    """同步检查 DDL 并返回结果字典（不含线上词根）。"""
    result = check_ddl(ddl_text)
    return _ddl_result_to_dict(result)


async def check_ddl_text_async(ddl_text: str) -> dict:
    """异步检查 DDL 并返回结果字典（含线上词根）。"""
    result = await check_ddl_async(ddl_text)
    return _ddl_result_to_dict(result)


def _ddl_result_to_dict(result: DdlCheckResult) -> dict:
    payload = {
        "table_name": result.table_name,
        "passed": result.passed,
        "errors": result.errors,
        "warnings": result.warnings,
    }
    if result.root_source:
        payload["root_source"] = result.root_source
    return payload
