"""Extract draft semantic metric evidence from production SQL.

Extraction never approves a metric. It records inspectable SQL evidence so a human
can complete and approve a query contract through the semantic layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlglot import exp, parse


@dataclass(frozen=True)
class MetricCandidate:
    candidate_id: str
    name: str
    expression: str
    alias: str = ""
    aggregation: str = ""
    source_tables: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    case_when: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeExtractionResult:
    candidates: list[MetricCandidate] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "tables": self.tables,
            "dimensions": self.dimensions,
            "filters": self.filters,
            "parse_errors": self.parse_errors,
        }


class SQLKnowledgeExtractor:
    """Parse SQL into auditable draft metric candidates."""

    def extract(
        self,
        sql: str,
        *,
        source: dict[str, Any] | None = None,
        dialect: str = "hive",
    ) -> KnowledgeExtractionResult:
        statements = []
        errors: list[str] = []
        try:
            statements = parse(sql, read=dialect)
        except Exception as exc:
            errors.append(str(exc))
        if not statements:
            return KnowledgeExtractionResult(parse_errors=errors or ["SQL 中没有可解析语句"])

        tables = self._unique(
            table.sql(dialect=dialect)
            for statement in statements
            for table in statement.find_all(exp.Table)
        )
        filters = self._unique(
            where.this.sql(dialect=dialect)
            for statement in statements
            for where in statement.find_all(exp.Where)
        )
        dimensions = self._unique(
            item.sql(dialect=dialect)
            for statement in statements
            for group in statement.find_all(exp.Group)
            for item in group.expressions
        )
        candidates: list[MetricCandidate] = []
        source_meta = dict(source or {})
        for statement_index, statement in enumerate(statements, start=1):
            for select in statement.find_all(exp.Select):
                select_dimensions = self._select_dimensions(select, dialect)
                for expression in select.expressions:
                    metric_expression = (
                        expression.this if isinstance(expression, exp.Alias) else expression
                    )
                    aggregates = list(metric_expression.find_all(exp.AggFunc))
                    cases = list(metric_expression.find_all(exp.Case))
                    if not aggregates and not cases:
                        continue
                    alias = expression.alias_or_name if isinstance(expression, exp.Alias) else ""
                    rendered = metric_expression.sql(dialect=dialect)
                    fingerprint = "|".join(
                        [rendered, alias, ",".join(tables), str(statement_index)]
                    )
                    candidate_id = "sql_" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
                    candidate_source = {**source_meta, "statement_index": statement_index}
                    candidates.append(
                        MetricCandidate(
                            candidate_id=candidate_id,
                            name=alias or rendered,
                            expression=rendered,
                            alias=alias,
                            aggregation=aggregates[0].key.upper() if aggregates else "CASE",
                            source_tables=tables,
                            dimensions=select_dimensions or dimensions,
                            filters=filters,
                            case_when=[case.sql(dialect=dialect) for case in cases],
                            source=candidate_source,
                        )
                    )
        return KnowledgeExtractionResult(
            candidates=candidates,
            tables=tables,
            dimensions=dimensions,
            filters=filters,
            parse_errors=errors,
        )

    @staticmethod
    def _select_dimensions(select: exp.Select, dialect: str) -> list[str]:
        group = select.args.get("group")
        if not isinstance(group, exp.Group):
            return []
        return SQLKnowledgeExtractor._unique(
            expression.sql(dialect=dialect) for expression in group.expressions
        )

    @staticmethod
    def _unique(values: Any) -> list[str]:
        return list(dict.fromkeys(str(value) for value in values if str(value)))
