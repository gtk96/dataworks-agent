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
