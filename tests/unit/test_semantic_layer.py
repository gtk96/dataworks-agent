"""SemanticLayer 单元测试 — 语义层单一事实源。"""

import uuid

import pytest

from dataworks_agent.semantic.layer import (
    QualitySignal,
    SemanticLayer,
)


@pytest.fixture
def layer():
    """创建 SemanticLayer 实例。"""
    return SemanticLayer()


def _unique_key() -> str:
    """生成唯一 key。"""
    return f"metric_{uuid.uuid4().hex[:8]}"


def test_get_metric_definition_not_found(layer):
    """获取不存在的指标定义。"""
    result = layer.get_metric_definition("nonexistent_metric")
    assert result is None


def test_resolve_caliber_not_found(layer):
    """口径澄清 — 未找到定义。"""
    result = layer.resolve_caliber("nonexistent_metric")
    assert result.resolved is False
    assert result.definition is None


def test_upsert_definition_create(layer):
    """创建新的语义定义。"""
    key = _unique_key()
    defn = layer.upsert_definition(
        kind="metric",
        key=key,
        body={"description": "订单数量", "type": "count"},
        actor="test_user",
    )

    assert defn.def_id.startswith("sem_")
    assert defn.kind == "metric"
    assert defn.key == key
    assert defn.version == 1
    assert defn.status == "draft"


def test_upsert_definition_no_change(layer):
    """更新语义定义但无实质性变更。"""
    key = _unique_key()

    # 创建
    defn1 = layer.upsert_definition(
        kind="metric",
        key=key,
        body={"description": "订单数量"},
        actor="test_user",
    )

    # 批准
    layer.approve_definition(defn1.def_id)

    # 无变更更新
    defn2 = layer.upsert_definition(
        kind="metric",
        key=key,
        body={"description": "订单数量"},
        actor="test_user",
    )

    assert defn2.def_id == defn1.def_id
    assert defn2.version == 1


def test_upsert_definition_with_change(layer):
    """更新语义定义有实质性变更。"""
    key = _unique_key()

    # 创建
    defn1 = layer.upsert_definition(
        kind="metric",
        key=key,
        body={"description": "订单数量"},
        actor="test_user",
    )

    # 批准
    layer.approve_definition(defn1.def_id)

    # 有变更更新
    defn2 = layer.upsert_definition(
        kind="metric",
        key=key,
        body={"description": "订单数量（新版）"},
        actor="test_user",
    )

    assert defn2.def_id != defn1.def_id
    assert defn2.version == 2


def test_approve_definition(layer):
    """批准语义定义。"""
    key = _unique_key()
    defn = layer.upsert_definition(
        kind="metric",
        key=key,
        body={"description": "订单数量"},
        actor="test_user",
    )

    assert defn.status == "draft"

    result = layer.approve_definition(defn.def_id)
    assert result is True

    # 验证已批准
    approved = layer.get_metric_definition(key)
    assert approved is not None
    assert approved.status == "approved"


def test_approve_nonexistent(layer):
    """批准不存在的定义。"""
    result = layer.approve_definition("nonexistent_id")
    assert result is False


def test_get_quality_signal(layer):
    """获取质量信号。"""
    signal = layer.get_quality_signal("test_table")
    assert isinstance(signal, QualitySignal)
    assert signal.table_name == "test_table"


def test_list_definitions(layer):
    """列出语义定义。"""
    key1 = _unique_key()
    key2 = _unique_key()
    key3 = _unique_key()

    # 创建几个定义
    layer.upsert_definition(kind="metric", key=key1, body={})
    layer.upsert_definition(kind="metric", key=key2, body={})
    layer.upsert_definition(kind="caliber", key=key3, body={})

    # 按 kind 过滤
    metrics = layer.list_definitions(kind="metric")
    # 检查新创建的 key 存在
    metric_keys = [m.key for m in metrics]
    assert key1 in metric_keys
    assert key2 in metric_keys

    # 检查新创建的 kind 存在
    calibers = layer.list_definitions(kind="caliber")
    caliber_keys = [c.key for c in calibers]
    assert key3 in caliber_keys
