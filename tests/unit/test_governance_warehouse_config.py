"""Warehouse governance config loader tests."""

from __future__ import annotations

import pytest

from dataworks_agent.governance.warehouse_config import (
    load_coding_standards,
    load_conventions,
    load_field_suffix_rules,
    load_subject_domains,
    load_update_modes,
    load_warehouse_standards_bundle,
)


class TestWarehouseConfig:
    def test_subject_domains_loaded(self) -> None:
        domains = load_subject_domains()
        codes = {item["code"] for item in domains}
        assert "ORD" in codes
        assert "PUB" in codes

    def test_update_modes_loaded(self) -> None:
        modes = load_update_modes()
        codes = {item["code"] for item in modes}
        assert "hour" in codes
        assert "day" in codes

    def test_layer_conventions_loaded(self) -> None:
        data = load_conventions("dwd")
        assert data.get("layer") == "DWD"
        assert "naming" in data

    def test_dim_layer_conventions_loaded(self) -> None:
        data = load_conventions("dim")
        assert data.get("layer") == "DIM"
        assert data["naming"]["table_prefix"] == "dim_"

    def test_invalid_layer_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown layer"):
            load_conventions("foo")

    def test_field_suffix_rules_non_empty(self) -> None:
        rules = load_field_suffix_rules()
        suffixes = {rule["suffix"] for rule in rules}
        assert "id" in suffixes
        assert "amt" in suffixes

    def test_warehouse_standards_bundle(self) -> None:
        bundle = load_warehouse_standards_bundle()
        assert bundle["field_suffix_rules"]
        assert "dwd" in bundle["layers"]
        assert "dim" in bundle["layers"]
        assert load_coding_standards()["charset"] == "UTF-8"
