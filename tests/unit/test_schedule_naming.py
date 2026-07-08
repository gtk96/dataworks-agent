"""Schedule configuration helpers (ported from data-development-design)."""

from __future__ import annotations

import pytest

from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    auto_distribute,
    generate_cron,
    get_cycle_type,
    get_schedule_config,
    granularity_from_update_method,
    infer_schedule_type,
)


class TestGetCycleType:
    def test_hour_returns_not_daily(self) -> None:
        assert get_cycle_type("hour") == "NotDaily"

    def test_day_returns_daily(self) -> None:
        assert get_cycle_type("day") == "Daily"

    def test_invalid_granularity_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid granularity"):
            get_cycle_type("weekly")  # type: ignore[arg-type]


class TestGenerateCron:
    def test_hour_basic(self) -> None:
        assert generate_cron("hour", minute=15) == "00 15 00-23/1 * * ?"

    def test_day_basic(self) -> None:
        assert generate_cron("day", hour=6, minute=30) == "00 30 06 * * ?"


class TestAutoDistribute:
    def test_hour_four_tasks(self) -> None:
        minutes = [auto_distribute(i, 4, "hour")["minute"] for i in range(4)]
        assert minutes == [0, 15, 30, 45]

    def test_day_single_task(self) -> None:
        assert auto_distribute(0, 1, "day") == {"hour": 0, "minute": 1}


class TestInferScheduleType:
    def test_hour_suffix(self) -> None:
        assert infer_schedule_type("dwd_trade_order_hour") == "NotDaily"

    def test_day_suffix(self) -> None:
        assert infer_schedule_type("dwd_trade_order_day") == "Daily"

    def test_ods_table_hour(self) -> None:
        assert infer_schedule_type("ods_hl_ofc__orders_hour") == "NotDaily"


class TestGetScheduleConfig:
    def test_hour_config(self) -> None:
        config = get_schedule_config("hour")
        assert config["cycle_type"] == "NotDaily"
        assert config["parameters"] == HOURLY_SQL_PARAMETERS

    def test_day_config(self) -> None:
        config = get_schedule_config("day")
        assert config["cycle_type"] == "Daily"
        assert config["parameters"] == DAILY_SQL_PARAMETERS


class TestGranularityFromUpdateMethod:
    def test_maps_dataworks_values(self) -> None:
        assert granularity_from_update_method("hour") == "hour"
        assert granularity_from_update_method("hourly") == "hourly"
        assert granularity_from_update_method("day") == "day"


class TestAutoDistributeWithCron:
    def test_hour_distribute_then_cron(self) -> None:
        time = auto_distribute(2, 4, "hour")
        cron = generate_cron("hour", **time)
        assert cron == "00 30 00-23/1 * * ?"
