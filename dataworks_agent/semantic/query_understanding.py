"""Deterministic business-query understanding for the autonomous analytics path.

The parser turns colloquial Chinese questions into a schema-bound query frame.  It
is deliberately independent from an LLM: an LLM may propose a frame later, but
only fields present in an approved metric contract can survive validation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, ClassVar


@dataclass(frozen=True)
class QueryTimeRange:
    kind: str = "latest"
    start: str = ""
    end: str = ""
    label: str = "最新可用数据"


@dataclass(frozen=True)
class BusinessQuery:
    metric_id: str
    metric_name: str
    dimensions: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    time_range: QueryTimeRange = field(default_factory=QueryTimeRange)
    query_type: str = "total"
    order: str = "desc"
    limit: int = 100
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BusinessQuery:
        time_value = value.get("time_range") or {}
        return cls(
            metric_id=str(value["metric_id"]),
            metric_name=str(value.get("metric_name") or value["metric_id"]),
            dimensions=[str(item) for item in value.get("dimensions", [])],
            filters=dict(value.get("filters") or {}),
            time_range=QueryTimeRange(
                kind=str(time_value.get("kind") or "latest"),
                start=str(time_value.get("start") or ""),
                end=str(time_value.get("end") or ""),
                label=str(time_value.get("label") or "latest available data"),
            ),
            query_type=str(value.get("query_type") or "total"),
            order=str(value.get("order") or "desc"),
            limit=int(value.get("limit") or 100),
            confidence=float(value.get("confidence") or 1.0),
            evidence=[str(item) for item in value.get("evidence", [])],
        )


class BusinessQueryUnderstanding:
    """Parse metrics, dimensions, values, time and ranking from approved contracts."""

    _PLATFORM_VALUES: ClassVar[dict[str, str]] = {
        "facebook": "facebook",
        "脸书": "facebook",
        "fb": "facebook",
        "google": "google",
        "谷歌": "google",
        "tiktok": "tiktok",
        "抖音海外": "tiktok",
        "snapchat": "snapchat",
        "snap": "snapchat",
    }

    def __init__(self, today_provider: Callable[[], date] | None = None) -> None:
        self._today = today_provider or date.today

    def understand(
        self, question: str, definitions: list[dict[str, Any]]
    ) -> tuple[BusinessQuery, dict[str, Any]] | None:
        definition = self._match_metric(question, definitions)
        if definition is None:
            return None

        time_range = self._parse_time(question)
        freshness = definition.get("freshness") or {}
        if time_range.kind not in {"latest", "today"} and not freshness.get(
            "supports_historical", False
        ):
            return None

        selected: list[str] = []
        filters: dict[str, Any] = {}
        evidence = [f"metric:{definition['id']}"]
        for dimension in definition.get("dimensions", []):
            dimension_id = str(dimension.get("id") or dimension.get("column") or "")
            if not dimension_id:
                continue
            if self._is_group_dimension(question, dimension):
                selected.append(dimension_id)
                evidence.append(f"group:{dimension_id}")
            value = self._extract_dimension_value(question, dimension)
            if value is not None:
                filters[dimension_id] = value
                evidence.append(f"filter:{dimension_id}={value}")

        trend = any(token in question for token in ("趋势", "每天", "每日", "按天"))
        query_type = "trend" if trend else "breakdown" if selected else "total"
        top_match = re.search(r"(?:top|前)\s*(\d{1,3})", question, re.I)
        limit = min(max(int(top_match.group(1)), 1), 1000) if top_match else 100
        order = "asc" if any(token in question for token in ("最低", "最少", "升序")) else "desc"
        return (
            BusinessQuery(
                metric_id=str(definition["id"]),
                metric_name=str(definition.get("name") or definition["id"]),
                dimensions=selected,
                filters=filters,
                time_range=time_range,
                query_type=query_type,
                order=order,
                limit=limit,
                confidence=1.0,
                evidence=evidence,
            ),
            definition,
        )

    def refine(
        self,
        followup: str,
        previous: BusinessQuery | dict[str, Any],
        definition: dict[str, Any],
    ) -> BusinessQuery | None:
        """Apply a short follow-up to a validated prior query frame."""
        prior = (
            previous if isinstance(previous, BusinessQuery) else BusinessQuery.from_dict(previous)
        )
        if prior.metric_id != str(definition.get("id") or ""):
            return None

        dimensions = list(prior.dimensions)
        filters = dict(prior.filters)
        evidence = [*prior.evidence, "followup"]
        changed = False

        explicit_time = self._has_time_expression(followup)
        time_range = self._parse_time(followup) if explicit_time else prior.time_range
        if explicit_time:
            changed = True

        grouped: list[str] = []
        for dimension in definition.get("dimensions", []):
            dimension_id = str(dimension.get("id") or dimension.get("column") or "")
            if not dimension_id:
                continue
            if self._is_group_dimension(followup, dimension):
                grouped.append(dimension_id)
            value = self._extract_dimension_value(followup, dimension)
            if value is not None:
                filters[dimension_id] = value
                dimensions = [item for item in dimensions if item != dimension_id]
                evidence.append(f"followup_filter:{dimension_id}={value}")
                changed = True
            aliases = [str(dimension.get("name") or ""), *map(str, dimension.get("aliases", []))]
            if dimension_id in filters and any(
                marker in followup
                for alias in aliases
                if alias
                for marker in (
                    f"\u5168\u90e8{alias}",
                    f"\u6240\u6709{alias}",
                    f"\u4e0d\u9650{alias}",
                )
            ):
                filters.pop(dimension_id, None)
                changed = True

        if grouped:
            dimensions = list(dict.fromkeys(grouped))
            for dimension_id in dimensions:
                filters.pop(dimension_id, None)
            evidence.extend(f"followup_group:{item}" for item in dimensions)
            changed = True

        trend = any(
            token in followup
            for token in ("\u8d8b\u52bf", "\u6bcf\u5929", "\u6bcf\u65e5", "\u6309\u5929")
        )
        query_type = "trend" if trend else "breakdown" if dimensions else "total"
        if trend:
            changed = True
        top_match = re.search(r"(?:top|\u524d)\s*(\d{1,3})", followup, re.I)
        limit = prior.limit
        if top_match:
            limit = min(max(int(top_match.group(1)), 1), 1000)
            changed = True
        order = prior.order
        if any(token in followup for token in ("\u6700\u4f4e", "\u6700\u5c11", "\u5347\u5e8f")):
            order = "asc"
            changed = True
        elif any(
            token in followup
            for token in ("\u6700\u9ad8", "\u6700\u591a", "\u964d\u5e8f", "\u6392\u540d")
        ):
            order = "desc"
            changed = True

        if not changed:
            return None
        freshness = definition.get("freshness") or {}
        if time_range.kind not in {"latest", "today"} and not freshness.get(
            "supports_historical", False
        ):
            return None
        return BusinessQuery(
            metric_id=prior.metric_id,
            metric_name=prior.metric_name,
            dimensions=dimensions,
            filters=filters,
            time_range=time_range,
            query_type=query_type,
            order=order,
            limit=limit,
            confidence=1.0,
            evidence=evidence,
        )

    @staticmethod
    def _has_time_expression(question: str) -> bool:
        return bool(
            re.search(r"20\d{2}[-\u5e74/]\d{1,2}[-\u6708/]\d{1,2}", question)
            or any(
                token in question
                for token in (
                    "\u4eca\u5929",
                    "\u4eca\u65e5",
                    "\u6628\u5929",
                    "\u6628\u65e5",
                    "\u8fd1",
                    "\u6700\u8fd1",
                    "\u672c\u6708",
                    "\u8fd9\u4e2a\u6708",
                    "\u4e0a\u6708",
                    "\u4e0a\u4e2a\u6708",
                )
            )
        )

    @staticmethod
    def _match_metric(question: str, definitions: list[dict[str, Any]]) -> dict[str, Any] | None:
        normalized = question.lower()
        candidates: list[tuple[int, dict[str, Any]]] = []
        for definition in definitions:
            aliases = [str(definition.get("name") or ""), *definition.get("aliases", [])]
            matched = [alias for alias in aliases if alias and alias.lower() in normalized]
            context = definition.get("context_aliases") or {}
            context_terms = [str(item).lower() for item in context.get("terms", [])]
            if (
                not matched
                and any(str(alias).lower() in normalized for alias in context.get("aliases", []))
                and any(term in normalized for term in context_terms)
            ):
                matched = [str(context.get("aliases", [""])[0])]
            if not matched:
                continue
            specificity = max(len(alias) for alias in matched)
            candidates.append((specificity, definition))
        candidates.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
        return candidates[0][1] if candidates else None

    def _parse_time(self, question: str) -> QueryTimeRange:
        today = self._today()
        range_match = re.search(
            r"(20\d{2}-\d{1,2}-\d{1,2})\s*(?:\u5230|\u81f3|~|\u2014)\s*(20\d{2}-\d{1,2}-\d{1,2})",
            question,
        )
        if range_match:
            start = date.fromisoformat(range_match.group(1)).isoformat()
            end = date.fromisoformat(range_match.group(2)).isoformat()
            if start > end:
                start, end = end, start
            return QueryTimeRange("range", start, end, "\u6307\u5b9a\u533a\u95f4")
        explicit = re.search(r"(20\d{2})[-\u5e74/](\d{1,2})[-\u6708/](\d{1,2})\u65e5?", question)
        if explicit:
            value = date(*map(int, explicit.groups())).isoformat()
            return QueryTimeRange("date", value, value, value)
        recent = re.search(r"(?:近|最近)\s*(\d{1,3})\s*天", question)
        if recent:
            days = max(1, min(int(recent.group(1)), 366))
            return QueryTimeRange(
                "range",
                (today - timedelta(days=days - 1)).isoformat(),
                today.isoformat(),
                f"近{days}天",
            )
        if "昨天" in question or "昨日" in question:
            value = (today - timedelta(days=1)).isoformat()
            return QueryTimeRange("yesterday", value, value, "昨天")
        if "今天" in question or "今日" in question:
            value = today.isoformat()
            return QueryTimeRange("today", value, value, "今天")
        if "上个月" in question or "上月" in question:
            this_month = today.replace(day=1)
            end = this_month - timedelta(days=1)
            start = end.replace(day=1)
            return QueryTimeRange("range", start.isoformat(), end.isoformat(), "上个月")
        if "本月" in question or "这个月" in question:
            start = today.replace(day=1).isoformat()
            return QueryTimeRange("range", start, today.isoformat(), "本月")
        return QueryTimeRange()

    @staticmethod
    def _is_group_dimension(question: str, dimension: dict[str, Any]) -> bool:
        aliases = [str(dimension.get("name") or ""), *map(str, dimension.get("aliases", []))]
        aliases = [alias.removeprefix("各") for alias in aliases if alias]
        return any(
            marker in question
            for alias in aliases
            for marker in (f"各{alias}", f"按{alias}", f"分{alias}", f"{alias}排名", f"每个{alias}")
        )

    def _extract_dimension_value(self, question: str, dimension: dict[str, Any]) -> Any | None:
        values = dict(dimension.get("values") or {})
        if str(dimension.get("id")) == "platform":
            values = {**self._PLATFORM_VALUES, **values}
        for alias, canonical in sorted(values.items(), key=lambda item: -len(str(item[0]))):
            if str(alias).lower() in question.lower():
                return canonical

        pattern = str(dimension.get("value_pattern") or "")
        if pattern:
            match = re.search(pattern, question, re.I)
            if match:
                value = str(match.groupdict().get("value") or match.group(1)).strip()
                for prefix in ("今天", "今日", "昨天", "昨日", "查询", "查看", "统计"):
                    value = value.removeprefix(prefix)
                if value.startswith(("各", "按", "每个")):
                    return None
                return value
        return None
