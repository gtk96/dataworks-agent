"""Metadata provider — search the DataMap + BFF for tables matching a keyword.

This module replaces the inline ``_resolve_table_via_bff_search`` logic
previously embedded in :class:`AgentWorkflowService`. The provider:

- Caches both album-resolve and per-keyword BFF search results so the
  same hot keyword does not repeatedly hit DataMap / BFF endpoints.
- Reuses the existing rule-based scoring (album hit > ref_count) and
  noise filters (redacted project names, ``*`` placeholders, single-char
  keywords, table-name suffix based layer filter).
- Exposes a structured :class:`MetadataQueryResult` so the planner /
  LLM prompt assembler can format the candidate list once and reuse
  it across multiple paths.

This is the ``MetadataProvider`` from
``docs/product/conversational-dialog-design.md`` §2.2 — the next phase
will reuse its output to inject tables into the LLM prompt.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.api_clients.provider_errors import ProviderError, ProviderUnavailableError
from dataworks_agent.config import settings
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


_CJK_RE = re.compile(r"[一-鿿]+")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Curated album hints. The provider looks up keyword → album_id first to
# avoid scoring the full album list on every chat call.
_ASK_DOMAIN_ALBUM_HINTS: dict[str, int] = {
    "订单": 436,  # 订单数据（ods 层）订单
    "订单信息": 436,
    "订单明细": 436,
    "客户订单": 436,
    "用户订单": 436,
    "订单模型": 328,
    "订单汇总": 328,
    "订单汇总模型": 328,
}


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class MetadataQueryResult:
    """Output of :meth:`MetadataProvider.search_table`."""

    keyword: str
    album: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    declined: bool = False  # True when the resolver defers to the semantic layer

    @property
    def top(self) -> dict[str, Any] | None:
        return self.candidates[0] if self.candidates else None

    def render_for_llm(self, *, limit: int = 20) -> str:
        """LLM-prompt-ready list of the top candidates."""
        if not self.candidates:
            return "（未搜索到匹配的物理表，请用户提供英文表名或更具体的关键词）"
        rows = self.candidates[:limit]
        lines = [f"## 当前数据仓库中匹配的表 (top {len(rows)}):"]
        for item in rows:
            lines.append(
                "- {full} ({layer}层, album={album}, ref_count={ref_count})".format(
                    full=item.get("full_name") or "?",
                    layer=item.get("layer") or "?",
                    album=item.get("album_name") or "-",
                    ref_count=item.get("ref_count") or 0,
                )
            )
        return "\n".join(lines)

    def to_prompt_payload(self, *, limit: int = 20) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "album": self.album,
            "tables": [
                {
                    "full_name": item.get("full_name"),
                    "layer": item.get("layer"),
                    "comment": item.get("comment"),
                    "album": item.get("album_name"),
                    "ref_count": item.get("ref_count"),
                    "entity_guid": item.get("entity_guid"),
                }
                for item in self.candidates[:limit]
            ],
        }


class MetadataProvider:
    """Cache + resolve DataMap / Cookie BFF candidates for a Chinese keyword.

    Lives in app_state so the rule-based planner and (future) LLM
    prompt assembler share the same per-keyword cache. The provider is
    safe to construct multiple times — caches are keyed off app_state.
    """

    def __init__(self, *, cache_ttl_seconds: float | None = None) -> None:
        self._cache_ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.ask_data_album_cache_seconds
        )
        # Per-keyword BFF search cache. The album resolve cache lives
        # directly on app_state (shared with workflow_service).
        self._search_cache: dict[str, tuple[float, MetadataQueryResult]] = {}

    @staticmethod
    def extract_keyword(message: str, params: dict[str, Any] | None = None) -> str:
        """Strip chat verbs to a bare Chinese / English noun."""
        params = params or {}
        for key in ("table_name", "source_table", "keyword"):
            value = str(params.get(key) or "").strip()
            if value and not _looks_like_physical_table(value):
                cleaned = value.removesuffix("表").strip() or value
                if len(cleaned) >= 2:
                    return cleaned
        text = message.strip()
        text = re.sub(
            r"^(?:请)?(?:帮我)?(?:查(?:询|看)?|检索|找|看){1,3}(?:一下|一|下)?",
            "",
            text,
        )
        match = re.search(r"([一-龥A-Za-z0-9_]{2,24})表", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"([一-龥A-Za-z0-9_]{2,24})表", message)
        if match:
            return match.group(1).strip()
        return ""

    async def search_table(
        self,
        keyword: str,
        message: str,
        *,
        force_refresh: bool = False,
    ) -> MetadataQueryResult | None:
        """Return candidates for ``keyword``; ``None`` when the provider
        chooses to defer (single weak signal) or refuses (no keyword)."""
        keyword = (keyword or "").strip()
        if not keyword:
            return None
        now = time.monotonic()
        cached = self._search_cache.get(keyword)
        if cached is not None and now - cached[0] < self._cache_ttl:
            return cached[1]

        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return None

        album = await self._resolve_keyword_album(keyword)
        album_entities: list[dict[str, Any]] = []
        if album is not None:
            try:
                album_entities = await bff.list_meta_album_entities(
                    album["album_id"], page_size=500
                )
            except Exception as exc:
                logger.warning(
                    "list_meta_album_entities(%s) 失败: %s",
                    album,
                    exc,
                )
                album_entities = []

        try:
            tables = await bff.search_tables(keyword)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                "bff_search_failed",
                type(exc).__name__,
                provider="cookie_bff",
            ) from exc

        merged, candidates = self._merge(
            keyword=keyword,
            album=album,
            album_entities=album_entities,
            tables=tables,
        )
        result = self._shape_candidates(
            candidates=candidates,
            merged=merged,
            album=album,
            keyword=keyword,
        )
        if result is None:
            self._search_cache[keyword] = (now, MetadataQueryResult(keyword=keyword))
            return None
        self._search_cache[keyword] = (now, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_keyword_album(self, keyword: str) -> dict[str, Any] | None:
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return None
        normalized = (keyword or "").strip()
        if not normalized:
            return None
        cache: dict[str, tuple[float, dict[str, Any] | None]] = getattr(
            app_state, "_album_keyword_cache", {}
        )
        now = time.monotonic()
        cached = cache.get(normalized)
        if cached is not None and now - cached[0] < self._cache_ttl:
            return cached[1]

        hinted_id = _ASK_DOMAIN_ALBUM_HINTS.get(normalized)
        for tag, album_id in _ASK_DOMAIN_ALBUM_HINTS.items():
            if tag and tag in normalized and album_id:
                hinted_id = album_id
                break
        if hinted_id:
            try:
                detail = await bff.get_meta_album(hinted_id)
            except Exception as exc:
                logger.warning("get_meta_album(%s) 失败: %s", hinted_id, exc)
                detail = None
            if isinstance(detail, dict):
                hint = {
                    "album_id": hinted_id,
                    "name": str(detail.get("albumName") or detail.get("name") or ""),
                    "description": str(detail.get("albumDesc") or detail.get("description") or ""),
                    "score": 100.0,
                }
                cache[normalized] = (now, hint)
                app_state._album_keyword_cache = cache
                return hint

        try:
            albums = await bff.list_meta_albums(page_size=100)
        except Exception as exc:
            logger.warning("list_meta_albums 失败: %s", exc)
            cache[normalized] = (now, None)
            app_state._album_keyword_cache = cache
            return None
        if not isinstance(albums, list) or not albums:
            cache[normalized] = (now, None)
            app_state._album_keyword_cache = cache
            return None

        best: dict[str, Any] | None = None
        best_score = -1.0
        for album in albums:
            name = str(album.get("albumName") or album.get("name") or "").strip()
            desc = str(album.get("albumDesc") or album.get("description") or "").strip()
            score = 0.0
            if name == normalized:
                score += 20.0
            if normalized and normalized in name:
                score += 8.0
            if name:
                for token in _CJK_RE.findall(name):
                    if token and token in normalized:
                        score += 3.0
            if normalized and normalized in desc:
                score += 1.5
            for tag, bonus in (
                ("订单", 4.0),
                ("模型汇总", 4.0),
                ("汇总", 2.0),
                ("社交电商", 1.0),
            ):
                if tag in name:
                    score += bonus
            if score > best_score:
                best_score = score
                best = {
                    "album_id": _as_int(album.get("id") or album.get("albumId")),
                    "name": name,
                    "description": desc,
                    "score": score,
                }
        result = best if best and best_score >= 4.0 else None
        cache[normalized] = (now, result)
        app_state._album_keyword_cache = cache
        return result

    def _merge(
        self,
        *,
        keyword: str,
        album: dict[str, Any] | None,
        album_entities: list[dict[str, Any]],
        tables: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        def _clean_name(raw_name: object) -> str:
            text = str(raw_name or "").strip()
            if not text or "*" in text:
                return ""
            if not _IDENTIFIER_RE.match(text.split(".")[-1]):
                return ""
            return text

        def _matches_keyword(item: dict[str, Any]) -> bool:
            if not keyword:
                return True
            key = keyword.lower()
            parts = [
                str(item.get("table_name") or "").lower(),
                str(item.get("comment") or "").lower(),
                str(item.get("remark") or "").lower(),
            ]
            return any(key in part for part in parts if part)

        merged: dict[str, dict[str, Any]] = {}
        for item in album_entities:
            if not isinstance(item, dict):
                continue
            name = _clean_name(item.get("table_name") or item.get("name"))
            project = _clean_name(item.get("project") or item.get("databaseName"))
            if not name:
                continue
            full_name = f"{project}.{name}" if project else name
            guid = str(item.get("entity_guid") or item.get("entityGuid") or "")
            if not guid and project and name:
                guid = f"odps.{project}.{name}"
            merged[full_name.lower()] = {
                "project": project,
                "table_name": name,
                "full_name": full_name,
                "comment": item.get("comment") or "",
                "entity_guid": guid,
                "ref_count": 0,
                "album_hit": True,
                "album_id": album["album_id"] if album else None,
                "album_name": album["name"] if album else "",
                "album_category": str(item.get("remark") or ""),
            }
        for item in tables or []:
            if not isinstance(item, dict):
                continue
            if not _matches_keyword(item):
                continue
            name = _clean_name(item.get("table_name") or item.get("name"))
            project = _clean_name(item.get("project") or item.get("databaseName"))
            if not name:
                continue
            full_name = f"{project}.{name}" if project else name
            guid = str(item.get("entity_guid") or item.get("entityGuid") or "")
            if not guid and project and name:
                guid = f"odps.{project}.{name}"
            key = full_name.lower()
            row = merged.setdefault(
                key,
                {
                    "project": project,
                    "table_name": name,
                    "full_name": full_name,
                    "comment": item.get("comment") or "",
                    "entity_guid": guid,
                    "ref_count": int(item.get("ref_count") or 0),
                    "album_hit": False,
                    "album_id": None,
                    "album_name": "",
                    "album_category": "",
                },
            )
            if not row.get("comment") and item.get("comment"):
                row["comment"] = item.get("comment") or ""
        candidates = list(merged.values())
        return candidates, candidates

    def _shape_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        merged: list[dict[str, Any]],
        album: dict[str, Any] | None,
        keyword: str,
    ) -> MetadataQueryResult | None:
        normalized = list(merged)
        if not normalized:
            logger.info(
                "MetadataProvider no hit for keyword=%s (album=%s)",
                keyword,
                album.get("name") if album else None,
            )
            return None
        if (
            album is None
            and not any(item.get("album_hit") for item in normalized)
            and len(normalized) > 1
        ):
            logger.info(
                "MetadataProvider weak hit (%d) for keyword=%s without album",
                len(normalized),
                keyword,
            )
            return None
        return MetadataQueryResult(
            keyword=keyword,
            album=album,
            candidates=normalized,
        )

    def invalidate(self, keyword: str | None = None) -> None:
        """Clear the per-keyword search cache (and album cache if keyword is None)."""
        if keyword is None:
            self._search_cache.clear()
            app_state._album_keyword_cache = {}
            return
        self._search_cache.pop(keyword, None)
        cache: dict[str, tuple[float, dict[str, Any] | None]] = getattr(
            app_state, "_album_keyword_cache", {}
        )
        cache.pop(keyword, None)


# ----------------------------------------------------------------------
# Helpers shared with the legacy workflow_service path. Keep these here
# so the rule-based planner + the metadata provider can both rely on
# the same shape helpers without circular imports.
# ----------------------------------------------------------------------


def _looks_like_physical_table(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.search(r"[一-鿿]", text):
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?", text))


def _is_cookie_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "csrf",
            "cookie",
            "login",
            "expired",
            "decrypt",
            "unauthorized",
            "forbidden",
            "403",
        )
    )


async def _refresh_cookie_auth(bff: Any) -> dict[str, Any]:
    from dataworks_agent.cookie.background_refresh import (
        run_cookie_background_refresh_once,
    )

    outcome = await run_cookie_background_refresh_once(force=True)
    reset = getattr(bff, "reset_auth_cache", None)
    if callable(reset):
        reset()
    else:
        bff._cookie = ""
        bff._csrf_token = ""
        bff._csrf_time = 0
    return outcome
