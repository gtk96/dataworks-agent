"""Read-only DataWorks directory checks for node creation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def normalize_node_path(path: str) -> str:
    return "/".join(part for part in str(path or "").strip().split("/") if part)


def parent_node_path(path: str) -> str:
    normalized = normalize_node_path(path)
    return normalized.rsplit("/", 1)[0] if "/" in normalized else ""


def node_record_path(record: dict[str, Any]) -> str:
    for key in ("path", "nodePath", "filePath", "scriptPath"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_node_path(value)
    script = record.get("script") or record.get("Script")
    if isinstance(script, dict):
        value = script.get("path") or script.get("Path")
        if isinstance(value, str) and value.strip():
            return normalize_node_path(value)
    return ""


def node_record_uuid(record: dict[str, Any]) -> str:
    for key in ("uuid", "nodeUuid", "id", "nodeId", "Id"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def find_node_by_path(records: list[dict[str, Any]], path: str) -> dict[str, Any] | None:
    target = normalize_node_path(path)
    for record in records:
        if isinstance(record, dict) and node_record_path(record) == target:
            return record
    return None


def infer_existing_directory(records: list[dict[str, Any]], path: str) -> bool:
    """Infer a directory only from positive node-path evidence."""
    target = normalize_node_path(path)
    if not target:
        return False
    prefix = f"{target}/"
    return any(
        isinstance(record, dict) and node_record_path(record).startswith(prefix)
        for record in records
    )


@dataclass(frozen=True)
class ExistingDirectoryEvidence:
    path: str
    source: str
    checked_at: str
    confirmed: bool

    @classmethod
    def from_check(cls, path: str, source: str, confirmed: bool) -> ExistingDirectoryEvidence:
        return cls(
            path=normalize_node_path(path),
            source=source,
            checked_at=datetime.now(UTC).isoformat(),
            confirmed=confirmed,
        )
