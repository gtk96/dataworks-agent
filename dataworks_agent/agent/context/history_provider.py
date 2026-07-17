"""History provider — surfaces conversational follow-up context.

Two flavours:

- :meth:`HistoryProvider.recent_tables` returns the most recently
  referenced physical tables in this conversation, so follow-ups like
  ``刚才那张表`` can resolve to a single table instead of an NLU
  fallback.
- :meth:`HistoryProvider.assemble` renders a compact prompt paragraph
  with the last N user / agent turns (used by the future LLM
  prompt assembler; rule-based planner currently only consumes
  ``recent_tables``).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import select

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import ConversationHistoryModel
except Exception:  # pragma: no cover - DB not available in some envs
    SessionLocal = None  # type: ignore[assignment]
    ConversationHistoryModel = None  # type: ignore[assignment]


class HistoryProvider:
    """Read conversation_graph + ``conversation_history`` rows."""

    def __init__(self, conversation_graph: Any | None = None) -> None:
        self._conversation_graph = conversation_graph
        if conversation_graph is None:
            try:
                from dataworks_agent.agent.conversation_graph import (
                    ConversationGraph,
                )

                self._conversation_graph = ConversationGraph()
            except Exception:  # pragma: no cover - best effort
                self._conversation_graph = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recent_tables(self, conversation_id: str | None, *, limit: int = 3) -> list[str]:
        """Return up to ``limit`` physical tables mentioned in recent turns.

        Order: most recent first. Empty list when no conversation or no
        history rows.
        """
        rows = self._load_recent_history(conversation_id, limit=12)
        tables: list[str] = []
        seen: set[str] = set()
        for row in rows:
            content = row.get("content") or ""
            content = self._unwrap_history_payload(content)
            for table in self._extract_tables(content):
                key = table.lower()
                if key in seen:
                    continue
                seen.add(key)
                tables.append(table)
                if len(tables) >= limit:
                    return tables
        # Also peek at conversation_graph for the most recent workflow_state.
        graph_tables = await self._extract_graph_tables(conversation_id)
        for table in graph_tables:
            key = table.lower()
            if key in seen:
                continue
            seen.add(key)
            tables.append(table)
            if len(tables) >= limit:
                break
        return tables

    async def assemble(self, conversation_id: str | None, *, max_turns: int = 10) -> str:
        """Compact, prompt-safe rendering of recent conversation.

        Format mirrors ``HistoryProvider`` described in the design doc
        (markdown with truncated turns).
        """
        rows = self._load_recent_history(conversation_id, limit=max_turns)
        if not rows:
            return ""
        recent_tables = await self.recent_tables(conversation_id)
        lines = ["## 最近对话"]
        if recent_tables:
            lines.append("- 最近引用表: " + " / ".join(recent_tables))
        for row in rows[-max_turns:]:
            role = "用户" if row.get("role") == "user" else "Agent"
            content = self._unwrap_history_payload(row.get("content") or "")[:400]
            lines.append(f"- **{role}**: {content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_history_payload(content: str) -> str:
        """Render the message body; assistant history may be JSON-wrapped."""
        if not content:
            return ""
        content = content.strip()
        if not (content.startswith("{") and content.endswith("}")):
            return content
        try:
            import json

            payload = json.loads(content)
        except Exception:
            return content
        if isinstance(payload, dict):
            # Prefer the structured message text but fall back to the
            # table-level summary so the recent_table extractor can
            # still pick up ``giikin_aliyun.tb_dwd_*`` mentions.
            message = payload.get("message")
            if isinstance(message, str) and message:
                parts = [message]
                for chip in payload.get("option_chips") or []:
                    if not isinstance(chip, dict):
                        continue
                    value = chip.get("value")
                    if isinstance(value, str) and value:
                        parts.append(value)
                return "\n".join(parts)
        return content

    def _load_recent_history(
        self, conversation_id: str | None, *, limit: int
    ) -> list[dict[str, Any]]:
        if not conversation_id or SessionLocal is None:
            return []
        try:
            session = SessionLocal()
        except Exception as exc:
            logger.warning("history session failed: %s", exc)
            return []
        try:
            stmt = (
                select(ConversationHistoryModel)
                .where(ConversationHistoryModel.conversation_id == conversation_id)
                .order_by(ConversationHistoryModel.id.desc())
                .limit(limit)
            )
            rows = list(session.execute(stmt).scalars().all())
            return [{"role": msg.role, "content": msg.content} for msg in reversed(rows)]
        except Exception as exc:
            logger.warning("history load failed: %s", exc)
            return []
        finally:
            session.close()

    async def _extract_graph_tables(self, conversation_id: str | None) -> list[str]:
        if not conversation_id or self._conversation_graph is None:
            return []
        try:
            context = await self._conversation_graph.context(conversation_id)
        except Exception:
            return []
        result_data = (context.get("workflow_state") or {}).get("result_data") or {}
        tables: list[str] = []
        seen: set[str] = set()
        for key in ("query", "table", "target_table"):
            value = result_data.get(key)
            if isinstance(value, str) and value and value.lower() not in seen:
                seen.add(value.lower())
                tables.append(value)
        return tables

    @staticmethod
    def _extract_tables(text: str) -> list[str]:
        """Naive table-name extractor for free-form assistant / user text."""
        if not text:
            return []
        import re

        candidates: list[str] = []
        seen: set[str] = set()
        # 1) ``project.table`` pattern (already canonical).
        for match in re.finditer(
            r"\b([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z][a-zA-Z0-9_]*)\b",
            text,
        ):
            value = match.group(1)
            if value.lower() not in seen:
                seen.add(value.lower())
                candidates.append(value)
        # 2) Bare ``dws_xxx``/``tb_dwd_ord_xxx``/``tb_rp_...`` patterns
        #    common in our warehouse. We default to ``giikin_aliyun`` when
        #    the candidate starts with ``tb_`` (matching the prod naming
        #    convention) and the table isn't already project-qualified.
        for match in re.finditer(
            r"\b((?:ods|dwd|dws|dim|dmr|rpt|tb_[a-z0-9]+)_[a-zA-Z0-9_]{3,})\b",
            text,
        ):
            value = match.group(1)
            if value.lower() in seen:
                continue
            if value.lower().startswith("tb_"):
                value = f"giikin_aliyun.{value}"
            if value.lower() in seen:
                continue
            seen.add(value.lower())
            candidates.append(value)
        return candidates
