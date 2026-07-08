"""Governance update mode inferer tests."""

from __future__ import annotations

import pytest

from dataworks_agent.governance.update_mode_inferer import infer_update_mode


class TestInferUpdateMode:
    def test_hour(self) -> None:
        result = infer_update_mode("ods_ms_shop__orders_hour")
        assert result.dwd_update_mode == "hourly"
        assert result.sql_update_mode == "hourly"
        assert result.partition_fields == ["dt", "ht"]

    def test_day(self) -> None:
        result = infer_update_mode("ods_ms_shop__orders_day")
        assert result.dwd_update_mode == "all"
        assert result.sql_update_mode == "full"

    def test_unsupported(self) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            infer_update_mode("ods_ms_shop__orders_his")
