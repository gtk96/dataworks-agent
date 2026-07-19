"""进化集成器 — 将进化模块接入 AutonomousAgent 的决策循环。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class EvolutionIntegrator:
    """连接进化模块与 AutonomousAgent 的桥梁。

    职责：
    1. 任务完成后自动存储 episode 并触发反思
    2. 任务规划前加载相关学习规则，增强 planning
    3. 提供学习报告 API

    设计为可选集成：不改变 AutonomousAgent 的核心接口。
    """

    def __init__(
        self,
        agent: Any,
        memory: Any,
        reflection_engine: Any,
        learning_store: Any,
        strategy_optimizer: Any,
    ) -> None:
        self._agent = agent
        self._memory = memory
        self._reflection_engine = reflection_engine
        self._learning_store = learning_store
        self._strategy_optimizer = strategy_optimizer

    async def after_task_completion(self, task: Any) -> None:
        """任务完成后：存储 episode → 触发反思 → 更新学习规则。

        Args:
            task: AutonomousTask 实例（已完成执行与验证）。
        """
        try:
            start_time = datetime.now(UTC)
            duration = (
                (start_time - task.created_at).total_seconds()
                if hasattr(task, "created_at")
                else 0.0
            )

            # 若 task 已有 duration_seconds 则使用实际值
            if hasattr(task, "duration_seconds") and task.duration_seconds > 0:
                duration = task.duration_seconds

            execution_log = []
            for sr in task.step_results or []:
                execution_log.append(
                    {
                        "step": sr.step,
                        "status": sr.status,
                        "error": sr.error,
                        "duration_ms": sr.duration_ms,
                        "details": sr.details,
                    }
                )

            from dataworks_agent.evolution.memory import ExecutionEpisode

            episode = ExecutionEpisode(
                episode_id=f"ep_{task.id}",
                task_type=task.task_type.value
                if hasattr(task.task_type, "value")
                else str(task.task_type),
                intent=task.description,
                params=task.params or {},
                plan_steps=task.plan or [],
                execution_log=execution_log,
                final_status=task.status.value
                if hasattr(task.status, "value")
                else str(task.status),
                verification_result=task.verification_result,
                error_message=task.error_message,
                duration_seconds=duration,
                created_at=datetime.now(UTC),
            )

            await self._memory.store_episode(episode)
            logger.info("Episode stored for task %s", task.id)

            # 触发反思
            reflection = await self._reflection_engine.reflect_on_episode(episode)

            # 根据反思结果生成/更新学习规则
            await self._update_rules_from_reflection(reflection, episode.episode_id)

            # 更新已有规则的置信度
            if reflection.success:
                await self._reward_matching_rules(episode.task_type, positive=True)
            else:
                await self._reward_matching_rules(episode.task_type, positive=False)

        except Exception as exc:
            logger.exception(
                "After-task evolution processing failed for %s: %s", getattr(task, "id", "?"), exc
            )

    async def before_task_planning(self, intent: str, params: dict[str, Any]) -> dict[str, Any]:
        """任务规划前：加载相关学习规则，返回增强上下文。

        Returns:
            {
                "enhanced_params": {...},
                "planning_hints": [...],
                "risk_assessment": {...},
            }
        """
        try:
            # 预测成功率
            task_type_guess = self._guess_task_type(intent, params)
            probability = 0.5
            if task_type_guess:
                probability = await self._strategy_optimizer.predict_success_probability(
                    task_type_guess, params
                )

            # 推荐参数
            param_recommendation = {}
            if task_type_guess:
                param_recommendation = await self._strategy_optimizer.recommend_parameters(
                    task_type_guess, params
                )

            # 加载相关规则
            rules = await self._learning_store.get_rules()
            high_confidence_rules = [r for r in rules if r.confidence >= 0.7]

            planning_hints = []
            for rule in high_confidence_rules:
                planning_hints.append(f"[{rule.rule_type}] {rule.condition} → {rule.action}")

            risk_level = "low"
            if probability < 0.4:
                risk_level = "high"
            elif probability < 0.7:
                risk_level = "medium"

            return {
                "task_type_hint": task_type_guess,
                "success_probability": round(probability, 3),
                "risk_level": risk_level,
                "enhanced_params": param_recommendation.get("recommended_params", params),
                "planning_hints": planning_hints,
                "warnings": param_recommendation.get("warnings", []),
            }
        except Exception as exc:
            logger.warning("Before-planning evolution enrichment failed: %s", exc)
            return {"task_type_hint": None, "success_probability": 0.5, "risk_level": "unknown"}

    async def get_learning_summary(self) -> dict[str, Any]:
        """获取学习报告。"""
        try:
            all_episodes = await self._memory.get_episodes()
            all_rules = await self._learning_store.get_rules()

            success_count = sum(1 for ep in all_episodes if ep.final_status == "verified")
            failure_count = sum(1 for ep in all_episodes if ep.final_status == "failed")

            avg_confidence = (
                sum(r.confidence for r in all_rules) / len(all_rules) if all_rules else 0.0
            )

            rules_by_type: dict[str, int] = {}
            for rule in all_rules:
                rules_by_type[rule.rule_type] = rules_by_type.get(rule.rule_type, 0) + 1

            return {
                "total_episodes": len(all_episodes),
                "success_count": success_count,
                "failure_count": failure_count,
                "success_rate": round(success_count / max(len(all_episodes), 1), 3),
                "total_rules": len(all_rules),
                "avg_confidence": round(avg_confidence, 3),
                "rules_by_type": rules_by_type,
                "high_confidence_rules": sum(1 for r in all_rules if r.confidence >= 0.7),
            }
        except Exception as exc:
            logger.exception("Failed to generate learning summary")
            return {"error": str(exc)}

    async def _update_rules_from_reflection(self, reflection: Any, episode_id: str) -> None:
        """根据反思结果创建或更新学习规则。"""
        from dataworks_agent.evolution.learning_store import LearnedRule

        # 失败根因 → execution 类规则
        for cause in reflection.failure_root_causes:
            rule_id = f"rule_fail_{cause[:30].replace(' ', '_')}_{episode_id[:8]}"
            rule = LearnedRule(
                rule_id=rule_id,
                rule_type="execution",
                condition=f"失败模式: {cause}",
                action="增加预检查或重试机制",
                confidence=0.6,
                source_episode_ids=[episode_id],
            )
            await self._learning_store.add_rule(rule)

        # 改进建议 → planning 类规则
        for suggestion in reflection.improvement_suggestions:
            rule_id = f"rule_improve_{suggestion[:30].replace(' ', '_')}_{episode_id[:8]}"
            rule = LearnedRule(
                rule_id=rule_id,
                rule_type="planning",
                condition=suggestion[:100],
                action="在规划阶段考虑此因素",
                confidence=0.5,
                source_episode_ids=[episode_id],
            )
            await self._learning_store.add_rule(rule)

        # 成功经验 → verification 类规则
        for obs in reflection.key_observations:
            if "成功" in obs or "有效" in obs:
                rule_id = f"rule_success_{obs[:30].replace(' ', '_')}_{episode_id[:8]}"
                rule = LearnedRule(
                    rule_id=rule_id,
                    rule_type="verification",
                    condition=obs[:100],
                    action="复用此成功经验",
                    confidence=0.7,
                    source_episode_ids=[episode_id],
                )
                await self._learning_store.add_rule(rule)

    async def _reward_matching_rules(self, task_type: str, positive: bool) -> None:
        """根据任务结果调整相关规则的置信度。"""
        rules = await self._learning_store.get_rules()
        for rule in rules:
            try:
                if positive:
                    await self._learning_store.increment_success_count(rule.rule_id)
                else:
                    await self._learning_store.increment_failure_count(rule.rule_id)
            except Exception as exc:
                logger.warning("Failed to update rule confidence for %s: %s", rule.rule_id, exc)

    @staticmethod
    def _guess_task_type(intent: str, params: dict[str, Any]) -> str | None:
        """从意图和参数中猜测任务类型。"""
        lower_intent = intent.lower()
        target = str(params.get("target_table") or params.get("table_name") or "")

        if "dwd" in lower_intent or target.lower().startswith("dwd_"):
            return "create_dwd"
        if "ods" in lower_intent or target.lower().startswith("ods_"):
            return "create_ods"
        if any(kw in lower_intent for kw in ("修改", "modify", "change")):
            return "modify_task"
        if any(kw in lower_intent for kw in ("调度", "schedule", "cron")):
            return "configure_schedule"
        if any(kw in lower_intent for kw in ("依赖", "dependency", "upstream")):
            return "configure_dependency"
        return None
