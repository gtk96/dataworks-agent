"""Certified metric planning driven by semantic contracts and query understanding."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dataworks_agent.semantic.album_context import DataAlbumContext
from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase
from dataworks_agent.semantic.layer import SemanticLayer
from dataworks_agent.semantic.query_understanding import BusinessQuery, BusinessQueryUnderstanding

_METRICS_PATH = Path(__file__).with_name("metrics.json")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?$")
_RECONCILIATION_DATE_TOKEN = "__PRIMARY_DATA_DATE__"


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
    business_query: dict[str, Any] = field(default_factory=dict)

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
                "business_query": self.business_query,
                "caliber": self.caliber,
                "selection_evidence": self.selection_evidence,
                "metadata_validation": self.metadata_validation,
                "album_validation": self.album_validation,
                "grain_validation": self.grain_validation,
                "freshness_validation": self.freshness_validation,
            },
        }


class MetricQueryPlanner:
    """Resolve a question through approved contracts, schema linking and album evidence."""

    def __init__(
        self,
        definitions_path: Path | None = None,
        semantic_layer: SemanticLayer | None = None,
        knowledge_base: SemanticKnowledgeBase | None = None,
        query_understanding: BusinessQueryUnderstanding | None = None,
    ) -> None:
        layer = semantic_layer or SemanticLayer()
        self._knowledge_base = knowledge_base or SemanticKnowledgeBase(
            metrics_path=definitions_path or _METRICS_PATH,
            semantic_layer=layer,
        )
        self._query_understanding = query_understanding or BusinessQueryUnderstanding()

    def understand(self, question: str) -> tuple[BusinessQuery, dict[str, Any]] | None:
        return self._query_understanding.understand(question, self._definitions())

    def definition_for_metric(self, metric_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self._definitions() if str(item.get("id") or "") == metric_id),
            None,
        )

    def refine(
        self, followup: str, previous: BusinessQuery | dict[str, Any]
    ) -> BusinessQuery | None:
        prior = (
            previous if isinstance(previous, BusinessQuery) else BusinessQuery.from_dict(previous)
        )
        definition = self.definition_for_metric(prior.metric_id)
        if definition is None:
            return None
        return self._query_understanding.refine(followup, prior, definition)

    def candidate_tables_for_query(self, query: BusinessQuery | dict[str, Any]) -> set[str]:
        prior = query if isinstance(query, BusinessQuery) else BusinessQuery.from_dict(query)
        definition = self.definition_for_metric(prior.metric_id)
        if definition is None:
            return set()
        tables = {str(definition["table"])}
        reconciliation = definition.get("reconciliation") or {}
        if reconciliation.get("table"):
            tables.add(str(reconciliation["table"]))
        return tables

    def required_album_ids_for_query(self, query: BusinessQuery | dict[str, Any]) -> set[int]:
        prior = query if isinstance(query, BusinessQuery) else BusinessQuery.from_dict(query)
        definition = self.definition_for_metric(prior.metric_id)
        if definition is None:
            return set()
        provenance = definition.get("asset_provenance") or {}
        try:
            return {int(provenance["album_id"])} if provenance.get("album_id") else set()
        except (TypeError, ValueError):
            return set()

    def plan_frame(
        self,
        query: BusinessQuery | dict[str, Any],
        album_contexts: list[DataAlbumContext],
    ) -> MetricQueryPlan | None:
        prior = query if isinstance(query, BusinessQuery) else BusinessQuery.from_dict(query)
        definition = self.definition_for_metric(prior.metric_id)
        if definition is None:
            return None
        return self.plan_query(prior, definition, album_contexts)

    def candidate_tables(self, question: str) -> set[str]:
        understood = self.understand(question)
        if understood is None:
            return set()
        definition = understood[1]
        tables = {str(definition["table"])}
        reconciliation = definition.get("reconciliation") or {}
        if reconciliation.get("table"):
            tables.add(str(reconciliation["table"]))
        return tables

    def required_album_ids(self, question: str) -> set[int]:
        understood = self.understand(question)
        if understood is None:
            return set()
        provenance = understood[1].get("asset_provenance") or {}
        try:
            return {int(provenance["album_id"])} if provenance.get("album_id") else set()
        except (TypeError, ValueError):
            return set()

    def has_certified_metric(self, question: str) -> bool:
        return self.understand(question) is not None

    def plan(self, question: str, album_contexts: list[DataAlbumContext]) -> MetricQueryPlan | None:
        understood = self.understand(question)
        if understood is None:
            return None
        query, definition = understood
        return self.plan_query(query, definition, album_contexts)

    def plan_query(
        self,
        query: BusinessQuery,
        definition: dict[str, Any],
        album_contexts: list[DataAlbumContext],
    ) -> MetricQueryPlan:
        table = str(definition["table"])
        provenance = definition.get("asset_provenance") or {}
        required_album_id = int(provenance["album_id"])
        reconciliation = definition.get("reconciliation") or {}
        required_tables = [table]
        if reconciliation.get("table"):
            required_tables.append(str(reconciliation["table"]))
        matched_albums = self._albums_containing_tables(
            required_tables, album_contexts, required_album_id=required_album_id
        )
        selected_dimensions = self._selected_dimensions(query, definition)
        sql = self._build_sql(definition, query, selected_dimensions)
        reconciliation_sql = self._build_reconciliation_sql(definition, query, selected_dimensions)
        albums = [
            {"album_id": context.album_id, "name": context.name, "categories": context.categories}
            for context in album_contexts
            if context.album_id == required_album_id
        ]

        direct_match = bool(matched_albums)
        lineage = provenance.get("verified_lineage") if isinstance(provenance, dict) else None
        lineage_match = bool(
            provenance.get("type") == "verified_lineage"
            and lineage
            and any(context.album_id == required_album_id for context in album_contexts)
        )
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
        status = (
            "direct_match" if direct_match else "lineage_match" if lineage_match else "ungrounded"
        )
        album_validation = {
            "status": status,
            "certified_table_present": direct_match,
            "assets": matched_assets,
            "required_album_id": required_album_id,
            "required_tables": required_tables,
        }
        if lineage_match:
            album_validation["verified_lineage"] = lineage
        album_evidence = (
            f"数据专辑资产直接命中 {table}"
            if direct_match
            else f"数据专辑通过已验证血缘关联 {table}"
            if lineage_match
            else f"数据专辑未证明 {table} 的资产关系，禁止执行"
        )

        aggregation = str(definition["measure"].get("aggregation") or "").lower()
        grain_validation = {
            "status": "passed"
            if aggregation in {"sum", "count", "snapshot", "ratio"}
            else "failed",
            "aggregation": aggregation,
            "dimensions": [str(item["column"]) for item in selected_dimensions],
            "filters": query.filters,
            "query_type": query.query_type,
        }
        freshness = definition.get("freshness", {})
        freshness_validation = {
            "status": "passed" if freshness.get("date_partition") else "failed",
            "strategy": freshness.get("strategy", "latest_partition"),
            "date_partition": freshness.get("date_partition", ""),
            "business_date": freshness.get("business_date", ""),
            "hour_partition": freshness.get("hour_partition", ""),
            "requested_time": query.time_range.label,
            "requested_start": query.time_range.start,
            "requested_end": query.time_range.end,
        }
        metric_id = str(definition["id"])
        metric_name = str(definition.get("name") or metric_id)
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
                "asset_provenance": provenance,
                "reconciliation": reconciliation,
                "query_filters": query.filters,
            },
            selection_evidence=[
                f"已批准语义指标 {metric_name} ({metric_id})",
                album_evidence,
                "问句已结构化为指标、时间、维度、过滤、排序和限制",
            ],
            album_validation=album_validation,
            grain_validation=grain_validation,
            freshness_validation=freshness_validation,
            reconciliation_sql=reconciliation_sql,
            business_query=query.to_dict(),
        )

    def _definitions(self) -> list[dict[str, Any]]:
        return self._knowledge_base.approved_metrics()

    @staticmethod
    def _is_executable_definition(value: object) -> bool:
        return SemanticKnowledgeBase.is_executable_definition(value)

    @staticmethod
    def _albums_containing_tables(
        tables: list[str], contexts: list[DataAlbumContext], *, required_album_id: int
    ) -> list[DataAlbumContext]:
        required = {table.lower() for table in tables}
        return [
            context
            for context in contexts
            if context.album_id == required_album_id
            and required <= {candidate.full_name.lower() for candidate in context.tables}
        ]

    @staticmethod
    def _selected_dimensions(
        query: BusinessQuery, definition: dict[str, Any]
    ) -> list[dict[str, Any]]:
        selected = set(query.dimensions)
        return [
            dimension
            for dimension in definition.get("dimensions", [])
            if str(dimension.get("id") or dimension.get("column")) in selected
        ]

    def _build_sql(
        self,
        definition: dict[str, Any],
        query: BusinessQuery,
        selected_dimensions: list[dict[str, Any]],
        *,
        reconciliation_date: bool = False,
    ) -> str:
        table = self._safe_table(str(definition["table"]))
        measure = definition["measure"]
        measure_column = self._safe_identifier(str(measure["column"]))
        aggregation = str(measure.get("aggregation") or "").lower()
        measure_expression = self._aggregate_expression(aggregation, measure_column, measure)
        freshness = definition["freshness"]
        date_partition = self._safe_identifier(str(freshness["date_partition"]))
        business_date_value = freshness.get("business_date")
        business_date = (
            self._safe_identifier(str(business_date_value)) if business_date_value else ""
        )
        hour_value = freshness.get("hour_partition")
        hour_partition = self._safe_identifier(str(hour_value)) if hour_value else ""

        data_date_column = business_date or date_partition
        include_data_date = query.query_type == "trend" or query.time_range.kind != "range"
        select_lines: list[str] = []
        if include_data_date:
            select_lines.append(f"  {data_date_column} AS data_date")
        if hour_partition and include_data_date:
            select_lines.append(f"  {hour_partition} AS data_hour")
        for dimension in selected_dimensions:
            select_lines.append(f"  {self._safe_identifier(str(dimension['column']))}")
        measure_alias = (
            str(measure.get("alias") or measure_column)
            if selected_dimensions
            else f"total_{measure.get('alias') or measure_column}"
        )
        select_lines.append(f"  {measure_expression} AS {self._safe_identifier(measure_alias)}")

        partition_value = (
            self._literal(_RECONCILIATION_DATE_TOKEN)
            if reconciliation_date
            else f"MAX_PT('{table}')"
        )
        filters = [f"{date_partition} = {partition_value}"]
        if hour_partition:
            filters.append(
                f"{hour_partition} = (SELECT MAX({hour_partition}) FROM {table} "
                f"WHERE {date_partition} = {partition_value})"
            )
        if business_date and query.time_range.start:
            if query.time_range.kind == "range":
                filters.append(
                    f"{business_date} BETWEEN {self._literal(query.time_range.start)} "
                    f"AND {self._literal(query.time_range.end)}"
                )
            else:
                filters.append(f"{business_date} = {self._literal(query.time_range.start)}")
        for column, value in definition.get("fixed_filters", {}).items():
            filters.append(f"{self._safe_identifier(str(column))} = {self._literal(value)}")

        dimensions_by_id = {
            str(item.get("id") or item.get("column")): item
            for item in definition.get("dimensions", [])
        }
        selected_ids = {str(item.get("id") or item.get("column")) for item in selected_dimensions}
        for dimension_id, dimension in dimensions_by_id.items():
            if dimension_id in query.filters or dimension_id in selected_ids:
                continue
            if "total_value" not in dimension:
                continue
            column = self._safe_identifier(str(dimension["column"]))
            filters.append(f"{column} = {self._literal(dimension['total_value'])}")

        for dimension_id, value in query.filters.items():
            dimension = dimensions_by_id.get(str(dimension_id))
            if dimension is None:
                raise ValueError(f"unknown semantic filter dimension: {dimension_id}")
            column = self._safe_identifier(str(dimension["column"]))
            filters.append(f"{column} = {self._literal(value)}")

        lines = ["SELECT", ",\n".join(select_lines), f"FROM {table}", "WHERE"]
        lines.append("  " + "\n  AND ".join(filters))
        group_columns: list[str] = []
        if include_data_date:
            group_columns.append(data_date_column)
        if hour_partition and include_data_date:
            group_columns.append(hour_partition)
        group_columns.extend(
            self._safe_identifier(str(item["column"])) for item in selected_dimensions
        )
        if aggregation in {"sum", "count", "ratio"} and group_columns:
            lines.append("GROUP BY " + ", ".join(dict.fromkeys(group_columns)))
        if query.query_type == "trend":
            order_columns = [data_date_column]
            order_columns.extend(
                self._safe_identifier(str(item["column"])) for item in selected_dimensions
            )
            lines.append("ORDER BY " + ", ".join(dict.fromkeys(order_columns)) + " ASC")
            lines.append(f"LIMIT {query.limit}")
        elif selected_dimensions:
            direction = "ASC" if query.order == "asc" else "DESC"
            lines.append(f"ORDER BY {self._safe_identifier(measure_alias)} {direction}")
            lines.append(f"LIMIT {query.limit}")
        else:
            lines.append("LIMIT 1")
        return "\n".join(lines)

    def _build_reconciliation_sql(
        self,
        definition: dict[str, Any],
        query: BusinessQuery,
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
        if reconciliation.get("dimensions"):
            mirror["dimensions"] = reconciliation["dimensions"]
        return self._build_sql(mirror, query, selected_dimensions, reconciliation_date=True)

    @staticmethod
    def _aggregate_expression(
        aggregation: str, column: str, measure: dict[str, Any] | None = None
    ) -> str:
        if aggregation == "sum":
            return f"SUM({column})"
        if aggregation == "count":
            return "COUNT(*)"
        if aggregation == "snapshot":
            return column
        if aggregation == "ratio":
            denominator = MetricQueryPlanner._safe_identifier(str((measure or {})["denominator"]))
            return f"CASE WHEN SUM({denominator}) = 0 THEN NULL ELSE SUM({column}) / SUM({denominator}) END"
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
