"""实体抽取器"""
import re
from typing import Any


class EntityExtractor:
    """从文本中抽取实体"""

    def extract_table_name(self, text: str) -> str | None:
        """抽取表名"""
        patterns = [
            r"(?:ods|dwd|dws|dim|dmr)[_a-zA-Z0-9]+(?=[^a-zA-Z0-9]|$)",
            r"([a-zA-Z0-9_]+)(?:表|数据表)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0) if match.lastindex is None else match.group(1)
        return None

    def extract_params(self, text: str, template: dict[str, Any]) -> dict[str, Any]:
        """根据模板抽取参数"""
        params: dict[str, Any] = {}
        if "table_name" in template.get("required_params", []):
            table_name = self.extract_table_name(text)
            if table_name:
                params["table_name"] = table_name
        return params
