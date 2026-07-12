from dataworks_agent.semantic.knowledge_extractor import SQLKnowledgeExtractor


def test_sql_extractor_records_aggregate_case_tables_filters_and_dimensions_as_draft():
    sql = """
SELECT
  family_name,
  SUM(CASE WHEN order_status = 'signed' THEN amount ELSE 0 END) AS signed_amount
FROM giikin_aliyun.tb_rp_pro_sale_report_df
WHERE pt = MAX_PT('giikin_aliyun.tb_rp_pro_sale_report_df')
  AND family_name <> '合计'
GROUP BY family_name
"""

    result = SQLKnowledgeExtractor().extract(
        sql,
        source={"task_id": 10001, "task_name": "经营分析"},
    )

    assert result.parse_errors == []
    assert result.tables == ["giikin_aliyun.tb_rp_pro_sale_report_df"]
    assert result.dimensions == ["family_name"]
    assert "family_name <> '合计'" in result.filters[0]
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.status == "draft"
    assert candidate.alias == "signed_amount"
    assert candidate.aggregation == "SUM"
    assert candidate.case_when
    assert candidate.source["task_id"] == 10001


def test_sql_extractor_never_turns_plain_columns_into_metric_candidates():
    result = SQLKnowledgeExtractor().extract("SELECT id, name FROM p.t LIMIT 10")

    assert result.tables == ["p.t"]
    assert result.candidates == []


def test_sql_extractor_returns_parse_error_without_false_candidate():
    result = SQLKnowledgeExtractor().extract("SELECT FROM")

    assert result.candidates == []
    assert result.parse_errors
