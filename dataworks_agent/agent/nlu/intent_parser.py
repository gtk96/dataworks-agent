"""意图解析器"""
import re
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES


@dataclass
class Intent:
    """意图数据类"""
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""


class IntentParser:
    """意图解析器"""

    def __init__(self) -> None:
        self._extractor = EntityExtractor()
        self._templates = INTENT_TEMPLATES

    def parse(self, text: str) -> Intent:
        """解析用户输入为意图"""
        text_lower = text.lower().strip()

        for action, template in self._templates.items():
            for pattern in template["patterns"]:
                if re.search(pattern, text_lower):
                    params = self._extractor.extract_params(text, template)
                    return Intent(
                        action=action,
                        params=params,
                        confidence=0.8,
                        raw_text=text,
                    )

        return Intent(
            action="unknown",
            params={},
            confidence=0.0,
            raw_text=text,
        )
