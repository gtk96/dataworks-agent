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
    "oss",
    "数据源",
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
        """解析用户输入为意图 — 按优先级匹配，特定意图优先于通用意图。"""
        text_lower = text.lower().strip()
        is_negated = self._check_negation(text)

        # 优先级顺序：更具体的意图先匹配
        priority_actions = [
            "any_ods_modeling",
            "ods_dwd_modeling",
            "forward_modeling",
            "reverse_modeling",
            "diagnose_issue",
            "metric_attribution",
            "publish_review",
            "ask_data",
            "cookie_manage",
            "greeting",
            "create_table",
            "query_lineage",
            "check_status",
            "agent_workflow",
        ]

        for action in priority_actions:
            if action not in self._templates:
                continue
            template = self._templates[action]
            for pattern in template["patterns"]:
                if re.search(pattern, text_lower):
                    params = self._extractor.extract_params(text, template)
                    confidence = 0.35 if is_negated else 0.82
                    return Intent(
                        action=action,
                        params=params,
                        confidence=confidence,
                        raw_text=text,
                        is_negated=is_negated,
                    )

        # Try multiple extraction strategies for table/entity name
        table_name = self._extractor.extract_table_name(text)
        if not table_name:
            table_name = self._extract_fuzzy_table_name(text)
        if not table_name:
            # Also try plain table names like "订单表" -> "订单"
            plain_match = re.search(
                r"(?:查|查看|查询|检索|找|看)[\s\S]*(?:一下|一|下)?[\s\S]*([^\s,，。；;\n]+?)表",
                text,
            )
            if plain_match:
                table_name = plain_match.group(1)

        # Distinguish: lineage keywords -> query_lineage, plain table lookup -> ask_data
        has_lineage_keyword = any(
            word in text_lower for word in ("血缘", "依赖", "影响", "query.*lineage")
        )
        if table_name and has_lineage_keyword:
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

        # Plain table lookup without lineage keywords -> ask_data
        if table_name:
            return Intent(
                action="ask_data",
                params={"table_name": table_name, "goal": text.strip()},
                confidence=0.6 if not is_negated else 0.35,
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

    def _extract_fuzzy_table_name(self, text: str) -> str | None:
        """Extract a Chinese business entity name from loose phrasing like '查一下订单'.

        Handles patterns such as:
          - "我想查一下订单" -> "订单"
          - "看看用户数据" -> "用户"
          - "查一下商品" -> "商品"
          - "统计一下GMV" -> "gmv"
        """
        # Pattern: verb(s) + optional filler + entity + optional "表/数据/量"
        # Strip common prefixes first
        stripped = re.sub(r"^(我想|请|帮|帮我|我要|能|能不能|怎么|如何)\s*", "", text)
        stripped = re.sub(r"^(查|查看|查询|检索|找|看|统计)\s*(一下|一|下)?\s*", "", stripped)
        # Now strip trailing qualifiers
        stripped = re.sub(r"\s*(的)?\s*(表|数据|量|数|信息|记录)$", "", stripped)
        # Remaining should be the entity name
        entity = stripped.strip()
        if entity and len(entity) >= 1:
            return entity
        return None

    def _looks_like_dataworks_goal(self, text_lower: str) -> bool:
        return any(word in text_lower for word in DATAWORKS_GOAL_WORDS)
