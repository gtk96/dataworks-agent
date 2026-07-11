"""实体抽取器。"""

from __future__ import annotations

import re
from typing import Any


class EntityExtractor:
    """从文本中抽取实体。"""

    _TABLE_PATTERN = r"((?:ods|dwd|dws|dim|dmr|ads|tmp|cda)[_a-zA-Z0-9]+)(?=[^a-zA-Z0-9]|$)"

    def extract_table_name(self, text: str) -> str | None:
        """抽取目标表名。"""
        target_patterns = [
            rf"(?:目标表|目标模型|产出表|生成|设计|建成|建设|发布)\s*(?:为|成|到|：|:)?\s*{self._TABLE_PATTERN}",
            rf"(?:to|target)\s+{self._TABLE_PATTERN}",
        ]
        for pattern in target_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        tables = self.extract_table_names(text)
        if not tables:
            generic_match = re.search(r"([a-zA-Z][a-zA-Z0-9_]{2,})(?:表|数据表)", text)
            return generic_match.group(1) if generic_match else None

        for table in tables:
            if table.lower().startswith(("dwd_", "dws_", "dim_", "dmr_", "ads_")):
                return table
        return tables[0]

    def extract_table_names(self, text: str) -> list[str]:
        """按出现顺序抽取所有数仓表名并去重。"""
        seen: set[str] = set()
        tables: list[str] = []
        for match in re.finditer(self._TABLE_PATTERN, text, re.IGNORECASE):
            table = match.group(1)
            key = table.lower()
            if key not in seen:
                seen.add(key)
                tables.append(table)
        return tables

    def extract_source_table(self, text: str) -> str | None:
        """抽取源表名。"""
        patterns = [
            rf"(?:源表|来源表|基于|从|由)\s*(?:表|数据表)?\s*(?:为|是|：|:)?\s*{self._TABLE_PATTERN}",
            rf"(?:from|source)\s+{self._TABLE_PATTERN}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        tables = self.extract_table_names(text)
        if len(tables) >= 2:
            for table in tables:
                if table.lower().startswith("ods_"):
                    return table
            return tables[0]
        return None

    def extract_layer(self, text: str) -> str | None:
        """抽取数仓分层。"""
        match = re.search(r"\b(ods|dwd|dws|dim|dmr|ads)\b", text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        table_name = self.extract_table_name(text)
        if table_name and "_" in table_name:
            prefix = table_name.split("_", 1)[0].lower()
            if prefix in {"ods", "dwd", "dws", "dim", "dmr", "ads"}:
                return prefix
        for keyword, layer in {
            "明细": "dwd",
            "汇总": "dws",
            "维度": "dim",
            "报表": "dmr",
            "应用": "ads",
            "贴源": "ods",
        }.items():
            if keyword in text:
                return layer
        return None

    def extract_depth(self, text: str) -> int | None:
        """抽取血缘深度。"""
        match = re.search(r"(\d+)\s*(?:层|级|depth)", text, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    def extract_task_id(self, text: str) -> str | None:
        """抽取任务 ID。"""
        match = re.search(r"(task[_-][a-zA-Z0-9_-]+|run[_-][a-zA-Z0-9_-]+)", text)
        return match.group(1) if match else None

    def extract_domain(self, text: str) -> str | None:
        """抽取业务域。"""
        match = re.search(r"(?:业务域|主题域|域)\s*(?:为|是|：|:)?\s*([一-龥A-Za-z0-9_-]{2,32})", text)
        return match.group(1) if match else None

    def extract_schedule_cycle(self, text: str) -> str | None:
        """抽取调度周期。"""
        mapping = {
            "小时": "hourly",
            "每小时": "hourly",
            "日调度": "daily",
            "每天": "daily",
            "每日": "daily",
            "天级": "daily",
            "周": "weekly",
            "月": "monthly",
        }
        for keyword, cycle in mapping.items():
            if keyword in text:
                return cycle
        return None

    def extract_metric_id(self, text: str) -> str | None:
        """抽取指标/口径标识。"""
        match = re.search(r"(?:指标|口径|metric)\s*(?:为|是|：|:)?\s*([a-zA-Z][a-zA-Z0-9_]{2,})", text, re.IGNORECASE)
        return match.group(1) if match else None

    def extract_params(self, text: str, template: dict[str, Any]) -> dict[str, Any]:
        """根据模板抽取参数。"""
        params: dict[str, Any] = {}
        wanted = set(template.get("required_params", [])) | set(template.get("optional_params", []))

        if "table_name" in wanted:
            table_name = self.extract_table_name(text)
            if table_name:
                params["table_name"] = table_name
        if "source_table" in wanted:
            source_table = self.extract_source_table(text)
            if source_table:
                params["source_table"] = source_table
        if "layer" in wanted:
            layer = self.extract_layer(text)
            if layer:
                params["layer"] = layer
        if "depth" in wanted:
            depth = self.extract_depth(text)
            if depth is not None:
                params["depth"] = depth
        if "task_id" in wanted:
            task_id = self.extract_task_id(text)
            if task_id:
                params["task_id"] = task_id
        if "domain" in wanted:
            domain = self.extract_domain(text)
            if domain:
                params["domain"] = domain
        if "schedule_cycle" in wanted:
            schedule_cycle = self.extract_schedule_cycle(text)
            if schedule_cycle:
                params["schedule_cycle"] = schedule_cycle
        if "metric_id" in wanted:
            metric_id = self.extract_metric_id(text)
            if metric_id:
                params["metric_id"] = metric_id
        if "goal" in wanted:
            params["goal"] = text.strip()
        return params
