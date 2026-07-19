"""进化模块 API 路由 — episodes / rules / reflection / optimization。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


def _get_evolution_components():
    """延迟导入并构建进化模块组件实例。"""
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.evolution.learning_store import LearningStore
    from dataworks_agent.evolution.memory import EpisodicMemory
    from dataworks_agent.evolution.reflection import ReflectionEngine
    from dataworks_agent.evolution.strategy_optimizer import StrategyOptimizer

    memory = EpisodicMemory(SessionLocal)
    learning_store = LearningStore(SessionLocal)
    reflection_engine = ReflectionEngine()
    strategy_optimizer = StrategyOptimizer(memory, learning_store)
    return memory, learning_store, reflection_engine, strategy_optimizer


@router.get("/episodes")
async def list_episodes(
    task_type: str | None = None,
    status: str | None = None,
) -> dict:
    """列出情景记忆 episode，支持按任务类型和状态过滤。"""
    try:
        memory, _, _, _ = _get_evolution_components()
        episodes = await memory.get_episodes(task_type=task_type, status=status)
        return {
            "success": True,
            "episodes": [ep.to_dict() for ep in episodes],
            "count": len(episodes),
        }
    except Exception as exc:
        logger.exception("Failed to list episodes")
        raise HTTPException(status_code=500, detail=f"获取 episodes 失败：{exc!s}") from exc


@router.get("/episodes/{episode_id}")
async def get_episode(episode_id: str) -> dict:
    """获取单个 episode 详情。"""
    try:
        memory, _, _, _ = _get_evolution_components()
        episode = await memory.get_episode(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail=f"Episode not found: {episode_id}")
        return {"success": True, "episode": episode.to_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get episode %s", episode_id)
        raise HTTPException(status_code=500, detail=f"获取 episode 失败：{exc!s}") from exc


@router.post("/reflect/{episode_id}")
async def trigger_reflection(episode_id: str) -> dict:
    """手动触发对指定 episode 的反思。"""
    try:
        memory, _, reflection_engine, _ = _get_evolution_components()
        episode = await memory.get_episode(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail=f"Episode not found: {episode_id}")

        result = await reflection_engine.reflect_on_episode(episode)
        return {
            "success": True,
            "reflection": {
                "episode_id": result.episode_id,
                "success": result.success,
                "key_observations": result.key_observations,
                "failure_root_causes": result.failure_root_causes,
                "improvement_suggestions": result.improvement_suggestions,
                "confidence": result.confidence,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to reflect on episode %s", episode_id)
        raise HTTPException(status_code=500, detail=f"反思失败：{exc!s}") from exc


@router.get("/rules")
async def list_rules(rule_type: str | None = None) -> dict:
    """列出学习规则，支持按类型过滤。"""
    try:
        _, learning_store, _, _ = _get_evolution_components()
        rules = await learning_store.get_rules(rule_type=rule_type)
        return {
            "success": True,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "rule_type": r.rule_type,
                    "condition": r.condition,
                    "action": r.action,
                    "confidence": r.confidence,
                    "source_episode_ids": r.source_episode_ids,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    "updated_at": r.updated_at.isoformat() if r.updated_at else "",
                }
                for r in rules
            ],
            "count": len(rules),
        }
    except Exception as exc:
        logger.exception("Failed to list rules")
        raise HTTPException(status_code=500, detail=f"获取 rules 失败：{exc!s}") from exc


@router.get("/summary")
async def get_learning_summary() -> dict:
    """获取学习报告摘要。"""
    try:
        from dataworks_agent.evolution.integrator import EvolutionIntegrator

        memory, learning_store, _, strategy_optimizer = _get_evolution_components()
        integrator = EvolutionIntegrator(
            agent=None,
            memory=memory,
            reflection_engine=None,
            learning_store=learning_store,
            strategy_optimizer=strategy_optimizer,
        )
        summary = await integrator.get_learning_summary()
        return {"success": True, **summary}
    except Exception as exc:
        logger.exception("Failed to get learning summary")
        raise HTTPException(status_code=500, detail=f"获取学习摘要失败：{exc!s}") from exc


@router.post("/optimize")
async def run_optimization(body: dict) -> dict:
    """运行策略优化分析。"""
    task_type = body.get("task_type", "")
    if not task_type:
        raise HTTPException(status_code=422, detail="task_type is required")
    try:
        _memory, _learning_store, _, strategy_optimizer = _get_evolution_components()

        planning = await strategy_optimizer.optimize_planning_strategy(task_type)
        execution_order = await strategy_optimizer.optimize_execution_order(task_type)
        parameters = await strategy_optimizer.recommend_parameters(task_type, {})

        return {
            "success": True,
            "task_type": task_type,
            "planning_strategy": planning,
            "execution_order": execution_order,
            "parameter_recommendation": parameters,
        }
    except Exception as exc:
        logger.exception("Failed to run optimization for %s", task_type)
        raise HTTPException(status_code=500, detail=f"优化失败：{exc!s}") from exc
