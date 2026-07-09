"""Load bundled steering documents and word-root dictionary."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_STANDARDS_DIR = Path(__file__).resolve().parent
_STEERING_DIR = _STANDARDS_DIR / "steering"
_WORD_ROOTS_PATH = _STANDARDS_DIR / "word_roots" / "词根.text"

_STANDARD_DOCS: dict[str, str] = {
    "data-warehouse-standards": "data-warehouse-standards.md",
    "field-naming-standards": "field-naming-standards.md",
    "sql-development-rules": "sql-development-rules.md",
    "hologres-naming-standards": "hologres-naming-standards.md",
}


def list_standard_documents() -> list[dict[str, str]]:
    return [
        {"id": doc_id, "title": doc_id.replace("-", " "), "filename": filename}
        for doc_id, filename in _STANDARD_DOCS.items()
    ]


def load_standard_document(doc_id: str) -> str:
    filename = _STANDARD_DOCS.get(doc_id)
    if not filename:
        raise KeyError(doc_id)
    path = _STEERING_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_word_root_entries() -> list[dict[str, Any]]:
    db_entries = _load_word_root_entries_from_db()
    if db_entries:
        return db_entries

    if not _WORD_ROOTS_PATH.is_file():
        return []

    entries: list[dict[str, Any]] = []
    with open(_WORD_ROOTS_PATH, encoding="utf-8") as fh:
        header: list[str] | None = None
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            parts = line.split("\t")
            if header is None:
                header = [p.strip().lower() for p in parts]
                continue
            row = {
                header[i]: parts[i].strip() if i < len(parts) else "" for i in range(len(header))
            }
            name = row.get("column_name", "")
            if name:
                entries.append(
                    {
                        "column_name": name,
                        "column_desc": row.get("column_desc", ""),
                        "is_digit": row.get("is_digit", "0") in {"1", "true", "True"},
                    }
                )
    return entries


def _load_word_root_entries_from_db() -> list[dict[str, Any]]:
    try:
        from sqlalchemy import select

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import WordRootCacheModel

        with SessionLocal() as db:
            rows = db.execute(select(WordRootCacheModel)).scalars().all()
            if not rows:
                return []
            return [
                {
                    "column_name": row.column_name,
                    "column_desc": row.column_desc,
                    "is_digit": bool(row.is_digit),
                }
                for row in rows
            ]
    except Exception:
        return []


def clear_word_root_loader_cache() -> None:
    load_word_root_entries.cache_clear()
    valid_root_tokens.cache_clear()


def word_root_source() -> str:
    """返回当前词根数据来源：online（已同步）或 bundled（内置文件）。"""
    return "online" if _load_word_root_entries_from_db() else "bundled"


@lru_cache(maxsize=1)
def valid_root_tokens() -> set[str]:
    return {
        entry["column_name"].strip().lower()
        for entry in load_word_root_entries()
        if entry.get("column_name")
    }


def validate_field_roots(field_name: str, valid_roots: set[str] | None = None) -> list[str]:
    """Return underscore segments not present in the word-root dictionary."""
    roots = valid_roots if valid_roots is not None else valid_root_tokens()
    segments = [segment for segment in field_name.lower().split("_") if segment]
    return [segment for segment in segments if segment not in roots]
