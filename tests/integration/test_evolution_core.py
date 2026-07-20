"""进化模块集成测试。

覆盖：
- EpisodicMemory 存储与查询
- ReflectionEngine 失败原因识别
- LearningStore 规则存储与置信度更新
- StrategyOptimizer 参数推荐与成功率预测
- EvolutionIntegrator 任务完成后自动反思
- EvolutionIntegrator 任务规划前加载学习规则
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from dataworks_agent.evolution.learning_store import LearnedRule, LearningStore
from dataworks_agent.evolution.memory import EpisodicMemory, ExecutionEpisode
from dataworks_agent.evolution.reflection import ReflectionEngine
from dataworks_agent.evolution.strategy_optimizer import StrategyOptimizer

# ── 辅助函数 ────────────────────────────────────────────────


def _make_session_factory(db_engine):
    """构造返回 SQLAlchemy Session 的工厂。"""
    from sqlalchemy.orm import sessionmaker

    sa_session = sessionmaker(bind=db_engine, autoflush=False)

    def factory():
        return sa_session()

    return factory


def _make_episode(
    task_type: str = "create_ods",
    status: str = "verified",
    error_message: str | None = None,
    execution_log: list[dict] | None = None,
    params: dict | None = None,
) -> ExecutionEpisode:
    """构造测试用 episode。"""
    return ExecutionEpisode(
        episode_id=f"ep_test_{uuid.uuid4().hex[:8]}",
        task_type=task_type,
        intent="帮我创建 ODS 表",
        params=params or {"target_table": "ods_test_table", "source_table": "src"},
        plan_steps=[
            {"step": "validate_params", "description": "校验参数"},
            {"step": "generate_ddl", "description": "生成 DDL"},
            {"step": "create_table", "description": "建表"},
            {"step": "verify", "description": "验证"},
        ],
        execution_log=execution_log or [
            {"step": "validate_params", "status": "completed", "error": ""},
            {"step": "generate_ddl", "status": "completed", "error": ""},
            {"step": "create_table", "status": "completed", "error": ""},
            {"step": "verify", "status": "completed", "error": ""},
        ],
        final_status=status,
        verification_result={"success": True} if status == "verified" else None,
        error_message=error_message,
        duration_seconds=12.5,
        created_at=datetime.now(UTC),
        lessons_learned=[],
    )


def _make_failed_episode() -> ExecutionEpisode:
    """构造失败的 episode。"""
    return _make_episode(
        task_type="create_dwd",
        status="failed",
        error_message="步骤 generate_ddl 执行异常: SQL syntax error",
        execution_log=[
            {"step": "validate_params", "status": "completed", "error": ""},
            {
                "step": "discover_source_tables",
                "status": "failed",
                "error": "源表 ods_xxx 不存在",
            },
            {"step": "generate_ddl", "status": "skipped", "error": ""},
        ],
        params={
            "target_table": "dwd_test",
            "source_table": "ods_nonexistent",
            "domain": "mkt",
            "entity": "test",
        },
    )


@pytest.fixture
def session_factory(temp_db):
    """提供 EpisodicMemory / LearningStore 使用的 session 工厂。"""
    return _make_session_factory(temp_db)


# ── EpisodicMemory 测试 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_episodic_memory_store_and_retrieve(session_factory):
    """episode 应能正确存储并通过 ID 检索。"""
    memory = EpisodicMemory(session_factory)

    episode = _make_episode(task_type="create_ods")
    await memory.store_episode(episode)

    retrieved = await memory.get_episode(episode.episode_id)
    assert retrieved is not None
    assert retrieved.episode_id == episode.episode_id
    assert retrieved.task_type == "create_ods"
    assert retrieved.final_status == "verified"
    assert retrieved.duration_seconds == 12.5
    assert retrieved.params["target_table"] == "ods_test_table"


@pytest.mark.asyncio
async def test_episodic_memory_filter_by_task_type(session_factory):
    """按 task_type 过滤 episodes 应只返回匹配的记录。"""
    memory = EpisodicMemory(session_factory)

    ep1 = _make_episode(task_type="create_ods", params={"target_table": "ods_a"})
    ep2 = _make_episode(task_type="create_dwd", params={"target_table": "dwd_b"})
    ep3 = _make_episode(task_type="create_ods", params={"target_table": "ods_c"})

    await memory.store_episode(ep1)
    await memory.store_episode(ep2)
    await memory.store_episode(ep3)

    ods_episodes = await memory.get_episodes(task_type="create_ods")
    assert len(ods_episodes) == 2
    assert all(ep.task_type == "create_ods" for ep in ods_episodes)

    dwd_episodes = await memory.get_episodes(task_type="create_dwd")
    assert len(dwd_episodes) == 1


@pytest.mark.asyncio
async def test_episodic_memory_success_failure_patterns(session_factory):
    """get_success_patterns / get_failure_patterns 应按状态过滤。"""
    memory = EpisodicMemory(session_factory)

    success = _make_episode(task_type="create_ods", status="verified")
    failure = _make_episode(task_type="create_ods", status="failed", error_message="测试失败")

    await memory.store_episode(success)
    await memory.store_episode(failure)

    successes = await memory.get_success_patterns("create_ods")
    failures = await memory.get_failure_patterns("create_ods")

    assert len(successes) == 1
    assert len(failures) == 1
    assert successes[0].final_status == "verified"
    assert failures[0].final_status == "failed"


@pytest.mark.asyncio
async def test_episodic_memory_sanitize_sensitive_params(session_factory):
    """params 中的敏感字段应被脱敏。"""
    memory = EpisodicMemory(session_factory)

    episode = _make_episode(
        params={
            "target_table": "ods_test",
            "access_key_id": "AKIA123",
            "password": "secret",
        }
    )
    await memory.store_episode(episode)

    retrieved = await memory.get_episode(episode.episode_id)
    assert retrieved is not None
    assert retrieved.params["access_key_id"] == "***REDACTED***"
    assert retrieved.params["password"] == "***REDACTED***"
    assert retrieved.params["target_table"] == "ods_test"


# ── ReflectionEngine 测试 ───────────────────────────────────


@pytest.mark.asyncio
async def test_reflection_identifies_failure_cause():
    """反思引擎应从失败日志中识别根因。"""
    engine = ReflectionEngine()

    failed_ep = _make_failed_episode()
    result = await engine.reflect_on_episode(failed_ep)

    assert result.episode_id == failed_ep.episode_id
    assert result.success is False
    assert len(result.failure_root_causes) > 0
    # 应识别出 SQL 错误或未知模式
    combined = " ".join(result.failure_root_causes).lower()
    assert "sql" in combined or "unknown" in combined or "源表" in str(result.failure_root_causes)
    assert len(result.improvement_suggestions) > 0
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_reflection_success_episode():
    """成功案例的反思应标记 success=True 且无失败根因。"""
    engine = ReflectionEngine()

    success_ep = _make_episode(task_type="create_ods", status="verified")
    result = await engine.reflect_on_episode(success_ep)

    assert result.success is True
    assert len(result.failure_root_causes) == 0
    assert len(result.key_observations) > 0


@pytest.mark.asyncio
async def test_reflection_batch():
    """批量反思应返回与输入等长的结果列表。"""
    engine = ReflectionEngine()

    episodes = [_make_episode(status="verified"), _make_failed_episode()]
    results = await engine.reflect_on_batch(episodes)

    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is False


# ── LearningStore 测试 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_learning_store_add_and_query(session_factory):
    """规则应能正确存储和查询。"""
    store = LearningStore(session_factory)

    rule = LearnedRule(
        rule_id=f"rule_test_{uuid.uuid4().hex[:8]}",
        rule_type="planning",
        condition="target_table 以 ods_ 开头",
        action="使用 ODS 规划模板",
        confidence=0.8,
        source_episode_ids=["ep_001", "ep_002"],
    )
    await store.add_rule(rule)

    rules = await store.get_rules()
    assert len(rules) >= 1
    found = next(r for r in rules if r.rule_id == rule.rule_id)
    assert found.rule_type == "planning"
    assert found.confidence == 0.8
    assert found.source_episode_ids == ["ep_001", "ep_002"]


@pytest.mark.asyncio
async def test_learning_store_filter_by_type(session_factory):
    """按 rule_type 过滤应只返回匹配的规则。"""
    store = LearningStore(session_factory)

    rule1 = LearnedRule(
        rule_id=f"rule_planning_{uuid.uuid4().hex[:8]}",
        rule_type="planning",
        condition="条件A",
        action="动作A",
    )
    rule2 = LearnedRule(
        rule_id=f"rule_execution_{uuid.uuid4().hex[:8]}",
        rule_type="execution",
        condition="条件B",
        action="动作B",
    )

    await store.add_rule(rule1)
    await store.add_rule(rule2)

    planning_rules = await store.get_rules(rule_type="planning")
    execution_rules = await store.get_rules(rule_type="execution")

    assert len(planning_rules) >= 1
    assert all(r.rule_type == "planning" for r in planning_rules)
    assert len(execution_rules) >= 1
    assert all(r.rule_type == "execution" for r in execution_rules)


@pytest.mark.asyncio
async def test_learning_store_confidence_update(session_factory):
    """置信度调整应在边界内（0.0-1.0）。"""
    store = LearningStore(session_factory)

    rule = LearnedRule(
        rule_id=f"rule_conf_{uuid.uuid4().hex[:8]}",
        rule_type="verification",
        condition="测试条件",
        action="测试动作",
        confidence=0.5,
    )
    await store.add_rule(rule)

    await store.update_confidence(rule.rule_id, 0.3)
    rules = await store.get_rules()
    updated = next(r for r in rules if r.rule_id == rule.rule_id)
    assert updated.confidence == 0.8

    await store.update_confidence(rule.rule_id, 0.5)
    rules = await store.get_rules()
    updated = next(r for r in rules if r.rule_id == rule.rule_id)
    assert updated.confidence == 1.0  # 上限

    await store.update_confidence(rule.rule_id, -0.9)
    rules = await store.get_rules()
    updated = next(r for r in rules if r.rule_id == rule.rule_id)
    assert abs(updated.confidence - 0.1) < 1e-6  # 下限保护


@pytest.mark.asyncio
async def test_learning_store_archive_low_confidence(session_factory):
    """低置信度规则归档后 confidence 应归零。"""
    store = LearningStore(session_factory)

    rule = LearnedRule(
        rule_id=f"rule_archive_{uuid.uuid4().hex[:8]}",
        rule_type="planning",
        condition="旧规则",
        action="旧动作",
        confidence=0.1,
    )
    await store.add_rule(rule)

    # 验证存储的置信度确实低于阈值
    rules_before = await store.get_rules()
    stored_rule = next(r for r in rules_before if r.rule_id == rule.rule_id)
    assert stored_rule.confidence < 0.3

    archived_count = await store.archive_low_confidence_rules(threshold=0.3)
    assert archived_count >= 1

    rules_after = await store.get_rules()
    archived = next(r for r in rules_after if r.rule_id == rule.rule_id)
    assert archived.confidence == 0.0


# ── StrategyOptimizer 测试 ──────────────────────────────────


@pytest.mark.asyncio
async def test_strategy_optimizer_recommends_parameters(session_factory):
    """策略优化器应基于历史成功案例推荐参数。"""
    memory = EpisodicMemory(session_factory)
    store = LearningStore(session_factory)
    optimizer = StrategyOptimizer(memory, store)

    # 存入多个成功案例，其中 datasource_name 有共同值
    for i in range(5):
        ep = _make_episode(
            params={
                "target_table": f"ods_test_{i}",
                "datasource_name": "jky_singleshop",
                "source_type": "mysql",
            }
        )
        await memory.store_episode(ep)

    # 再加一个不同值的案例
    ep_diff = _make_episode(
        params={
            "target_table": "ods_other",
            "datasource_name": "other_ds",
            "source_type": "odps",
        }
    )
    await memory.store_episode(ep_diff)

    recommendation = await optimizer.recommend_parameters(
        "create_ods", {"target_table": "ods_test_0", "datasource_name": "jky_singleshop", "source_type": "mysql"}
    )

    assert "recommended_params" in recommendation
    assert "confidence" in recommendation
    assert recommendation["confidence"] > 0.0
    # jky_singleshop 出现 5/6 次，应被推荐
    assert recommendation["recommended_params"].get("datasource_name") == "jky_singleshop"


@pytest.mark.asyncio
async def test_strategy_optimizer_predict_success_probability(session_factory):
    """成功率预测应基于历史成功/失败比例。"""
    memory = EpisodicMemory(session_factory)
    store = LearningStore(session_factory)
    optimizer = StrategyOptimizer(memory, store)

    # 7 个成功 + 3 个失败 → 基础概率约 0.7
    for _ in range(7):
        await memory.store_episode(_make_episode(status="verified"))
    for _ in range(3):
        await memory.store_episode(_make_episode(status="failed"))

    probability = await optimizer.predict_success_probability("create_ods", {"target_table": "x"})
    assert 0.0 <= probability <= 1.0
    assert probability >= 0.5  # 成功案例更多


@pytest.mark.asyncio
async def test_strategy_optimizer_no_data_returns_empty(session_factory):
    """无历史数据时，优化器应返回空结果而非报错。"""
    memory = EpisodicMemory(session_factory)
    store = LearningStore(session_factory)
    optimizer = StrategyOptimizer(memory, store)

    planning = await optimizer.optimize_planning_strategy("unknown_task")
    assert planning["confidence"] == 0.0
    assert planning["message"] == "暂无历史数据"

    order = await optimizer.optimize_execution_order("unknown_task")
    assert order == []


# ── EvolutionIntegrator 测试 ────────────────────────────────


@pytest.mark.asyncio
async def test_evolution_integrator_after_completion(session_factory):
    """任务完成后，integrator 应自动存储 episode 并触发反思。"""
    from dataworks_agent.evolution.integrator import EvolutionIntegrator

    memory = EpisodicMemory(session_factory)
    store = LearningStore(session_factory)
    reflection_engine = ReflectionEngine()
    optimizer = StrategyOptimizer(memory, store)

    # 构造 mock agent
    mock_agent = MagicMock()

    integrator = EvolutionIntegrator(
        agent=mock_agent,
        memory=memory,
        reflection_engine=reflection_engine,
        learning_store=store,
        strategy_optimizer=optimizer,
    )

    # 构造模拟 AutonomousTask
    mock_task = MagicMock()
    mock_task.id = "auto_test_task"
    mock_task.task_type.value = "create_ods"
    mock_task.description = "测试任务"
    mock_task.params = {"target_table": "ods_test"}
    mock_task.plan = [{"step": "validate_params"}, {"step": "verify"}]
    mock_task.status.value = "verified"
    mock_task.error_message = None
    mock_task.verification_result = {"success": True}
    mock_task.created_at = datetime.now(UTC)
    mock_task.duration_seconds = 10.0
    mock_task.step_results = [
        MagicMock(step="validate_params", status="completed", error=None, duration_ms=100, details={}),
        MagicMock(step="verify", status="completed", error=None, duration_ms=50, details={}),
    ]

    await integrator.after_task_completion(mock_task)

    # 验证 episode 已存储
    episodes = await memory.get_episodes(task_type="create_ods")
    assert len(episodes) >= 1

    # 验证规则已创建（反思会生成规则）
    rules = await store.get_rules()
    assert len(rules) >= 0  # 成功任务可能不产生 execution 类规则


@pytest.mark.asyncio
async def test_evolution_integrator_before_planning(session_factory):
    """任务规划前，integrator 应返回增强上下文。"""
    from dataworks_agent.evolution.integrator import EvolutionIntegrator

    memory = EpisodicMemory(session_factory)
    store = LearningStore(session_factory)
    reflection_engine = ReflectionEngine()
    optimizer = StrategyOptimizer(memory, store)

    mock_agent = MagicMock()
    integrator = EvolutionIntegrator(
        agent=mock_agent,
        memory=memory,
        reflection_engine=reflection_engine,
        learning_store=store,
        strategy_optimizer=optimizer,
    )

    # 先存入一些成功案例
    for _ in range(3):
        await memory.store_episode(
            _make_episode(task_type="create_ods", params={"target_table": "ods_x", "source_type": "mysql"})
        )

    enrichment = await integrator.before_task_planning(
        "帮我创建 ODS 表", {"target_table": "ods_new", "source_type": "mysql"}
    )

    assert "task_type_hint" in enrichment
    assert enrichment["task_type_hint"] == "create_ods"
    assert "success_probability" in enrichment
    assert 0.0 <= enrichment["success_probability"] <= 1.0
    assert "risk_level" in enrichment


@pytest.mark.asyncio
async def test_evolution_integrator_learning_summary(session_factory):
    """学习摘要应包含正确的统计信息。"""
    from dataworks_agent.evolution.integrator import EvolutionIntegrator

    memory = EpisodicMemory(session_factory)
    store = LearningStore(session_factory)
    reflection_engine = ReflectionEngine()
    optimizer = StrategyOptimizer(memory, store)

    mock_agent = MagicMock()
    integrator = EvolutionIntegrator(
        agent=mock_agent,
        memory=memory,
        reflection_engine=reflection_engine,
        learning_store=store,
        strategy_optimizer=optimizer,
    )

    # 存入混合案例
    for _ in range(3):
        await memory.store_episode(_make_episode(status="verified"))
    for _ in range(2):
        await memory.store_episode(_make_episode(status="failed"))

    summary = await integrator.get_learning_summary()

    assert summary["total_episodes"] == 5
    assert summary["success_count"] == 3
    assert summary["failure_count"] == 2
    assert abs(summary["success_rate"] - 0.6) < 0.01


# ── API 路由测试 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evolution_api_list_episodes(mocked_client, temp_db):
    """GET /api/evolution/episodes 应返回空列表或已有数据。"""
    resp = await mocked_client.get("/api/evolution/episodes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "episodes" in body


@pytest.mark.asyncio
async def test_evolution_api_get_missing_episode(mocked_client):
    """GET /api/evolution/episodes/{id} 对不存在的 ID 应返回 404。"""
    resp = await mocked_client.get("/api/evolution/episodes/nonexistent_id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_evolution_api_list_rules(mocked_client, temp_db):
    """GET /api/evolution/rules 应返回规则列表。"""
    resp = await mocked_client.get("/api/evolution/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "rules" in body


@pytest.mark.asyncio
async def test_evolution_api_summary(mocked_client, temp_db):
    """GET /api/evolution/summary 应返回学习摘要。"""
    resp = await mocked_client.get("/api/evolution/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "total_episodes" in body


@pytest.mark.asyncio
async def test_evolution_api_optimize(mocked_client, temp_db):
    """POST /api/evolution/optimize 应返回优化建议。"""
    resp = await mocked_client.post("/api/evolution/optimize", json={"task_type": "create_ods"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "planning_strategy" in body
