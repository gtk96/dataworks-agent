"""意图解析器"""

import re
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

# 否定词列表。删除/移除属于高风险操作，不作为普通否定处理，交给 Publish Gate/guardrail。
NEGATION_WORDS = ["不要", "别", "禁止", "取消", "停止", "关闭"]

DATAWORKS_GOAL_WORDS = (
    "dataworks",
    "数仓",
    "建模",
    "模型",
    "调度",
    "节点",
    "血缘",
    "依赖",
    "治理",
    "质量",
    "异常",
    "指标",
    "口径",
    "发布",
    "上线",
    "ddl",
    "dml",
    "flowspec",
    "ods_",
    "dwd_",
    "dws_",
    "dim_",
    "dmr_",
    "ads_",
)


@dataclass
class Intent:
    """意图数据类"""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""
    is_negated: bool = False


class IntentParser:
    """意图解析器"""

    def __init__(self) -> None:
        self._extractor = EntityExtractor()
        self._templates = INTENT_TEMPLATES

    def _check_negation(self, text: str) -> bool:
        """检查文本是否包含否定词"""
        text_lower = text.lower()
        return any(negation in text_lower for negation in NEGATION_WORDS)

    def parse(self, text: str) -> Intent:
        """解析用户输入为意图"""
        text_lower = text.lower().strip()
        is_negated = self._check_negation(text)

        for action, template in self._templates.items():
            for pattern in template["patterns"]:
                if re.search(pattern, text_lower):
                    params = self._extractor.extract_params(text, template)

                    # 如果是否定句，降低置信度，但仍保留计划让后续 guardrail 处理。
                    confidence = 0.35 if is_negated else 0.82

                    return Intent(
                        action=action,
                        params=params,
                        confidence=confidence,
                        raw_text=text,
                        is_negated=is_negated,
                    )

        table_name = self._extractor.extract_table_name(text)
        if table_name and any(
            word in text_lower for word in ("查询", "查看", "检索", "查", "血缘", "依赖", "query")
        ):
            params = {"table_name": table_name}
            depth = self._extractor.extract_depth(text)
            if depth is not None:
                params["depth"] = depth
            return Intent(
                action="query_lineage",
                params=params,
                confidence=0.65 if not is_negated else 0.35,
                raw_text=text,
                is_negated=is_negated,
            )

        if self._looks_like_dataworks_goal(text_lower):
            template = self._templates["agent_workflow"]
            params = self._extractor.extract_params(text, template)
            return Intent(
                action="agent_workflow",
                params=params,
                confidence=0.58 if not is_negated else 0.35,
                raw_text=text,
                is_negated=is_negated,
            )

        return Intent(
            action="unknown",
            params={},
            confidence=0.0,
            raw_text=text,
            is_negated=is_negated,
        )

    def _looks_like_dataworks_goal(self, text_lower: str) -> bool:
        return any(word in text_lower for word in DATAWORKS_GOAL_WORDS)
