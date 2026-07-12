"""Entity extractor for chat Agent."""

from __future__ import annotations

import re
from typing import Any


class EntityExtractor:
    """Extract deterministic entities from natural language text."""

    _TABLE_PATTERN = r"((?:ods|dwd|dws|dim|dmr|ads|tmp|cda)[_a-zA-Z0-9]+)(?=[^a-zA-Z0-9]|$)"
    _RAW_TABLE_PATTERN = r"([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)?)"

    def extract_table_name(self, text: str) -> str | None:
        """Extract target warehouse table name."""
        target_patterns = [
            rf"(?:\u76ee\u6807\u8868|\u76ee\u6807\u6a21\u578b|\u4ea7\u51fa\u8868|\u751f\u6210|\u8bbe\u8ba1|\u5efa\u6210|\u5efa\u8bbe|\u53d1\u5e03)\s*(?:\u4e3a|\u6210|\u5230|\uff1a|:)?\s*{self._TABLE_PATTERN}",
            rf"(?:to|target)\s+{self._TABLE_PATTERN}",
        ]
        for pattern in target_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        tables = self.extract_table_names(text)
        if not tables:
            generic_match = re.search(
                r"([a-zA-Z][a-zA-Z0-9_]{2,})(?:\u8868|\u6570\u636e\u8868)", text
            )
            return generic_match.group(1) if generic_match else None

        for table in tables:
            if table.lower().startswith(("dwd_", "dws_", "dim_", "dmr_", "ads_")):
                return table
        return tables[0]

    def extract_table_names(self, text: str) -> list[str]:
        """Extract warehouse table names in first-seen order."""
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
        """Extract source table name."""
        patterns = [
            rf"(?:\u6e90\u8868|\u6765\u6e90\u8868|\u57fa\u4e8e|\u4ece|\u7531)\s*(?:\u8868|\u6570\u636e\u8868)?\s*(?:\u4e3a|\u662f|\uff1a|:)?\s*{self._TABLE_PATTERN}",
            rf"(?:from|source)\s+{self._TABLE_PATTERN}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        raw_patterns = [
            rf"(?:\u6e90\u8868|\u6765\u6e90\u8868|\u57fa\u4e8e|\u4ece|\u7531)\s*(?:\u8868|\u6570\u636e\u8868)?\s*(?:\u4e3a|\u662f|\uff1a|:)?\s*{self._RAW_TABLE_PATTERN}",
            rf"(?:from|source(?:\s+table)?)\s+{self._RAW_TABLE_PATTERN}",
            rf"\u6570\u636e\u6e90\s*{self._RAW_TABLE_PATTERN}\s*(?:\u7684|\u4e0b\u7684|\u91cc?\u7684)\s*{self._RAW_TABLE_PATTERN}\s*(?:\u8868|table)?",
            rf"(?:mysql|hologres|holo|postgres(?:ql)?|polardb|oracle|sqlserver|oss)\s+{self._RAW_TABLE_PATTERN}",
        ]
        for pattern in raw_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(2) if len(match.groups()) >= 2 else match.group(1)

        tables = self.extract_table_names(text)
        if len(tables) >= 2:
            for table in tables:
                if table.lower().startswith("ods_"):
                    return table
            return tables[0]
        ods_table = self.extract_ods_table(text)
        if ods_table:
            return ods_table
        return None

    def extract_layer(self, text: str) -> str | None:
        """Extract warehouse layer."""
        match = re.search(r"\b(ods|dwd|dws|dim|dmr|ads)\b", text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        table_name = self.extract_table_name(text)
        if table_name and "_" in table_name:
            prefix = table_name.split("_", 1)[0].lower()
            if prefix in {"ods", "dwd", "dws", "dim", "dmr", "ads"}:
                return prefix
        for keyword, layer in {
            "\u660e\u7ec6": "dwd",
            "\u6c47\u603b": "dws",
            "\u7ef4\u5ea6": "dim",
            "\u62a5\u8868": "dmr",
            "\u5e94\u7528": "ads",
            "\u8d34\u6e90": "ods",
        }.items():
            if keyword in text:
                return layer
        return None

    def extract_depth(self, text: str) -> int | None:
        """Extract lineage depth."""
        match = re.search(r"(\d+)\s*(?:\u5c42|\u7ea7|depth)", text, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    def extract_task_id(self, text: str) -> str | None:
        """Extract task ID."""
        match = re.search(r"(task[_-][a-zA-Z0-9_-]+|run[_-][a-zA-Z0-9_-]+)", text)
        return match.group(1) if match else None

    def extract_domain(self, text: str) -> str | None:
        """Extract business domain."""
        match = re.search(
            r"(?:\u4e1a\u52a1\u57df|\u4e3b\u9898\u57df|\u57df)\s*(?:\u4e3a|\u662f|\uff1a|:)?\s*([\u4e00-\u9fa5A-Za-z0-9_-]{2,32})",
            text,
        )
        return match.group(1) if match else None

    def extract_schedule_cycle(self, text: str) -> str | None:
        """Extract schedule cycle."""
        mapping = {
            "\u5c0f\u65f6": "hourly",
            "\u6bcf\u5c0f\u65f6": "hourly",
            "\u65e5\u8c03\u5ea6": "daily",
            "\u6bcf\u5929": "daily",
            "\u6bcf\u65e5": "daily",
            "\u5929\u7ea7": "daily",
            "\u5468": "weekly",
            "\u6708": "monthly",
        }
        for keyword, cycle in mapping.items():
            if keyword in text:
                return cycle
        return None

    def extract_source_type(self, text: str) -> str | None:
        """Extract ODS source type."""
        realtime_mapping = {
            "\u5b9e\u65f6": "realtime",
            "realtime": "realtime",
            "real-time": "realtime",
            "cdc": "realtime",
            "flink": "realtime",
            "binlog": "realtime",
        }
        mapping = {
            "hologres": "hologres",
            "holo": "hologres",
            "mysql": "mysql",
            "polardb": "polardb",
            "polar": "polardb",
            "postgresql": "postgres",
            "postgres": "postgres",
            "oracle": "oracle",
            "sqlserver": "sqlserver",
            "oss": "oss",
            "s3": "oss",
        }
        lowered = text.lower()
        for keyword, source_type in realtime_mapping.items():
            if keyword in lowered or keyword in text:
                return source_type
        for keyword, source_type in mapping.items():
            if keyword in lowered or keyword in text:
                return source_type
        return None

    def extract_datasource_name(self, text: str) -> str | None:
        """Extract DataWorks datasource name."""
        patterns = [
            rf"(?:\u6570\u636e\u6e90|datasource|data source)\s*(?:\u4e3a|\u662f|\uff1a|:)?\s*{self._RAW_TABLE_PATTERN}",
            rf"(?:mysql|hologres|holo|postgres(?:ql)?|polardb|oracle|sqlserver)\s+(?:\u6570\u636e\u6e90\s*)?{self._RAW_TABLE_PATTERN}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def extract_oss_path(self, text: str) -> str | None:
        """Extract OSS object path."""
        match = re.search(r"(oss://[^\s\u3002\uff0c,;\uff1b]+)", text, re.IGNORECASE)
        return match.group(1) if match else None

    def extract_ods_table(self, text: str) -> str | None:
        """Extract ODS table."""
        for table in self.extract_table_names(text):
            if table.lower().startswith("ods_"):
                return table
        return None

    def extract_dwd_table(self, text: str) -> str | None:
        """Extract DWD table."""
        target_patterns = [
            rf"(?:\u76ee\u6807\u8868|\u76ee\u6807\u6a21\u578b|\u4ea7\u51fa\u8868|\u751f\u6210|\u8bbe\u8ba1|\u5efa\u6210|\u5efa\u8bbe|\u518d\u5efa|\u521b\u5efa|\u65b0\u5efa)\s*(?:\u4e3a|\u6210|\u5230|\uff1a|:)?\s*{self._TABLE_PATTERN}",
            rf"(?:dwd|\u660e\u7ec6).*?{self._TABLE_PATTERN}",
        ]
        for pattern in target_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match and match.group(1).lower().startswith("dwd_"):
                return match.group(1)
        for table in self.extract_table_names(text):
            if table.lower().startswith("dwd_"):
                return table
        return None

    def extract_granularity(self, text: str) -> str | None:
        """Extract ODS/DWD granularity."""
        mapping = {
            "\u6bcf\u5c0f\u65f6": "hour",
            "\u5c0f\u65f6": "hour",
            "hourly": "hour",
            "hour": "hour",
            "\u65e5\u5168\u91cf": "day",
            "\u65e5\u589e\u91cf": "day",
            "\u6bcf\u65e5": "day",
            "\u6bcf\u5929": "day",
            "\u5929\u7ea7": "day",
            "daily": "day",
            "day": "day",
            "\u5206\u949f": "minute",
            "minute": "minute",
            "min": "minute",
            "\u5b9e\u65f6": "realtime",
            "realtime": "realtime",
            "\u5168\u91cf": "full",
            "full": "full",
        }
        lowered = text.lower()
        for keyword, granularity in mapping.items():
            if keyword in lowered or keyword in text:
                return granularity
        return None

    def extract_schedule_minute(self, text: str) -> int | None:
        """Extract hourly schedule minute."""
        patterns = [
            r"(?:\u7b2c|\u6bcf\u5c0f\u65f6\u7b2c)?(\d{1,2})\s*(?:\u5206\u949f|\u5206)",
            r"minute\s*(?:=|:)?\s*(\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                if 0 <= value <= 59:
                    return value
        return None

    def extract_metric_id(self, text: str) -> str | None:
        """Extract metric identifier."""
        match = re.search(
            r"(?:\u6307\u6807|\u53e3\u5f84|metric)\s*(?:\u4e3a|\u662f|\uff1a|:)?\s*([a-zA-Z][a-zA-Z0-9_]{2,})",
            text,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def extract_params(self, text: str, template: dict[str, Any]) -> dict[str, Any]:
        """Extract params required by an intent template."""
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
        if "source_type" in wanted:
            source_type = self.extract_source_type(text)
            if source_type:
                params["source_type"] = source_type
        if "datasource_name" in wanted:
            datasource_name = self.extract_datasource_name(text)
            if datasource_name:
                params["datasource_name"] = datasource_name
        if "oss_path" in wanted:
            oss_path = self.extract_oss_path(text)
            if oss_path:
                params["oss_path"] = oss_path
        if "ods_table" in wanted:
            ods_table = self.extract_ods_table(text)
            if ods_table:
                params["ods_table"] = ods_table
        if "dwd_table" in wanted:
            dwd_table = self.extract_dwd_table(text)
            if dwd_table:
                params["dwd_table"] = dwd_table
                params.setdefault("table_name", dwd_table)
        if "granularity" in wanted:
            granularity = self.extract_granularity(text)
            if granularity:
                params["granularity"] = granularity
        if "schedule_minute" in wanted:
            schedule_minute = self.extract_schedule_minute(text)
            if schedule_minute is not None:
                params["schedule_minute"] = schedule_minute
        if "goal" in wanted:
            params["goal"] = text.strip()
        return params
