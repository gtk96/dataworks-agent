"""Structured business knowledge used by conversational metric planning.

The knowledge base intentionally separates discoverable evidence from executable
metric contracts. Draft concepts can improve clarification, but only approved and
complete metric definitions may produce SQL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dataworks_agent.semantic.album_context import DataAlbumContext
from dataworks_agent.semantic.layer import SemanticLayer

_METRICS_PATH = Path(__file__).with_name("metrics.json")
_KNOWLEDGE_PATH = Path(__file__).with_name("knowledge.json")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeItem:
    item_id: str
    kind: str
    name: str
    aliases: list[str] = field(default_factory=list)
    status: str = "draft"
    description: str = ""
    unit: str = ""
    ambiguity: list[str] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    candidate_fields: list[str] = field(default_factory=list)
    candidate_dimensions: list[str] = field(default_factory=list)
    asset_candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    query_contract: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["id"] = value.pop("item_id")
        return value


@dataclass(frozen=True)
class KnowledgeMatch:
    item: KnowledgeItem
    score: int
    matched_aliases: list[str] = field(default_factory=list)
    album_evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = self.item.to_dict()
        value.update(
            {
                "score": self.score,
                "matched_aliases": self.matched_aliases,
                "album_evidence": self.album_evidence,
                "executable": bool(
                    self.item.status == "approved"
                    and self.item.query_contract
                    and SemanticKnowledgeBase.is_executable_definition(self.item.query_contract)
                ),
            }
        )
        return value


@dataclass(frozen=True)
class KnowledgeSearchResult:
    question: str
    matches: list[KnowledgeMatch] = field(default_factory=list)

    @property
    def clarifying_questions(self) -> list[str]:
        questions: list[str] = []
        for match in self.matches:
            for question in match.item.clarifying_questions:
                if question not in questions:
                    questions.append(question)
        return questions

    @property
    def missing_contract_fields(self) -> list[str]:
        fields: list[str] = []
        for match in self.matches:
            if match.item.status != "approved":
                fields.extend(["approved_status", "query_contract"])
            contract = match.item.query_contract or {}
            for key in ("table", "measure", "freshness", "asset_provenance"):
                if not contract.get(key):
                    fields.append(key)
        return list(dict.fromkeys(fields))

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "matches": [match.to_dict() for match in self.matches],
            "clarifying_questions": self.clarifying_questions,
            "missing_contract_fields": self.missing_contract_fields,
        }


class SemanticKnowledgeBase:
    """Merge approved contracts, draft business concepts, DB versions and album evidence."""

    def __init__(
        self,
        *,
        metrics_path: Path | None = None,
        knowledge_path: Path | None = None,
        semantic_layer: SemanticLayer | None = None,
    ) -> None:
        self._metrics_path = metrics_path or _METRICS_PATH
        self._knowledge_path = knowledge_path or _KNOWLEDGE_PATH
        self._semantic_layer = semantic_layer or SemanticLayer()

    def items(self) -> list[KnowledgeItem]:
        payload = self._read_json(self._knowledge_path)
        return [self._item_from_dict(item) for item in payload.get("items", [])]

    def search(
        self,
        question: str,
        album_contexts: list[DataAlbumContext] | None = None,
        *,
        limit: int = 5,
    ) -> KnowledgeSearchResult:
        normalized = question.strip().lower()
        matches: list[KnowledgeMatch] = []
        for item in self.items():
            aliases = [item.name, *item.aliases]
            matched = sorted(
                {alias for alias in aliases if alias and alias.lower() in normalized},
                key=lambda value: (-len(value), value),
            )
            if not matched:
                continue
            exact_bonus = 100 if any(alias.lower() == normalized for alias in matched) else 0
            specificity = max(len(alias) for alias in matched)
            score = exact_bonus + specificity * 10
            evidence = self._album_evidence(item, album_contexts or [])
            matches.append(
                KnowledgeMatch(
                    item=item,
                    score=score,
                    matched_aliases=matched,
                    album_evidence=evidence,
                )
            )
        matches.sort(key=lambda match: (-match.score, match.item.item_id))
        if matches:
            top_score = matches[0].score
            matches = [match for match in matches if match.score == top_score]
        return KnowledgeSearchResult(question=question, matches=matches[:limit])

    def approved_metric(self, question: str) -> dict[str, Any] | None:
        normalized = question.strip().lower()
        matches: list[tuple[int, dict[str, Any]]] = []
        for definition in self.approved_metrics():
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

    def approved_metrics(self) -> list[dict[str, Any]]:
        payload = self._read_json(self._metrics_path)
        baseline = {
            str(item["id"]): dict(item)
            for item in payload.get("metrics", [])
            if item.get("status") == "approved" and self.is_executable_definition(item)
        }
        versions = {key: int(value.get("version") or 1) for key, value in baseline.items()}
        try:
            approved = self._semantic_layer.list_definitions(kind="metric", status="approved")
        except Exception as exc:
            logger.warning("读取 approved 语义指标失败，回退版本化 baseline: %s", exc)
            approved = []
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
            if not self.is_executable_definition(candidate):
                continue
            if definition.version >= versions.get(metric_id, 0):
                baseline[metric_id] = candidate
                versions[metric_id] = definition.version
        return list(baseline.values())

    @staticmethod
    def is_executable_definition(value: object) -> bool:
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
            and provenance.get("type") in {"data_album", "verified_lineage"}
            and provenance.get("album_id")
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))

    @staticmethod
    def _item_from_dict(value: dict[str, Any]) -> KnowledgeItem:
        return KnowledgeItem(
            item_id=str(value["id"]),
            kind=str(value.get("kind") or "metric_concept"),
            name=str(value.get("name") or value["id"]),
            aliases=[str(item) for item in value.get("aliases", [])],
            status=str(value.get("status") or "draft"),
            description=str(value.get("description") or ""),
            unit=str(value.get("unit") or ""),
            ambiguity=[str(item) for item in value.get("ambiguity", [])],
            clarifying_questions=[str(item) for item in value.get("clarifying_questions", [])],
            candidate_fields=[str(item) for item in value.get("candidate_fields", [])],
            candidate_dimensions=[str(item) for item in value.get("candidate_dimensions", [])],
            asset_candidates=[dict(item) for item in value.get("asset_candidates", [])],
            evidence=[dict(item) for item in value.get("evidence", [])],
            query_contract=(
                dict(value["query_contract"])
                if isinstance(value.get("query_contract"), dict)
                else None
            ),
        )

    @staticmethod
    def _album_evidence(
        item: KnowledgeItem, contexts: list[DataAlbumContext]
    ) -> list[dict[str, Any]]:
        candidate_tables = {
            str(asset.get("table") or "").lower()
            for asset in item.asset_candidates
            if asset.get("table")
        }
        evidence: list[dict[str, Any]] = []
        for context in contexts:
            matched_tables = [
                table
                for table in context.tables
                if table.full_name.lower() in candidate_tables
                or any(
                    alias and alias.lower() in f"{table.comment} {table.remark}".lower()
                    for alias in [item.name, *item.aliases]
                )
            ]
            if not matched_tables:
                continue
            evidence.append(
                {
                    "album_id": context.album_id,
                    "album": context.name,
                    "tables": [table.full_name for table in matched_tables],
                }
            )
        return evidence
