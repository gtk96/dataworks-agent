"""意图解析器"""

import re
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

# 否定词列表
NEGATION_WORDS = ["不要", "别", "禁止", "取消", "停止", "关闭", "删除", "移除"]


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

                    # 如果是否定句，降低置信度
                    confidence = 0.3 if is_negated else 0.8

                    return Intent(
                        action=action,
                        params=params,
                        confidence=confidence,
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
