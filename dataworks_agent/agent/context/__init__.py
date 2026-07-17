"""Context Assembly Layer for conversational ask_data.

This package materialises the three context providers from
``docs/product/conversational-dialog-design.md`` so the chat workflow can
inject metadata / history / project facts into both the rule-based
planner and the (eventual) LLM prompt assembler.

Provider responsibilities:

- :class:`MetadataProvider` — searches the DataMap + Cookie BFF for tables
  matching a Chinese / English keyword, ranks them by business-domain
  album and table-name suffix, and caches the result.
- :class:`HistoryProvider` — pulls conversation_graph state plus recent
  ``conversation_history`` rows so follow-ups like ``刚才那个表`` resolve
  to the table last discussed.
- :class:`ProjectProvider` — surfaces project / schema / tool metadata so
  the planner / LLM have the same shared vocabulary.

None of the providers mutate global state beyond their own cache.
"""

from __future__ import annotations

from dataworks_agent.agent.context.history_provider import HistoryProvider
from dataworks_agent.agent.context.metadata_provider import (
    MetadataProvider,
    MetadataQueryResult,
)
from dataworks_agent.agent.context.project_provider import ProjectProvider

__all__ = [
    "HistoryProvider",
    "MetadataProvider",
    "MetadataQueryResult",
    "ProjectProvider",
]
