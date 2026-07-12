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
    grain_validation: dict[str, Any] = field(default_factory=dict)
    freshness_validation: dict[str, Any] = field(default_factory=dict)
    reconciliation_sql: str = ""

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
                "grain_validation": self.grain_validation,
                "freshness_validation": self.freshness_validation,
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

    def required_album_ids(self, question: str) -> set[int]:
        definition = self._match_metric(question)
        if definition is None:
            return set()
        provenance = definition.get("asset_provenance") or {}
        album_id = provenance.get("album_id") if isinstance(provenance, dict) else None
        try:
            return {int(album_id)} if album_id is not None else set()
        except (TypeError, ValueError):
            return set()

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
        provenance = definition.get("asset_provenance") or {}
        required_album_id = int(provenance["album_id"])
        reconciliation = definition.get("reconciliation") or {}
        required_tables = [table]
        if reconciliation.get("table"):
            required_tables.append(str(reconciliation["table"]))
        matched_albums = self._albums_containing_tables(
            required_tables,
            album_contexts,
            required_album_id=required_album_id,
        )
        selected_dimensions = self._selected_dimensions(question, definition)
        sql = self._build_sql(definition, selected_dimensions)
        reconciliation_sql = self._build_reconciliation_sql(definition, selected_dimensions)
        albums = [
            {
                "album_id": context.album_id,
                "name": context.name,
                "categories": context.categories,
            }
            for context in matched_albums
        ]
        metric_id = str(definition["id"])
        metric_name = str(definition.get("name") or metric_id)
        if matched_albums:
            matched_assets = [
                {
                    "table": candidate.full_name,
                    "entity_guid": candidate.entity_guid,
                    "qualified_name": candidate.qualified_name,
                    "relation_id": candidate.relation_id,
                }
                for context in matched_albums
                for candidate in context.tables
                if candidate.full_name.lower() in {item.lower() for item in required_tables}
            ]
            album_validation = {
                "status": "direct_match",
                "certified_table_present": True,
                "assets": matched_assets,
                "required_album_id": required_album_id,
                "required_tables": required_tables,
            }
            album_evidence = f"数据专辑资产直接命中 {table}"
        else:
            album_validation = {
                "status": "ungrounded",
                "certified_table_present": False,
                "assets": [],
                "required_album_id": required_album_id,
                "required_tables": required_tables,
            }
            album_evidence = f"数据专辑未证明 {table} 的资产关系，禁止执行"

        aggregation = str(definition["measure"].get("aggregation") or "").lower()
        grain_validation = {
            "status": "passed" if aggregation in {"sum", "count", "snapshot"} else "failed",
            "aggregation": aggregation,
            "dimensions": [str(item["column"]) for item in selected_dimensions],
        }
        freshness = definition.get("freshness", {})
        freshness_validation = {
            "status": "passed" if freshness.get("date_partition") else "failed",
            "strategy": freshness.get("strategy", "latest_partition"),
            "date_partition": freshness.get("date_partition", ""),
            "hour_partition": freshness.get("hour_partition", ""),
        }
        evidence = [
            f"已批准语义指标 {metric_name} ({metric_id})",
            album_evidence,
            "查询须通过专辑资产、DDL 字段、粒度、时效和 DWS/DWD 对账验收",
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
                "freshness": freshness,
                "description": definition.get("description", ""),
                "source": definition.get("source", ""),
                "asset_provenance": definition.get("asset_provenance", {}),
                "reconciliation": definition.get("reconciliation", {}),
            },
            selection_evidence=evidence,
            album_validation=album_validation,
            grain_validation=grain_validation,
            freshness_validation=freshness_validation,
            reconciliation_sql=reconciliation_sql,
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
                logger.debug(
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
        provenance = value.get("asset_provenance")
        return bool(
            value.get("id")
            and value.get("table")
            and isinstance(measure, dict)
            and measure.get("column")
            and measure.get("aggregation")
            and isinstance(freshness, dict)
            and freshness.get("date_partition")
            and isinstance(provenance, dict)
            and provenance.get("type") == "data_album"
            and provenance.get("album_id")
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
    def _albums_containing_tables(
        tables: list[str],
        contexts: list[DataAlbumContext],
        *,
        required_album_id: int,
    ) -> list[DataAlbumContext]:
        required = {table.lower() for table in tables}
        return [
            context
            for context in contexts
            if context.album_id == required_album_id
            and required <= {candidate.full_name.lower() for candidate in context.tables}
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
        aggregation = str(measure.get("aggregation") or "").lower()
        measure_expression = self._aggregate_expression(aggregation, measure_column)
        freshness = definition["freshness"]
        date_partition = self._safe_identifier(str(freshness["date_partition"]))
        hour_value = freshness.get("hour_partition")
        hour_partition = self._safe_identifier(str(hour_value)) if hour_value else ""

        select_lines = [f"  {date_partition} AS data_date"]
        if hour_partition:
            select_lines.append(f"  {hour_partition} AS data_hour")
        for dimension in selected_dimensions:
            select_lines.append(f"  {self._safe_identifier(str(dimension['column']))}")
        measure_alias = (
            str(measure.get("alias") or measure_column)
            if selected_dimensions
            else f"total_{measure.get('alias') or measure_column}"
        )
        select_lines.append(f"  {measure_expression} AS {self._safe_identifier(measure_alias)}")

        filters = [f"{date_partition} = MAX_PT('{table}')"]
        if hour_partition:
            filters.append(
                f"{hour_partition} = (SELECT MAX({hour_partition}) FROM {table} "
                f"WHERE {date_partition} = MAX_PT('{table}'))"
            )
        for column, value in definition.get("fixed_filters", {}).items():
            filters.append(f"{self._safe_identifier(str(column))} = {self._literal(value)}")

        lines = ["SELECT", ",\n".join(select_lines), f"FROM {table}", "WHERE"]
        lines.append("  " + "\n  AND ".join(filters))
        group_columns = [date_partition]
        if hour_partition:
            group_columns.append(hour_partition)
        group_columns.extend(
            self._safe_identifier(str(item["column"])) for item in selected_dimensions
        )
        if aggregation in {"sum", "count"}:
            lines.append("GROUP BY " + ", ".join(group_columns))
        if selected_dimensions:
            lines.append(f"ORDER BY {self._safe_identifier(measure_alias)} DESC")
        else:
            lines.append("LIMIT 1")
        return "\n".join(lines)

    def _build_reconciliation_sql(
        self,
        definition: dict[str, Any],
        selected_dimensions: list[dict[str, Any]],
    ) -> str:
        reconciliation = definition.get("reconciliation")
        if not isinstance(reconciliation, dict) or not reconciliation.get("table"):
            return ""
        mirror = dict(definition)
        mirror["table"] = reconciliation["table"]
        mirror["measure"] = reconciliation["measure"]
        mirror["fixed_filters"] = reconciliation.get("fixed_filters", {})
        mirror["freshness"] = reconciliation.get("freshness", definition["freshness"])
        return self._build_sql(mirror, selected_dimensions)

    @staticmethod
    def _aggregate_expression(aggregation: str, column: str) -> str:
        if aggregation == "sum":
            return f"SUM({column})"
        if aggregation == "count":
            return "COUNT(*)"
        if aggregation == "snapshot":
            return column
        raise ValueError(f"unsupported semantic aggregation: {aggregation}")

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
