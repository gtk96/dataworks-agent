"""LLM_Router — 按任务复杂度分级路由到模型档位（Requirement 7）。

轻量 / 常规 / 复杂三档；若某档未配置则回退到默认模型。
仅配置单一模型时，所有请求都路由到该模型（Requirement 7.4）。
"""

from __future__ import annotations

from typing import Literal

TaskComplexity = Literal["light", "normal", "complex"]


class LLMRouter:
    """把任务复杂度映射到具体模型名。"""

    def __init__(self, default_model: str, models: dict[str, str] | None = None) -> None:
        """
        Args:
            default_model: 兜底模型（对应 settings.llm_model）。
            models: 可选的 {档位: 模型名} 映射；缺失或空值的档位回退到 default_model。
        """
        if not default_model:
            raise ValueError("LLMRouter 需要非空的 default_model")
        self._default = default_model
        self._models = {k: v for k, v in (models or {}).items() if v}

    def route(self, complexity: TaskComplexity = "normal") -> str:
        """返回该复杂度档位对应的模型名，未配置则回退默认模型。"""
        return self._models.get(complexity, self._default)

    @classmethod
    def from_settings(cls, settings) -> LLMRouter:
        """从全局配置构建路由器。"""
        return cls(
            default_model=settings.llm_model,
            models={
                "light": settings.llm_model_light,
                "normal": settings.llm_model_normal,
                "complex": settings.llm_model_complex,
            },
        )
