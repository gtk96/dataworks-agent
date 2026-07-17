"""Project metadata provider — surfaces settings + workflow context as text.

This is intentionally tiny today: it reads the same constants the rule-based
planner already uses (project id, schema, cookie health) and renders them
as a compact prompt paragraph. LLM-as-router can later consume this same
string so rule-based and LLM paths share a single vocabulary.
"""

from __future__ import annotations

from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.state import app_state


class ProjectProvider:
    """Render the project facts the agent is currently operating on.

    Output is intentionally short (well under the 200-token budget in
    ``conversational-dialog-design.md`` §4) so it can be inlined into
    system prompts without consuming a meaningful share of the context
    window.
    """

    @staticmethod
    def render(*, conversation_id: str | None = None) -> str:
        """Return a human-readable project overview line."""
        cookie_health = getattr(app_state, "cookie_health", "unknown") or "unknown"
        maxcompute = settings.maxcompute_project or settings.dataworks_dev_schema
        return (
            "## Project context\n"
            f"- region: {settings.dataworks_region}\n"
            f"- dev_schema: {settings.dataworks_dev_schema}\n"
            f"- prod_schema: {settings.dataworks_prod_schema}\n"
            f"- maxcompute_project: {maxcompute}\n"
            f"- cookie_health: {cookie_health}\n"
            f"- conversation_id: {conversation_id or '-'}"
        )

    @staticmethod
    def to_dict() -> dict[str, Any]:
        """Structured form for the rule-based planner."""
        return {
            "region": settings.dataworks_region,
            "dev_schema": settings.dataworks_dev_schema,
            "prod_schema": settings.dataworks_prod_schema,
            "maxcompute_project": settings.maxcompute_project
            or settings.dataworks_dev_schema,
            "cookie_health": getattr(app_state, "cookie_health", "unknown"),
        }
