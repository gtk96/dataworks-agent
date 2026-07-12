from __future__ import annotations

from datetime import date

from dataworks_agent.semantic.query_understanding import BusinessQueryUnderstanding


def _definitions():
    return [
        {
            "id": "ad_spend_amt",
            "name": "广告花费",
            "aliases": ["广告花费", "广告费", "花了多少钱"],
            "context_aliases": {"aliases": ["花费"], "terms": ["平台", "facebook"]},
            "freshness": {"supports_historical": True},
            "dimensions": [
                {
                    "id": "family",
                    "name": "家族",
                    "column": "family_name",
                    "aliases": ["家族", "各家族"],
                    "value_pattern": r"(?P<value>[\u4e00-\u9fff]{2,12}家族)",
                },
                {
                    "id": "platform",
                    "name": "平台",
                    "column": "platform",
                    "aliases": ["平台", "各平台"],
                    "values": {"facebook": "facebook", "脸书": "facebook"},
                },
            ],
        }
    ]


def test_understands_metric_dimension_value_time_and_breakdown():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    query, _ = parser.understand("金狮家族今天各平台花了多少钱", _definitions())

    assert query.metric_id == "ad_spend_amt"
    assert query.dimensions == ["platform"]
    assert query.filters == {"family": "金狮家族"}
    assert query.time_range.start == "2026-07-13"
    assert query.query_type == "breakdown"


def test_platform_value_is_filter_not_grouping():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    query, _ = parser.understand("今天金狮家族 Facebook 花费", _definitions())

    assert query.dimensions == []
    assert query.filters == {"family": "金狮家族", "platform": "facebook"}


def test_group_word_is_not_mistaken_for_dimension_value():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    query, _ = parser.understand("今天各家族广告花费排名", _definitions())

    assert query.dimensions == ["family"]
    assert query.filters == {}


def test_ambiguous_bare_cost_is_not_forced_to_ad_spend():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    assert parser.understand("今天花费多少", _definitions()) is None


def _base_query(parser: BusinessQueryUnderstanding):
    understood = parser.understand(
        "\u91d1\u72ee\u5bb6\u65cf\u4eca\u5929\u5404\u5e73\u53f0\u5e7f\u544a\u82b1\u8d39\u662f\u591a\u5c11",
        _definitions(),
    )
    assert understood is not None
    return understood[0]


def test_followup_can_filter_platform():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    refined = parser.refine("\u53ea\u770b Facebook", _base_query(parser), _definitions()[0])

    assert refined is not None
    assert refined.dimensions == []
    assert refined.filters == {"family": "\u91d1\u72ee\u5bb6\u65cf", "platform": "facebook"}


def test_followup_can_change_date():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    refined = parser.refine("\u6362\u6210\u6628\u5929", _base_query(parser), _definitions()[0])

    assert refined is not None
    assert refined.time_range.start == "2026-07-12"
    assert refined.time_range.kind == "yesterday"


def test_followup_can_replace_grouping_dimension():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    refined = parser.refine(
        "\u6309\u5bb6\u65cf\u62c6\u5f00", _base_query(parser), _definitions()[0]
    )

    assert refined is not None
    assert refined.dimensions == ["family"]
    assert refined.filters == {}


def test_followup_can_clear_dimension_filter():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))
    prior, _ = parser.understand(
        "\u4eca\u5929\u91d1\u72ee\u5bb6\u65cf Facebook \u82b1\u8d39", _definitions()
    )

    refined = parser.refine("\u5168\u90e8\u5e73\u53f0", prior, _definitions()[0])

    assert refined is not None
    assert refined.filters == {"family": "\u91d1\u72ee\u5bb6\u65cf"}


def test_followup_refuses_historical_query_when_contract_does_not_support_it():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))
    definition = {**_definitions()[0], "freshness": {"supports_historical": False}}
    prior, _ = parser.understand(
        "\u91d1\u72ee\u5bb6\u65cf\u4eca\u5929\u5404\u5e73\u53f0\u5e7f\u544a\u82b1\u8d39",
        [definition],
    )

    assert parser.refine("\u6362\u6210\u6628\u5929", prior, definition) is None


def test_explicit_date_range_is_not_truncated_to_first_date():
    parser = BusinessQueryUnderstanding(lambda: date(2026, 7, 13))

    query, _ = parser.understand(
        "2026-07-01\u52302026-07-07\u5404\u5e73\u53f0\u5e7f\u544a\u82b1\u8d39\u8d8b\u52bf",
        _definitions(),
    )

    assert query.time_range.kind == "range"
    assert query.time_range.start == "2026-07-01"
    assert query.time_range.end == "2026-07-07"
