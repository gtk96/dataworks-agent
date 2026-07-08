"""Bundled standards loader tests."""

from __future__ import annotations

import pytest

from dataworks_agent.standards.loader import (
    load_standard_document,
    load_word_root_entries,
    valid_root_tokens,
    validate_field_roots,
)


class TestStandardsLoader:
    def test_word_roots_loaded(self) -> None:
        entries = load_word_root_entries()
        assert len(entries) > 100
        assert entries[0]["column_name"]

    def test_valid_roots_contains_common_tokens(self) -> None:
        roots = valid_root_tokens()
        assert "order" in roots
        assert "dt" in roots

    def test_validate_field_roots_detects_unknown_segment(self) -> None:
        illegal = validate_field_roots("order_badtoken_id", {"order", "id"})
        assert illegal == ["badtoken"]

    def test_standard_documents_exist(self) -> None:
        content = load_standard_document("field-naming-standards")
        assert "字段" in content or "field" in content.lower()

    def test_unknown_standard_raises(self) -> None:
        with pytest.raises(KeyError):
            load_standard_document("does-not-exist")
