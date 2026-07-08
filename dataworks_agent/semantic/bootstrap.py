"""Standards_Bundle 导入 bootstrap — 将规范落库为语义规则。

实现 Requirement 10.7：从 Standards_Bundle 导入初始语义规则。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STANDARDS_DIR = Path(__file__).resolve().parent.parent / "standards"
_WAREHOUSE_DIR = _STANDARDS_DIR.parent / "warehouse"


def load_warehouse_yaml() -> dict[str, Any]:
    """加载 warehouse/*.yaml 规范。"""
    import yaml

    result: dict[str, Any] = {}

    if not _WAREHOUSE_DIR.exists():
        logger.warning("warehouse 目录不存在: %s", _WAREHOUSE_DIR)
        return result

    for yaml_file in _WAREHOUSE_DIR.glob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    result[yaml_file.stem] = data
        except Exception as e:
            logger.warning("加载 YAML 失败: %s: %s", yaml_file, e)

    return result


def load_steering_documents() -> dict[str, str]:
    """加载 standards/steering/*.md 规范文档。"""
    steering_dir = _STANDARDS_DIR / "steering"
    result: dict[str, str] = {}

    if not steering_dir.exists():
        logger.warning("steering 目录不存在: %s", steering_dir)
        return result

    for md_file in steering_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            result[md_file.stem] = content
        except Exception as e:
            logger.warning("加载 MD 失败: %s: %s", md_file, e)

    return result


def load_word_roots() -> list[dict[str, Any]]:
    """加载词根字典。"""
    from dataworks_agent.standards.loader import load_word_root_entries

    return load_word_root_entries()


def parse_warehouse_rules(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """解析 warehouse YAML 为语义规则。"""
    rules: dict[str, dict[str, Any]] = {}

    # 分层引用规则
    if "layers" in data and isinstance(data["layers"], dict):
        for layer_name, layer_config in data["layers"].items():
            rules[f"layer_{layer_name}"] = {
                "type": "layer_reference",
                "layer": layer_name,
                "config": layer_config,
            }

    # 主题域
    if "domains" in data and isinstance(data["domains"], dict):
        for domain_name, domain_config in data["domains"].items():
            rules[f"domain_{domain_name}"] = {
                "type": "domain",
                "name": domain_name,
                "config": domain_config,
            }

    # 更新方式（可能是列表或字典）
    if "update_modes" in data:
        update_modes = data["update_modes"]
        if isinstance(update_modes, dict):
            for mode_name, mode_config in update_modes.items():
                rules[f"update_mode_{mode_name}"] = {
                    "type": "update_mode",
                    "name": mode_name,
                    "config": mode_config,
                }
        elif isinstance(update_modes, list):
            for idx, mode_config in enumerate(update_modes):
                mode_name = (
                    mode_config.get("name", f"mode_{idx}")
                    if isinstance(mode_config, dict)
                    else f"mode_{idx}"
                )
                rules[f"update_mode_{mode_name}"] = {
                    "type": "update_mode",
                    "name": mode_name,
                    "config": mode_config,
                }

    # 类型映射
    if "type_mappings" in data and isinstance(data["type_mappings"], dict):
        for mapping_name, mapping_config in data["type_mappings"].items():
            rules[f"type_mapping_{mapping_name}"] = {
                "type": "type_mapping",
                "name": mapping_name,
                "config": mapping_config,
            }

    return rules


def parse_steering_rules(doc_id: str, content: str) -> dict[str, dict[str, Any]]:
    """解析 steering MD 文档为语义规则。"""
    rules: dict[str, dict[str, Any]] = {}

    # 简单解析：提取标题和内容块
    sections = re.split(r"\n##\s+", content)

    for section in sections[1:] if len(sections) > 1 else []:
        lines = section.strip().split("\n")
        if lines:
            title = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            rule_key = f"{doc_id}_{title.lower().replace(' ', '_')}"
            rules[rule_key] = {
                "type": "steering_rule",
                "document": doc_id,
                "title": title,
                "content": body,
            }

    return rules


def bootstrap_semantic_layer() -> int:
    """从 Standards_Bundle 导入初始语义规则到语义层。"""
    from dataworks_agent.semantic.layer import SemanticLayer

    layer = SemanticLayer()
    count = 0

    # 1. 导入 warehouse YAML 规则
    logger.info("导入 warehouse YAML 规则...")
    warehouse_data = load_warehouse_yaml()
    for _file_key, data in warehouse_data.items():
        rules = parse_warehouse_rules(data)
        for rule_key, rule_body in rules.items():
            try:
                layer.upsert_definition(
                    kind="rule",
                    key=rule_key,
                    body=rule_body,
                    actor="bootstrap",
                    source="standards_bundle",
                )
                count += 1
            except Exception as e:
                logger.warning("导入规则失败: %s: %s", rule_key, e)

    # 2. 导入 steering MD 规则
    logger.info("导入 steering MD 规则...")
    steering_docs = load_steering_documents()
    for doc_id, content in steering_docs.items():
        rules = parse_steering_rules(doc_id, content)
        for rule_key, rule_body in rules.items():
            try:
                layer.upsert_definition(
                    kind="rule",
                    key=rule_key,
                    body=rule_body,
                    actor="bootstrap",
                    source="standards_bundle",
                )
                count += 1
            except Exception as e:
                logger.warning("导入规则失败: %s: %s", rule_key, e)

    # 3. 导入词根
    logger.info("导入词根字典...")
    word_roots = load_word_roots()
    for entry in word_roots:
        try:
            layer.upsert_definition(
                kind="root",
                key=entry["column_name"],
                body={
                    "column_name": entry["column_name"],
                    "column_desc": entry.get("column_desc", ""),
                    "is_digit": entry.get("is_digit", False),
                },
                actor="bootstrap",
                source="standards_bundle",
            )
            count += 1
        except Exception as e:
            logger.warning("导入词根失败: %s: %s", entry.get("column_name"), e)

    logger.info("Standards_Bundle 导入完成: %d 条规则", count)
    return count
