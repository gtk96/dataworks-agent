"""任务接力器单元测试 — Loop Engineering Self-prompting。"""

import pytest

from dataworks_agent.task_engine.task_chainer import ChainingDecision, ChainingRule, TaskChainer


@pytest.fixture
def chainer():
    """创建接力器实例。"""
    return TaskChainer()


def test_load_default_rules(chainer):
    """加载默认接力规则。"""
    rules = chainer.get_rules()
    assert len(rules) > 0

    # 检查 ODS 规则
    ods_rules = [r for r in rules if "ods" in r.trigger_task_type]
    assert len(ods_rules) > 0


def test_on_task_complete_no_match(chainer):
    """任务完成但无匹配规则。"""
    decisions = chainer.on_task_complete(
        task_id="task_001",
        task_type="unknown_type",
        status="verified",
    )
    assert len(decisions) == 0


def test_on_task_complete_match_ods(chainer):
    """ODS 节点创建完成触发接力。"""
    decisions = chainer.on_task_complete(
        task_id="task_002",
        task_type="ods_node_create",
        status="verified",
    )

    assert len(decisions) == 1
    assert decisions[0].next_task_type == "dml_push"
    assert decisions[0].trigger_task_id == "task_002"


def test_on_task_complete_wrong_status(chainer):
    """任务完成但状态不匹配。"""
    decisions = chainer.on_task_complete(
        task_id="task_003",
        task_type="ods_node_create",
        status="failed",  # 不是 verified
    )
    assert len(decisions) == 0


def test_on_task_complete_disabled_rule(chainer):
    """任务完成但规则已禁用。"""
    chainer.disable_rule("ods_to_dml")

    decisions = chainer.on_task_complete(
        task_id="task_004",
        task_type="ods_node_create",
        status="verified",
    )
    assert len(decisions) == 0


def test_enable_disable_rule(chainer):
    """启用/禁用接力规则。"""
    # 禁用
    assert chainer.disable_rule("ods_to_dml") is True
    rule = next(r for r in chainer.get_rules() if r.id == "ods_to_dml")
    assert rule.enabled is False

    # 启用
    assert chainer.enable_rule("ods_to_dml") is True
    rule = next(r for r in chainer.get_rules() if r.id == "ods_to_dml")
    assert rule.enabled is True


def test_enable_nonexistent_rule(chainer):
    """启用不存在的规则。"""
    assert chainer.enable_rule("nonexistent") is False


def test_disable_nonexistent_rule(chainer):
    """禁用不存在的规则。"""
    assert chainer.disable_rule("nonexistent") is False


def test_on_task_complete_dwd(chainer):
    """DWD 节点创建完成触发接力。"""
    decisions = chainer.on_task_complete(
        task_id="task_005",
        task_type="dwd_node_create",
        status="verified",
    )

    assert len(decisions) == 1
    assert decisions[0].next_task_type == "dml_push"


def test_on_task_complete_dim(chainer):
    """DIM 节点创建完成触发接力。"""
    decisions = chainer.on_task_complete(
        task_id="task_006",
        task_type="dim_node_create",
        status="verified",
    )

    assert len(decisions) == 1
    assert decisions[0].next_task_type == "dml_push"


def test_on_task_complete_dws(chainer):
    """DWS 节点创建完成触发接力。"""
    decisions = chainer.on_task_complete(
        task_id="task_007",
        task_type="dws_node_create",
        status="verified",
    )

    assert len(decisions) == 1
    assert decisions[0].next_task_type == "dml_push"


def test_chaining_rule_dataclass():
    """ChainingRule 数据结构。"""
    rule = ChainingRule(
        id="test_rule",
        trigger_task_type="test_trigger",
        trigger_status="verified",
        next_task_type="test_next",
        description="测试规则",
        enabled=True,
    )

    assert rule.id == "test_rule"
    assert rule.enabled is True


def test_chaining_decision_dataclass():
    """ChainingDecision 数据结构。"""
    decision = ChainingDecision(
        rule_id="test_rule",
        trigger_task_id="task_001",
        trigger_task_type="test_trigger",
        next_task_type="test_next",
        description="测试决策",
        executed=False,
        reason="匹配规则",
    )

    assert decision.rule_id == "test_rule"
    assert decision.executed is False
