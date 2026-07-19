"""策略优化器 — 基于历史数据优化 planning 和执行策略。"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    """从情景记忆和学习规则中提取可执行的优化建议。

    Args:
        memory: EpisodicMemory 实例，用于查询历史案例。
        learning_store: LearningStore 实例，用于获取学习规则。
    """

    def __init__(self, memory: Any, learning_store: Any) -> None:
        self._memory = memory
        self._learning_store = learning_store

    async def optimize_planning_strategy(self, task_type: str) -> dict[str, Any]:
        """根据历史成功案例优化规划策略。

        Returns:
            {
                "recommended_steps": [...],
                "skippable_steps": [...],
                "additional_checks": [...],
                "confidence": 0.0-1.0,
            }
        """
        success_episodes = await self._memory.get_success_patterns(task_type)
        failure_episodes = await self._memory.get_failure_patterns(task_type)

        if not success_episodes and not failure_episodes:
            return {
                "recommended_steps": [],
                "skippable_steps": [],
                "additional_checks": [],
                "confidence": 0.0,
                "message": "暂无历史数据",
            }

        # 分析成功步骤频率
        step_frequency: dict[str, int] = defaultdict(int)
        for ep in success_episodes:
            for step in ep.plan_steps or []:
                step_name = step.get("step", "")
                if step_name:
                    step_frequency[step_name] += 1

        total_success = len(success_episodes)
        recommended_steps = [
            name
            for name, count in sorted(step_frequency.items(), key=lambda x: -x[1])
            if count / max(total_success, 1) >= 0.5
        ]

        # 分析失败模式以识别需要额外检查的步骤
        additional_checks: list[str] = []
        failure_step_counts: dict[str, int] = defaultdict(int)
        for ep in failure_episodes:
            for entry in ep.execution_log or []:
                if (entry.get("status") or "").lower() in ("failed", "error"):
                    step_name = entry.get("step", "")
                    if step_name:
                        failure_step_counts[step_name] += 1

        for step_name, count in failure_step_counts.items():
            if count >= 2:
                additional_checks.append(
                    f"步骤 '{step_name}' 在 {count} 个失败案例中出现，建议增加预检查"
                )

        # 识别可跳过的步骤
        skippable_steps = [
            "verify"  # 验证步骤由 verifier 统一处理，可在优化计划中标记为可选
        ]

        confidence = self._compute_strategy_confidence(len(success_episodes), len(failure_episodes))

        return {
            "recommended_steps": recommended_steps,
            "skippable_steps": skippable_steps,
            "additional_checks": additional_checks,
            "confidence": round(confidence, 3),
            "success_count": total_success,
            "failure_count": len(failure_episodes),
        }

    async def optimize_execution_order(self, task_type: str) -> list[dict[str, Any]]:
        """根据历史数据推荐执行步骤顺序。

        Returns:
            按推荐优先级排序的步骤列表。
        """
        success_episodes = await self._memory.get_success_patterns(task_type)

        if not success_episodes:
            return []

        # 统计步骤间的共现关系
        step_cooccurrence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for ep in success_episodes:
            steps = [s.get("step", "") for s in (ep.plan_steps or []) if s.get("step")]
            for i, step_a in enumerate(steps):
                for step_b in steps[i + 1 :]:
                    step_cooccurrence[step_a][step_b] += 1
                    step_cooccurrence[step_b][step_a] += 1

        # 构建有向图：频繁共现的步骤倾向于相邻
        step_names = list({name for d in step_cooccurrence.values() for name in d})

        if not step_names:
            return []

        # 简单排序：按共现度降序
        scored_steps = []
        for step_name in step_names:
            neighbors = step_cooccurrence[step_name]
            total_cooccurrence = sum(neighbors.values())
            scored_steps.append(
                {
                    "step": step_name,
                    "priority": round(total_cooccurrence / max(len(success_episodes), 1), 2),
                    "connected_to": list(neighbors.keys())[:5],
                }
            )

        scored_steps.sort(key=lambda x: -x["priority"])
        return scored_steps

    async def recommend_parameters(
        self, task_type: str, base_params: dict[str, Any]
    ) -> dict[str, Any]:
        """根据历史成功案例推荐参数调整。

        Returns:
            {
                "recommended_params": {...},
                "warnings": [...],
                "confidence": 0.0-1.0,
            }
        """
        success_episodes = await self._memory.get_success_patterns(task_type)

        if not success_episodes:
            return {
                "recommended_params": base_params,
                "warnings": ["暂无成功案例数据"],
                "confidence": 0.0,
            }

        # 收集成功案例中的参数分布
        param_values: dict[str, list[Any]] = defaultdict(list)
        for ep in success_episodes:
            params = ep.params or {}
            for k, v in params.items():
                if v is not None and not isinstance(v, (dict, list)):
                    param_values[k].append(v)

        recommendations: dict[str, Any] = {}
        warnings: list[str] = []

        # 对每个参数，推荐最常见的值
        for key, values in param_values.items():
            if not values:
                continue
            from collections import Counter

            counter = Counter(values)
            most_common_value, most_common_count = counter.most_common(1)[0]
            ratio = most_common_count / len(values)

            if ratio >= 0.7:
                recommendations[key] = most_common_value
            else:
                warnings.append(
                    f"参数 '{key}' 在成功案例中分布较分散，当前值 {base_params.get(key)} 需谨慎"
                )

        # 检查 base_params 中缺失的常见参数
        common_keys = set()
        for ep in success_episodes:
            common_keys.update((ep.params or {}).keys())

        missing_common = common_keys - set(base_params.keys())
        for key in missing_common:
            # 找出该键在成功案例中最常见的值
            values = param_values.get(key, [])
            if values:
                from collections import Counter

                recommendations[key] = Counter(values).most_common(1)[0][0]

        confidence = self._compute_parameter_confidence(success_episodes, base_params)

        return {
            "recommended_params": {**base_params, **recommendations},
            "warnings": warnings,
            "confidence": round(confidence, 3),
        }

    async def predict_success_probability(self, task_type: str, params: dict[str, Any]) -> float:
        """预测给定参数的任务成功率。

        Returns:
            0.0-1.0 之间的概率值。
        """
        success_episodes = await self._memory.get_success_patterns(task_type)
        failure_episodes = await self._memory.get_failure_patterns(task_type)
        total = len(success_episodes) + len(failure_episodes)

        if total == 0:
            return 0.5  # 无数据时返回中性概率

        base_probability = len(success_episodes) / total

        # 参数匹配度修正
        param_bonus = self._compute_param_match_bonus(params, success_episodes)
        param_penalty = self._compute_param_failure_penalty(params, failure_episodes)

        probability = base_probability + param_bonus - param_penalty
        return max(0.0, min(1.0, probability))

    def _compute_strategy_confidence(self, success_count: int, failure_count: int) -> float:
        """计算策略优化的置信度。"""
        total = success_count + failure_count
        if total == 0:
            return 0.0
        success_ratio = success_count / total
        data_weight = min(1.0, total / 10.0)  # 10+ 条数据后权重饱和
        return success_ratio * 0.6 + data_weight * 0.4

    def _compute_parameter_confidence(
        self, success_episodes: list[Any], base_params: dict[str, Any]
    ) -> float:
        """计算参数推荐的置信度。"""
        if not success_episodes:
            return 0.0

        matching = 0
        for ep in success_episodes:
            ep_params = ep.params or {}
            if all(ep_params.get(k) == v for k, v in base_params.items() if v is not None):
                matching += 1

        return matching / len(success_episodes)

    def _compute_param_match_bonus(
        self, params: dict[str, Any], success_episodes: list[Any]
    ) -> float:
        """计算参数与成功案例的匹配度带来的正向修正。"""
        if not success_episodes or not params:
            return 0.0

        match_score = 0.0
        for ep in success_episodes:
            ep_params = ep.params or {}
            matches = sum(1 for k, v in params.items() if ep_params.get(k) == v)
            total_keys = max(len(params), len(ep_params))
            match_score += matches / total_keys

        return (match_score / len(success_episodes)) * 0.3

    def _compute_param_failure_penalty(
        self, params: dict[str, Any], failure_episodes: list[Any]
    ) -> float:
        """计算参数与失败案例的匹配度带来的负向修正。"""
        if not failure_episodes or not params:
            return 0.0

        match_score = 0.0
        for ep in failure_episodes:
            ep_params = ep.params or {}
            matches = sum(1 for k, v in params.items() if ep_params.get(k) == v)
            total_keys = max(len(params), len(ep_params))
            match_score += matches / total_keys

        return (match_score / len(failure_episodes)) * 0.2
