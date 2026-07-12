from datetime import date

from dataworks_agent.agent.workflow_service import AgentWorkflowService
from dataworks_agent.semantic.album_context import AlbumTable, DataAlbumContext
from dataworks_agent.semantic.query_planner import MetricQueryPlan, MetricQueryPlanner
from dataworks_agent.semantic.query_understanding import BusinessQueryUnderstanding


def spend_album():
    return [
        DataAlbumContext(
            album_id=505,
            name="金狮家族",
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="vw_dwd_fin_nr_product_spend_1014_df",
                )
            ],
        )
    ]


def planner():
    return MetricQueryPlanner(
        query_understanding=BusinessQueryUnderstanding(lambda: date(2026, 7, 13))
    )


def test_ad_spend_query_is_schema_linked_and_executable():
    plan = planner().plan("金狮家族今天各平台花了多少钱", spend_album())

    assert plan is not None
    assert plan.metric_id == "ad_spend_amt"
    assert plan.album_validation["status"] == "lineage_match"
    assert plan.selected_dimensions == ["平台"]
    assert plan.business_query["filters"] == {"family": "金狮家族"}
    assert "FROM giikin_aliyun.tb_dwd_fin_ad_spend_di" in plan.sql
    assert "spend_date = '2026-07-13'" in plan.sql
    assert "family_name = '金狮家族'" in plan.sql
    assert "GROUP BY spend_date, platform" in plan.sql
    assert "ORDER BY ad_spend_amt DESC" in plan.sql


def test_ad_spend_platform_filter_generates_total():
    plan = planner().plan("今天金狮家族 Facebook 花费", spend_album())

    assert plan is not None
    assert plan.selected_dimensions == []
    assert "platform = 'facebook'" in plan.sql
    assert "SUM(ad_spend) AS total_ad_spend_amt" in plan.sql


def test_order_reconciliation_is_bound_to_primary_business_date():
    album = [
        DataAlbumContext(
            album_id=888,
            name="订单",
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dws_ord_order_si_crt_df",
                ),
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dwd_ord_gk_order_info_crt_df",
                ),
            ],
        )
    ]

    plan = planner().plan("今天的总有效订单是多少", album)

    assert plan is not None
    assert "__PRIMARY_DATA_DATE__" in plan.reconciliation_sql


def test_reconciliation_date_uses_primary_query_data_date():
    sql = "WHERE pt = '__PRIMARY_DATA_DATE__'"

    bound = AgentWorkflowService._bind_reconciliation_date(
        sql,
        ["data_date", "total_effective_order_cnt"],
        [["20260712", 95687]],
    )

    assert bound == "WHERE pt = '20260712'"


def test_reconciliation_date_normalizes_iso_date():
    sql = "WHERE pt = '__PRIMARY_DATA_DATE__'"

    bound = AgentWorkflowService._bind_reconciliation_date(
        sql,
        ["data_date", "total_effective_order_cnt"],
        [["2026-07-12", 95687]],
    )

    assert bound == "WHERE pt = '20260712'"


def test_grouped_ad_spend_answer_lists_platforms_and_total():
    plan = MetricQueryPlan(
        sql="SELECT 1",
        metric_id="ad_spend_amt",
        metric_name="\u5e7f\u544a\u82b1\u8d39",
        metric_version=1,
        table="giikin_aliyun.tb_dwd_fin_ad_spend_di",
        albums=[{"id": 505, "name": "\u91d1\u72ee\u5bb6\u65cf"}],
        selected_dimensions=["\u5e73\u53f0"],
        caliber={
            "measure": {
                "column": "ad_spend",
                "alias": "ad_spend_amt",
                "aggregation": "sum",
                "unit": "CNY",
            },
            "dimensions": [{"id": "platform", "name": "\u5e73\u53f0", "column": "platform"}],
        },
    )

    answer = AgentWorkflowService._format_query_answer(
        plan,
        ["data_date", "platform", "ad_spend_amt"],
        [
            ["2026-07-13", "google", 4102.168830095509],
            ["2026-07-13", "facebook", 3631.7108548160363],
            ["2026-07-13", "tiktok", 2918.575932652018],
            ["2026-07-13", "snapchat", 1374.820515729102],
        ],
    )

    assert "google\uff1a\u00a54,102.17" in answer
    assert "facebook\uff1a\u00a53,631.71" in answer
    assert "\u5408\u8ba1\uff1a\u00a512,027.28" in answer
    assert "approved v1" in answer


def test_effective_order_total_sums_family_rows_without_inventing_total_row():
    album = [
        DataAlbumContext(
            album_id=888,
            name="\u8ba2\u5355",
            tables=[
                AlbumTable(project="giikin_aliyun", name="tb_dws_ord_order_si_crt_df"),
                AlbumTable(project="giikin_aliyun", name="tb_dwd_ord_gk_order_info_crt_df"),
            ],
        )
    ]

    plan = planner().plan(
        "\u4eca\u5929\u7684\u603b\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11", album
    )

    assert plan is not None
    assert "SUM(effect_order_cnt) AS total_effective_order_cnt" in plan.sql
    assert "family_name = '\u5408\u8ba1'" not in plan.sql
    assert "family_name = '\u5408\u8ba1'" not in plan.reconciliation_sql


def test_effective_order_family_value_generates_schema_linked_filter():
    album = [
        DataAlbumContext(
            album_id=888,
            name="\u8ba2\u5355",
            tables=[
                AlbumTable(project="giikin_aliyun", name="tb_dws_ord_order_si_crt_df"),
                AlbumTable(project="giikin_aliyun", name="tb_dwd_ord_gk_order_info_crt_df"),
            ],
        )
    ]

    plan = planner().plan(
        "\u91d1\u72ee\u5bb6\u65cf\u4eca\u5929\u6709\u6548\u8ba2\u5355\u591a\u5c11", album
    )

    assert plan is not None
    assert "family_name = '\u91d1\u72ee\u5bb6\u65cf'" in plan.sql
    assert "family_name = '\u91d1\u72ee\u5bb6\u65cf'" in plan.reconciliation_sql


def test_ad_spend_range_total_aggregates_the_whole_period():
    plan = planner().plan("\u672c\u6708\u5e7f\u544a\u82b1\u8d39", spend_album())

    assert plan is not None
    assert "spend_date BETWEEN '2026-07-01' AND '2026-07-13'" in plan.sql
    assert "spend_date AS data_date" not in plan.sql
    assert "GROUP BY" not in plan.sql
    assert "SUM(ad_spend) AS total_ad_spend_amt" in plan.sql
    assert "LIMIT 1" in plan.sql


def test_ad_spend_range_breakdown_aggregates_by_dimension_not_by_day():
    plan = planner().plan(
        "2026-07-01\u52302026-07-07\u5404\u5e73\u53f0\u5e7f\u544a\u82b1\u8d39",
        spend_album(),
    )

    assert plan is not None
    assert "spend_date BETWEEN '2026-07-01' AND '2026-07-07'" in plan.sql
    assert "spend_date AS data_date" not in plan.sql
    assert "GROUP BY platform" in plan.sql
    assert "GROUP BY spend_date, platform" not in plan.sql
    assert "ORDER BY ad_spend_amt DESC" in plan.sql


def test_ad_spend_trend_keeps_daily_grain_and_orders_chronologically():
    plan = planner().plan(
        "\u8fd17\u5929\u5404\u5e73\u53f0\u5e7f\u544a\u82b1\u8d39\u8d8b\u52bf", spend_album()
    )

    assert plan is not None
    assert plan.business_query["query_type"] == "trend"
    assert "spend_date AS data_date" in plan.sql
    assert "GROUP BY spend_date, platform" in plan.sql
    assert "ORDER BY spend_date, platform ASC" in plan.sql
    assert "ORDER BY ad_spend_amt" not in plan.sql


def test_trend_answer_lists_dates_and_interval_total():
    plan = MetricQueryPlan(
        sql="SELECT 1",
        metric_id="ad_spend_amt",
        metric_name="\u5e7f\u544a\u82b1\u8d39",
        metric_version=1,
        table="giikin_aliyun.tb_dwd_fin_ad_spend_di",
        albums=[{"id": 505, "name": "\u91d1\u72ee\u5bb6\u65cf"}],
        selected_dimensions=[],
        caliber={
            "measure": {
                "column": "ad_spend",
                "alias": "ad_spend_amt",
                "aggregation": "sum",
                "unit": "CNY",
            },
            "dimensions": [],
        },
        business_query={
            "query_type": "trend",
            "time_range": {
                "kind": "range",
                "start": "2026-07-11",
                "end": "2026-07-13",
            },
        },
    )

    answer = AgentWorkflowService._format_query_answer(
        plan,
        ["data_date", "total_ad_spend_amt"],
        [
            ["2026-07-11", 100],
            ["2026-07-12", 200],
            ["2026-07-13", 300],
        ],
    )

    assert "\u65f6\u95f4\u8303\u56f4 2026-07-11 \u81f3 2026-07-13" in answer
    assert "2026-07-11\uff1a\u00a5100.00" in answer
    assert "2026-07-13\uff1a\u00a5300.00" in answer
    assert "\u533a\u95f4\u5408\u8ba1\uff1a\u00a5600.00" in answer


def test_range_total_answer_shows_requested_time_scope_without_daily_row():
    plan = MetricQueryPlan(
        sql="SELECT 1",
        metric_id="ad_spend_amt",
        metric_name="\u5e7f\u544a\u82b1\u8d39",
        metric_version=1,
        table="giikin_aliyun.tb_dwd_fin_ad_spend_di",
        selected_dimensions=[],
        caliber={
            "measure": {
                "column": "ad_spend",
                "alias": "ad_spend_amt",
                "aggregation": "sum",
                "unit": "CNY",
            }
        },
        business_query={
            "query_type": "total",
            "time_range": {
                "kind": "range",
                "start": "2026-07-01",
                "end": "2026-07-13",
            },
        },
    )

    answer = AgentWorkflowService._format_query_answer(
        plan,
        ["total_ad_spend_amt"],
        [[1234.5]],
    )

    assert "\u5e7f\u544a\u82b1\u8d39\uff1a\u00a51,234.50" in answer
    assert "\u65f6\u95f4\u8303\u56f4 2026-07-01 \u81f3 2026-07-13" in answer


def test_trend_answer_total_includes_rows_hidden_by_display_limit():
    plan = MetricQueryPlan(
        sql="SELECT 1",
        metric_id="ad_spend_amt",
        metric_name="\u5e7f\u544a\u82b1\u8d39",
        metric_version=1,
        table="giikin_aliyun.tb_dwd_fin_ad_spend_di",
        selected_dimensions=["\u5e73\u53f0"],
        caliber={
            "measure": {
                "column": "ad_spend",
                "alias": "ad_spend_amt",
                "aggregation": "sum",
                "unit": "CNY",
            },
            "dimensions": [{"name": "\u5e73\u53f0", "column": "platform"}],
        },
        business_query={
            "query_type": "trend",
            "time_range": {
                "kind": "range",
                "start": "2026-07-07",
                "end": "2026-07-13",
            },
        },
    )
    rows = [[f"2026-07-{7 + index // 4:02d}", f"p{index % 4}", 100] for index in range(28)]

    answer = AgentWorkflowService._format_query_answer(
        plan, ["data_date", "platform", "ad_spend_amt"], rows
    )

    assert "\u5176\u4f59 8 \u884c\u8bf7\u67e5\u770b\u7ed3\u679c\u8868" in answer
    assert "\u533a\u95f4\u5408\u8ba1\uff1a\u00a52,800.00" in answer
