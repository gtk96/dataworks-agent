"""Semantic Bootstrap 单元测试 — Standards_Bundle 导入。"""

from dataworks_agent.semantic.bootstrap import (
    bootstrap_semantic_layer,
    load_warehouse_yaml,
    load_word_roots,
    parse_warehouse_rules,
)


def test_load_warehouse_yaml():
    """加载 warehouse YAML。"""
    data = load_warehouse_yaml()
    assert isinstance(data, dict)
    # 可能为空（如果没有 warehouse 目录）


def test_load_word_roots():
    """加载词根字典。"""
    roots = load_word_roots()
    assert isinstance(roots, list)


def test_parse_warehouse_rules():
    """解析 warehouse YAML 为规则。"""
    test_data = {
        "layers": {"DWD": {"description": "明细层"}},
        "domains": {"ord": {"description": "订单域"}},
        "update_modes": {"day": {"description": "日增量"}},
    }

    rules = parse_warehouse_rules(test_data)
    assert "layer_DWD" in rules
    assert "domain_ord" in rules
    assert "update_mode_day" in rules
    assert rules["layer_DWD"]["type"] == "layer_reference"


def test_bootstrap_semantic_layer():
    """bootstrap 语义层。"""
    count = bootstrap_semantic_layer()
    assert count >= 0  # 可能为 0（如果没有规范文件）


def test_bootstrap_multiple_runs():
    """bootstrap 多次运行 — 可以重复运行。"""
    count1 = bootstrap_semantic_layer()
    count2 = bootstrap_semantic_layer()
    # 两次都应该成功运行
    assert count1 >= 0
    assert count2 >= 0
