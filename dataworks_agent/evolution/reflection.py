"""反思引擎 — 从执行结果中分析、归因并生成改进建议。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    """单次反思的输出。"""

    episode_id: str
    success: bool
    key_observations: list[str] = field(default_factory=list)
    failure_root_causes: list[str] = field(default_factory=list)
    improvement_suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.0


# 失败模式关键词 → 根因分类
_FAILURE_PATTERNS: dict[str, list[str]] = {
    "security": ["安全守卫拦截", "SecurityViolation", "越权", "未授权"],
    "validation": ["校验", "参数缺失", "缺少", "无效", "InvalidParameter", "验证"],
    "api_throttle": ["Throttling", "限流", "429", "RateLimit"],
    "permission_denied": ["403", "Forbidden", "权限", "RAM"],
    "network": ["timeout", "ConnectionError", "网络", "超时"],
    "sql_error": ["SQL", "syntax", "语法错误", "DDL", "DML"],
    "node_not_found": ["not found", "不存在", "404", "NodeNotFound"],
    "directory_error": ["目录层级", "path", "folder", "目录"],
}

_STEP_FAILURE_KEYWORDS = ["failed", "失败", "异常", "error", "exception"]


class ReflectionEngine:
    """基于规则引擎的反思器。

    LLM 可选注入：若提供 llm_client，可在规则分析后调用 LLM 补充观察与建议。
    当前默认不依赖 LLM，保证独立可用。

    Args:
        llm_client: 可选的 OpenAI 兼容 LLM 客户端，用于增强反思质量。
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    async def reflect_on_episode(self, episode: Any) -> ReflectionResult:
        """对单个 episode 进行反思分析。"""
        result = ReflectionResult(
            episode_id=episode.episode_id,
            success=episode.final_status == "verified",
        )

        # 1. 分析执行日志中的失败步骤
        failed_steps = self._find_failed_steps(episode)
        if failed_steps:
            result.failure_root_causes.extend(
                self._classify_failures(failed_steps, episode.error_message)
            )
            result.improvement_suggestions.extend(
                self._suggest_improvements(failed_steps, episode.task_type)
            )

        # 2. 分析参数与计划模式
        observations = self._extract_observations(episode)
        result.key_observations.extend(observations)

        # 3. 成功路径的经验提取
        if result.success:
            result.key_observations.append(
                f"任务在 {len(episode.plan_steps or [])} 步内成功完成，耗时 {episode.duration_seconds:.1f}s"
            )
            successful_patterns = self._extract_success_patterns(episode)
            result.key_observations.extend(successful_patterns)

        # 4. 置信度评估
        result.confidence = self._compute_confidence(result, episode)

        # 5. 可选 LLM 增强
        if self._llm_client is not None:
            try:
                llm_enriched = await self._llm_enhance(result, episode)
                if llm_enriched:
                    result.key_observations.extend(llm_enriched.get("observations", []))
                    result.improvement_suggestions.extend(llm_enriched.get("suggestions", []))
            except Exception as exc:
                logger.warning("LLM 反思增强失败，使用规则引擎结果: %s", exc)

        logger.info(
            "Reflection on %s: success=%s, causes=%d, suggestions=%d",
            episode.episode_id,
            result.success,
            len(result.failure_root_causes),
            len(result.improvement_suggestions),
        )
        return result

    async def reflect_on_batch(self, episodes: list[Any]) -> list[ReflectionResult]:
        """批量反思多个 episodes。"""
        results = []
        for ep in episodes:
            result = await self.reflect_on_episode(ep)
            results.append(result)
        return results

    def _find_failed_steps(self, episode: Any) -> list[dict[str, Any]]:
        """从执行日志中提取失败的步骤。"""
        execution_log = episode.execution_log or []
        if not execution_log:
            step_results = getattr(episode, "step_results", []) or []
            execution_log = [
                {"step": sr.step, "status": sr.status, "error": sr.error} for sr in step_results
            ]

        failed = []
        for entry in execution_log:
            status = (entry.get("status") or "").lower()
            error = (entry.get("error") or "").lower()
            if (
                "fail" in status
                or "error" in status
                or any(kw in error for kw in _STEP_FAILURE_KEYWORDS)
            ):
                failed.append(entry)
        return failed

    def _classify_failures(
        self, failed_steps: list[dict[str, Any]], error_message: str | None
    ) -> list[str]:
        """将失败步骤归类为根因。"""
        combined_text = "\n".join(
            [str(s.get("error", "")) or str(s.get("status", "")) for s in failed_steps]
        )
        if error_message:
            combined_text += "\n" + error_message

        causes = []
        for pattern, labels in _FAILURE_PATTERNS.items():
            for label in labels:
                if label.lower() in combined_text.lower():
                    causes.append(f"{pattern}: 匹配到 '{label}' 模式")
                    break

        if not causes and failed_steps:
            causes.append("unknown: 未匹配已知失败模式，需人工审查")

        return causes

    def _suggest_improvements(
        self, failed_steps: list[dict[str, Any]], task_type: str
    ) -> list[str]:
        """基于失败模式生成改进建议。"""
        suggestions = []
        for step in failed_steps:
            step_name = step.get("step", "unknown")
            error = str(step.get("error", "")).lower()

            if "param" in error or "validate" in error or "missing" in error:
                suggestions.append(
                    f"步骤 '{step_name}' 参数校验失败：建议在 planning 阶段增加参数完整性检查"
                )
            elif "throttl" in error or "rate" in error:
                suggestions.append(
                    f"步骤 '{step_name}' 触发限流：建议增加指数退避重试（初始 1s，最大 30s）"
                )
            elif "forbidden" in error or "permission" in error or "403" in error:
                suggestions.append(f"步骤 '{step_name}' 权限不足：确认 RAM 策略是否覆盖该操作")
            elif "timeout" in error or "network" in error:
                suggestions.append(f"步骤 '{step_name}' 网络/超时：建议增加连接超时与重试机制")
            elif "sql" in error or "syntax" in error:
                suggestions.append(f"步骤 '{step_name}' SQL 错误：建议使用 sqlglot 预校验 SQL 语法")
            else:
                suggestions.append(f"步骤 '{step_name}' 执行失败：建议查看完整日志并手动复核")

        if task_type == "create_ods":
            suggestions.append(
                "ODS 创建失败常见原因：源表不存在或数据源配置错误，建议先验证源端连通性"
            )
        elif task_type == "create_dwd":
            suggestions.append("DWD 创建失败常见原因：上游表缺失或字段映射错误，建议先检查血缘关系")

        return suggestions

    def _extract_observations(self, episode: Any) -> list[str]:
        """从 episode 中提取关键观察。"""
        observations = []

        plan_steps = episode.plan_steps or []
        observations.append(f"计划包含 {len(plan_steps)} 个步骤")

        duration = episode.duration_seconds
        if duration > 60:
            observations.append(f"执行耗时较长 ({duration:.0f}s)，可能存在性能瓶颈")
        elif duration < 5:
            observations.append(f"执行快速完成 ({duration:.0f}s)")

        error_msg = episode.error_message
        if error_msg:
            observations.append(f"错误信息摘要: {error_msg[:100]}")

        return observations

    def _extract_success_patterns(self, episode: Any) -> list[str]:
        """从成功案例中提取可复用模式。"""
        patterns = []
        params = episode.params or {}
        target = params.get("target_table", "")

        if target:
            patterns.append(f"成功创建/操作目标: {target}")

        plan_steps = episode.plan_steps or []
        step_names = [s.get("step", "") for s in plan_steps]
        if "validate_params" in step_names and all(
            s.get("status") == "completed" for s in plan_steps if s.get("step") == "validate_params"
        ):
            patterns.append("参数预校验有效，避免了后续无效执行")

        return patterns

    def _compute_confidence(self, result: ReflectionResult, episode: Any) -> float:
        """计算反思结果的置信度。"""
        confidence = 0.5  # 基础置信度

        # 有失败步骤 + 匹配到已知模式 → 提高置信度
        if result.failure_root_causes:
            confidence += min(0.2, len(result.failure_root_causes) * 0.1)

        # 有改进建议 → 提高置信度
        if result.improvement_suggestions:
            confidence += 0.1

        # 执行日志丰富 → 提高置信度
        log_count = len(episode.execution_log or [])
        if log_count >= 3:
            confidence += 0.1
        elif log_count == 0:
            confidence -= 0.1

        return max(0.0, min(1.0, confidence))

    async def _llm_enhance(
        self, result: ReflectionResult, episode: Any
    ) -> dict[str, list[str]] | None:
        """调用 LLM 增强反思结果。"""
        if self._llm_client is None:
            return None

        prompt = (
            f"请分析以下 DataWorks 数仓任务执行记录，提供额外的观察和改进建议。\n\n"
            f"任务类型: {episode.task_type}\n"
            f"最终状态: {episode.final_status}\n"
            f"错误信息: {episode.error_message or '无'}\n"
            f"执行日志: {len(episode.execution_log or [])} 条\n"
            f"已有观察: {result.key_observations}\n"
            f"已有根因: {result.failure_root_causes}\n"
            f"已有建议: {result.improvement_suggestions}\n\n"
            f'返回 JSON 格式: {{"observations": [...], "suggestions": [...]}}'
        )

        try:
            response = await self._llm_client.chat.completions.create(
                model="deepseek-v4-flash-free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            if content:
                import json

                return json.loads(content)
        except Exception:
            return None

        return None
