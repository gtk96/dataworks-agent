"""Unit tests for incremental WHERE inference."""

from __future__ import annotations

from dataworks_agent.services.ods_di.where_infer import (
    default_where_mode,
    infer_incremental_where,
    infer_where_field,
    list_where_options,
)


class TestInferWhereField:
    def test_case_insensitive(self) -> None:

        columns = [{"column_name": "Update_Time", "data_type": "datetime", "column_key": ""}]

        assert infer_where_field(columns)["where_field"] == "Update_Time"

    def test_up_time_unix(self) -> None:

        columns = [{"column_name": "up_time", "data_type": "bigint", "column_key": ""}]

        assert infer_where_field(columns) == {"where_field": "up_time", "where_type": "unix"}


class TestListWhereOptions:
    def test_pair_includes_coalesce_and_or(self) -> None:

        columns = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]

        modes = [o["mode"] for o in list_where_options(columns)]

        assert "coalesce" in modes

        assert "or" in modes

        assert "modify" in modes

        assert "create" in modes

    def test_unix_pair_defaults_to_or(self) -> None:

        columns = [
            {"column_name": "up_time", "data_type": "bigint"},
            {"column_name": "create_time", "data_type": "string"},
        ]

        assert default_where_mode(columns) == "or"

        modes = [o["mode"] for o in list_where_options(columns)]

        assert "coalesce" not in modes

        assert "or" in modes


class TestInferIncrementalWhere:
    def test_coalesce_when_both_present(self) -> None:

        columns = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]

        meta = infer_incremental_where(columns, "hour", "coalesce")

        assert meta["where_label"] == "coalesce(update_time, create_time)"

        assert "coalesce(update_time, create_time)" in meta["where_clause"]

    def test_or_mode(self) -> None:

        columns = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]

        meta = infer_incremental_where(columns, "hour", "or")

        assert meta["where_label"] == "update_time OR create_time"

        assert "update_time::timestamp >=" in meta["where_clause"]

        assert " or create_time::timestamp >=" in meta["where_clause"]

    def test_modify_only(self) -> None:

        columns = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]

        meta = infer_incremental_where(columns, "hour", "modify")

        assert meta["where_label"] == "update_time"

        assert "coalesce" not in meta["where_clause"]

        assert " or " not in meta["where_clause"]

    def test_create_only(self) -> None:

        columns = [{"column_name": "create_time", "data_type": "string"}]

        meta = infer_incremental_where(columns, "hour", "create")

        assert meta["where_label"] == "create_time"

        assert "coalesce" not in meta["where_clause"]

    def test_modify_time_pair(self) -> None:

        columns = [
            {"column_name": "modify_time", "data_type": "timestamp"},
            {"column_name": "create_time", "data_type": "timestamp"},
        ]

        meta = infer_incremental_where(columns, "hour", "coalesce")

        assert meta["where_label"] == "coalesce(modify_time, create_time)"

    def test_none_mode(self) -> None:

        columns = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]

        meta = infer_incremental_where(columns, "hour", "none")

        assert meta["where_clause"] == ""
