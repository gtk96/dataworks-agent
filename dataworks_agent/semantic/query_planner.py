"""Certified metric planning driven by DataWorks albums and semantic contracts."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dataworks_agent.semantic.album_context import DataAlbumContext
from dataworks_agent.semantic.layer import SemanticLayer

_METRICS_PATH = Path(__file__).with_name("metrics.json")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?$")
logger = logging.getLogger(__name__)


@dataclass
class MetricQueryPlan:
    sql: str
    metric_id: str
    metric_name: str
    metric_version: int
    table: str
    albums: list[dict[str, Any]] = field(default_factory=list)
    selected_dimensions: list[str] = field(default_factory=list)
    caliber: dict[str, Any] = field(default_factory=dict)
    selection_evidence: list[str] = field(default_factory=list)
    metadata_validation: dict[str, Any] = field(default_factory=dict)
    album_validation: dict[str, Any] = field(default_factory=dict)

    def semantic_artifact(self) -> dict[str, Any]:
        return {
            "type": "semantic_query_plan",
            "name": self.metric_id,
            "content": {
                "metric_id": self.metric_id,
                "metric_name": self.metric_name,
                "metric_version": self.metric_version,
                "table": self.table,
                "albums": self.albums,
                "selected_dimensions": self.selected_dimensions,
                "caliber": self.caliber,
                "selection_evidence": self.selection_evidence,
                "metadata_validation": self.metadata_validation,
                "album_validation": self.album_validation,
            },
        }


class MetricQueryPlanner:
    """Resolve a question through approved semantic contracts and album membership."""

    def __init__(
        self,
        definitions_path: Path | None = None,
        semantic_layer: SemanticLayer | None = None,
    ) -> None:
        self._definitions_path = definitions_path or _METRICS_PATH
        self._semantic_layer = semantic_layer or SemanticLayer()

    def candidate_tables(self, question: str) -> set[str]:
        definition = self._match_metric(question)
        return {str(definition["table"])} if definition is not None else set()

    def has_certified_metric(self, question: str) -> bool:
        return self._match_metric(question) is not None

    def plan(
        self,
        question: str,
        album_contexts: list[DataAlbumContext],
    ) -> MetricQueryPlan | None:
        definition = self._match_metric(question)
        if definition is None:
            return None

        table = str(definition["table"])
        matched_albums = self._albums_containing_table(table, album_contexts)
        supporting_albums = matched_albums or album_contexts[:1]

        selected_dimensions = self._selected_dimensions(question, definition)
        sql = self._build_sql(definition, selected_dimensions)
        albums = [
            {
                "album_id": context.album_id,
                "name": context.name,
                "categories": context.categories,
            }
            for context in supporting_albums
        ]
        metric_id = str(definition["id"])
        metric_name = str(definition.get("name") or metric_id)
        if matched_albums:
            album_validation = {
                "status": "direct_match",
                "certified_table_present": True,
            }
            album_evidence = f"官方表 {table} 已在数据专辑中直接命中"
        elif supporting_albums:
            album_validation = {
                "status": "domain_context",
                "certified_table_present": False,
            }
            album_evidence = (
                f"数据专辑已命中业务域，但未收录官方表 {table}；"
                "最终表由 approved 指标定义决定，并须通过真实 DDL 校验"
            )
        else:
            album_validation = {
                "status": "unavailable",
                "certified_table_present": False,
            }
            album_evidence = (
                "数据专辑当前未返回候选；仅允许 approved 指标定义在真实 DDL 校验通过后执行"
            )
        evidence = [
            f"问题命中已批准指标 {metric_name} ({metric_id})",
            album_evidence,
            "查询口径来自版本化语义定义，而非对话代码分支",
        ]
        return MetricQueryPlan(
            sql=sql,
            metric_id=metric_id,
            metric_name=metric_name,
            metric_version=int(definition.get("version") or 1),
            table=table,
            albums=albums,
            selected_dimensions=[str(item["name"]) for item in selected_dimensions],
            caliber={
                "measure": definition["measure"],
                "fixed_filters": definition.get("fixed_filters", {}),
                "dimensions": definition.get("dimensions", []),
                "freshness": definition.get("freshness", {}),
                "description": definition.get("description", ""),
                "source": definition.get("source", ""),
            },
            selection_evidence=evidence,
            album_validation=album_validation,
        )

    def _definitions(self) -> list[dict[str, Any]]:
        payload = json.loads(self._definitions_path.read_text(encoding="utf-8-sig"))
        baseline = {
            str(item["id"]): dict(item)
            for item in payload.get("metrics", [])
            if self._is_executable_definition(item) and item.get("status") == "approved"
        }
        try:
            approved = self._semantic_layer.list_definitions(kind="metric", status="approved")
        except Exception as exc:
            logger.warning(
                "读取 approved 语义指标失败，回退版本化 baseline: %s",
                exc,
            )
            approved = []

        versions = {key: int(value.get("version") or 1) for key, value in baseline.items()}
        for definition in approved:
            body = definition.body.get("query_contract", definition.body)
            if not isinstance(body, dict):
                continue
            candidate = dict(body)
            candidate.setdefault("id", definition.key)
            candidate["version"] = definition.version
            candidate["status"] = "approved"
            candidate.setdefault("source", definition.source)
            metric_id = str(candidate.get("id") or "")
            if not self._is_executable_definition(candidate):
                logger.warning(
                    "忽略不完整的 approved 指标定义: %s",
                    definition.key,
                )
                continue
            if definition.version >= versions.get(metric_id, 0):
                baseline[metric_id] = candidate
                versions[metric_id] = definition.version
        return list(baseline.values())

    @staticmethod
    def _is_executable_definition(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        measure = value.get("measure")
        freshness = value.get("freshness")
        return bool(
            value.get("id")
            and value.get("table")
            and isinstance(measure, dict)
            and measure.get("column")
            and isinstance(freshness, dict)
            and freshness.get("date_partition")
            and freshness.get("hour_partition")
        )

    def _match_metric(self, question: str) -> dict[str, Any] | None:
        normalized = question.strip().lower()
        matches: list[tuple[int, dict[str, Any]]] = []
        for definition in self._definitions():
            time_terms = [str(item) for item in definition.get("time_terms", [])]
            if time_terms and not any(term in question for term in time_terms):
                continue
            aliases = [str(definition.get("name") or ""), *definition.get("aliases", [])]
            score = max(
                (len(alias) for alias in aliases if alias and alias.lower() in normalized),
                default=0,
            )
            if score:
                matches.append((score, definition))
        matches.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
        return matches[0][1] if matches else None

    @staticmethod
    def _albums_containing_table(
        table: str,
        contexts: list[DataAlbumContext],
    ) -> list[DataAlbumContext]:
        normalized = table.lower()
        return [
            context
            for context in contexts
            if any(candidate.full_name.lower() == normalized for candidate in context.tables)
        ]

    @staticmethod
    def _selected_dimensions(question: str, definition: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dimension
            for dimension in definition.get("dimensions", [])
            if any(str(alias) in question for alias in dimension.get("aliases", []))
        ]

    def _build_sql(
        self,
        definition: dict[str, Any],
        selected_dimensions: list[dict[str, Any]],
    ) -> str:
        table = self._safe_table(str(definition["table"]))
        measure = definition["measure"]
        measure_column = self._safe_identifier(str(measure["column"]))
        date_partition = self._safe_identifier(str(definition["freshness"]["date_partition"]))
        hour_partition = self._safe_identifier(str(definition["freshness"]["hour_partition"]))

        select_lines = [
            f"  {date_partition} AS data_date",
            f"  {hour_partition} AS data_hour",
        ]
        for dimension in selected_dimensions:
            select_lines.append(f"  {self._safe_identifier(str(dimension['column']))}")
        measure_alias = (
            str(measure.get("alias") or measure_column)
            if selected_dimensions
            else f"total_{measure.get('alias') or measure_column}"
        )
        select_lines.append(f"  {measure_column} AS {self._safe_identifier(measure_alias)}")

        filters = [
            f"{date_partition} = MAX_PT('{table}')",
            (
                f"{hour_partition} = (SELECT MAX({hour_partition}) FROM {table} "
                f"WHERE {date_partition} = MAX_PT('{table}'))"
            ),
        ]
        selected_ids = {str(item["id"]) for item in selected_dimensions}
        for column, value in definition.get("fixed_filters", {}).items():
            filters.append(f"{self._safe_identifier(str(column))} = {self._literal(value)}")
        for dimension in definition.get("dimensions", []):
            column = self._safe_identifier(str(dimension["column"]))
            total_value = dimension.get("total_value")
            if total_value is None:
                continue
            operator = "<>" if str(dimension["id"]) in selected_ids else "="
            filters.append(f"{column} {operator} {self._literal(total_value)}")

        lines = ["SELECT", ",\n".join(select_lines), f"FROM {table}", "WHERE"]
        lines.append("  " + "\n  AND ".join(filters))
        if selected_dimensions:
            lines.append(f"ORDER BY {measure_column} DESC")
        else:
            lines.append("LIMIT 2")
        return "\n".join(lines)

    @staticmethod
    def _safe_identifier(value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"unsafe semantic identifier: {value}")
        return value

    @staticmethod
    def _safe_table(value: str) -> str:
        if not _TABLE_RE.fullmatch(value):
            raise ValueError(f"unsafe semantic table: {value}")
        return value

    @staticmethod
    def _literal(value: object) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"
