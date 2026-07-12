"""Read-only DataWorks data-album context for semantic table selection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_RE = re.compile(r"[a-z0-9]+")
_LAYER_BONUS = {"rp": 5.0, "dmr": 5.0, "dws": 4.0, "dwd": 2.0, "dim": 1.5, "ods": 0.0}


@dataclass(frozen=True)
class AlbumTable:
    project: str
    name: str
    comment: str = ""
    remark: str = ""
    entity_type: str = "odps-table"
    category: str = ""
    score: float = 0.0

    @property
    def full_name(self) -> str:
        return f"{self.project}.{self.name}" if self.project else self.name


@dataclass(frozen=True)
class DataAlbumContext:
    album_id: int
    name: str
    description: str = ""
    categories: list[str] = field(default_factory=list)
    tables: list[AlbumTable] = field(default_factory=list)
    score: float = 0.0


class DataAlbumContextResolver:
    """Resolve business questions to a small, metadata-only album context."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any | None:
        return self._client or getattr(app_state, "_bff_client", None)

    async def resolve(
        self,
        question: str,
        *,
        max_albums: int = 3,
        max_tables: int = 12,
        required_tables: set[str] | None = None,
    ) -> list[DataAlbumContext]:
        client = self.client
        if client is None:
            return []

        query_tokens = _tokens(question)
        if not query_tokens:
            return []

        try:
            albums = await client.list_meta_albums(page_size=100)
            ranked = self._rank_albums(albums, question, query_tokens)[:max_albums]
            contexts: list[DataAlbumContext] = []
            for album_score, album in ranked:
                album_id = _as_int(album.get("id") or album.get("albumId"))
                if album_id is None:
                    continue
                categories = await client.list_meta_album_categories(album_id)
                category_names, category_map = _flatten_categories(categories)
                entities = await client.list_meta_album_entities(
                    album_id,
                    page_size=500,
                    entity_type="odps-table",
                )
                tables = self._rank_tables(
                    entities,
                    query_tokens,
                    category_map,
                    max_tables=max_tables,
                    required_tables=required_tables or set(),
                )
                category_score = _field_score(" ".join(category_names), query_tokens, 1.5)
                contexts.append(
                    DataAlbumContext(
                        album_id=album_id,
                        name=str(album.get("albumName") or album.get("name") or ""),
                        description=str(album.get("albumDesc") or album.get("description") or ""),
                        categories=category_names,
                        tables=tables,
                        score=album_score + category_score,
                    )
                )
            return sorted(contexts, key=lambda item: item.score, reverse=True)
        except Exception as exc:
            logger.warning("Data album context unavailable; continuing without it: %s", exc)
            return []

    @staticmethod
    def _rank_albums(
        albums: list[dict],
        question: str,
        query_tokens: set[str],
    ) -> list[tuple[float, dict]]:
        ranked: list[tuple[float, dict]] = []
        normalized_question = question.lower()
        for album in albums:
            name = str(album.get("albumName") or album.get("name") or "")
            description = str(album.get("albumDesc") or album.get("description") or "")
            score = _field_score(name, query_tokens, 3.0)
            score += _field_score(description, query_tokens, 1.0)
            if name and name.lower() in normalized_question:
                score += 12.0
            if score > 0:
                ranked.append((score, album))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("albumName") or "")))
        return ranked

    @staticmethod
    def _rank_tables(
        entities: list[dict],
        query_tokens: set[str],
        category_map: dict[int, str],
        *,
        max_tables: int,
        required_tables: set[str] | None = None,
    ) -> list[AlbumTable]:
        ranked: list[AlbumTable] = []
        for entity in entities:
            name = str(entity.get("table_name") or entity.get("name") or "")
            if not name:
                continue
            comment = str(entity.get("comment") or "")
            remark = str(entity.get("remark") or "")
            category_id = _as_int(entity.get("category_id") or entity.get("categoryId"))
            category = category_map.get(category_id, "") if category_id is not None else ""
            semantic_score = _field_score(name, query_tokens, 3.0)
            semantic_score += _field_score(comment, query_tokens, 4.0)
            semantic_score += _field_score(remark, query_tokens, 6.0)
            semantic_score += _field_score(category, query_tokens, 2.0)
            layer = _table_layer(name)
            score = semantic_score + _LAYER_BONUS.get(layer, 0.0)
            ranked.append(
                AlbumTable(
                    project=str(entity.get("project") or entity.get("databaseName") or ""),
                    name=name,
                    comment=comment,
                    remark=remark,
                    entity_type=str(entity.get("entity_type") or entity.get("entityType") or ""),
                    category=category,
                    score=score,
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.full_name))
        selected = ranked[:max_tables]
        required = {item.lower() for item in (required_tables or set())}
        selected_names = {item.full_name.lower() for item in selected}
        for candidate in ranked:
            if (
                candidate.full_name.lower() in required
                and candidate.full_name.lower() not in selected_names
            ):
                selected.append(candidate)
                selected_names.add(candidate.full_name.lower())
        return selected

    @staticmethod
    def format_for_llm(contexts: list[DataAlbumContext]) -> str:
        """Render only metadata, never production rows, into the LLM prompt."""
        if not contexts:
            return ""
        lines = [
            "DataWorks data albums (candidate-table metadata only):",
            "- Use albums only to narrow candidate assets; never infer metric formulas or filters from them.",
            "- Prefer approved semantic definitions/recipes for metric caliber. If caliber is unknown, ask for clarification rather than inventing it.",
        ]
        for context in contexts:
            lines.append(f"Album: {context.name} (id={context.album_id})")
            if context.description:
                lines.append(f"  Description: {context.description}")
            if context.categories:
                lines.append(f"  Categories: {', '.join(context.categories[:20])}")
            for table in context.tables:
                details = [part for part in (table.comment, table.remark, table.category) if part]
                suffix = f" -- {' | '.join(details)}" if details else ""
                lines.append(f"  Table: {table.full_name}{suffix}")
        return "\n".join(lines)


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    tokens = {token for token in _ASCII_RE.findall(normalized) if len(token) >= 2}
    for sequence in _CJK_RE.findall(normalized):
        if 2 <= len(sequence) <= 8:
            tokens.add(sequence)
        for size in range(2, min(4, len(sequence)) + 1):
            tokens.update(
                sequence[index : index + size] for index in range(len(sequence) - size + 1)
            )
    return tokens


def _field_score(text: str, tokens: set[str], weight: float) -> float:
    normalized = text.lower()
    return sum(weight * max(1, len(token) - 1) for token in tokens if token in normalized)


def _table_layer(name: str) -> str:
    lowered = name.lower()
    match = re.search(r"(?:^|_)(ods|dwd|dim|dws|dmr|rp)(?:_|$)", lowered)
    return match.group(1) if match else ""


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _flatten_categories(categories: list[dict]) -> tuple[list[str], dict[int, str]]:
    names: list[str] = []
    mapping: dict[int, str] = {}

    def visit(items: list[dict], parents: list[str]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("categoryName") or item.get("name") or "").strip()
            path = [*parents, name] if name else parents
            label = " / ".join(path)
            category_id = _as_int(item.get("id") or item.get("categoryId"))
            if name and name not in names:
                names.append(name)
            if category_id is not None and label:
                mapping[category_id] = label
            children = item.get("children") or item.get("childList") or item.get("subCategories")
            if isinstance(children, list):
                visit(children, path)

    visit(categories, [])
    return names, mapping
