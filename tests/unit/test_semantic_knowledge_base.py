from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from dataworks_agent.semantic.album_context import AlbumTable, DataAlbumContext
from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase
from dataworks_agent.semantic.layer import SemanticDefinition


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_business_cost_question_returns_all_ambiguous_draft_concepts():
    layer = SimpleNamespace(list_definitions=lambda **kwargs: [])
    knowledge = SemanticKnowledgeBase(semantic_layer=layer)

    result = knowledge.search("今天花费多少？")

    assert [match.item.item_id for match in result.matches] == [
        "ad_spend_amt",
        "logistics_cost_amt",
        "purchase_cost_amt",
    ]
    assert all(match.item.status == "draft" for match in result.matches)
    assert "query_contract" in result.missing_contract_fields


def test_specific_business_metric_does_not_expand_to_generic_cost_matches():
    layer = SimpleNamespace(list_definitions=lambda **kwargs: [])
    result = SemanticKnowledgeBase(semantic_layer=layer).search("今天广告花费多少？")

    assert [match.item.item_id for match in result.matches] == ["ad_spend_amt"]
    assert "财务账单花费" in result.clarifying_questions[0]


def test_album_membership_is_added_as_dynamic_evidence():
    layer = SimpleNamespace(list_definitions=lambda **kwargs: [])
    contexts = [
        DataAlbumContext(
            album_id=330,
            name="物流成本",
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dwd_fin_order_logistics_cost_df",
                    comment="订单物流成本表",
                )
            ],
        )
    ]

    result = SemanticKnowledgeBase(semantic_layer=layer).search("物流成本是多少", contexts)

    assert result.matches[0].album_evidence == [
        {
            "album_id": 330,
            "album": "物流成本",
            "tables": ["giikin_aliyun.tb_dwd_fin_order_logistics_cost_df"],
        }
    ]


def test_approved_metric_has_priority_and_higher_db_version_overrides_baseline(tmp_path: Path):
    baseline = {
        "metrics": [
            {
                "id": "cost",
                "name": "成本",
                "aliases": ["成本"],
                "status": "approved",
                "version": 1,
                "table": "p.cost_v1",
                "measure": {"column": "amount", "aggregation": "sum"},
                "freshness": {"date_partition": "pt"},
                "asset_provenance": {"type": "data_album", "album_id": 9},
            }
        ]
    }
    layer = SimpleNamespace(
        list_definitions=lambda **kwargs: [
            SemanticDefinition(
                def_id="sem_cost_v2",
                kind="metric",
                key="cost",
                body={
                    "query_contract": {
                        "id": "cost",
                        "name": "成本",
                        "aliases": ["成本"],
                        "table": "p.cost_v2",
                        "measure": {"column": "amount", "aggregation": "sum"},
                        "freshness": {"date_partition": "pt"},
                        "asset_provenance": {"type": "data_album", "album_id": 9},
                    }
                },
                version=2,
                status="approved",
            )
        ]
    )
    knowledge = SemanticKnowledgeBase(
        metrics_path=_write_json(tmp_path / "metrics.json", baseline),
        knowledge_path=_write_json(tmp_path / "knowledge.json", {"items": []}),
        semantic_layer=layer,
    )

    metric = knowledge.approved_metric("今天成本多少")

    assert metric is not None
    assert metric["version"] == 2
    assert metric["table"] == "p.cost_v2"


def test_only_complete_approved_query_contract_is_executable():
    assert not SemanticKnowledgeBase.is_executable_definition(
        {"id": "cost", "table": "p.t", "status": "approved"}
    )
    assert SemanticKnowledgeBase.is_executable_definition(
        {
            "id": "cost",
            "table": "p.t",
            "measure": {"column": "amount", "aggregation": "sum"},
            "freshness": {"date_partition": "pt"},
            "asset_provenance": {"type": "verified_lineage", "album_id": 330},
        }
    )


def test_platform_spend_colloquial_question_prefers_ad_spend():
    result = SemanticKnowledgeBase().search(
        "\u91d1\u72ee\u5bb6\u65cf\u4eca\u5929\u5404\u5e73\u53f0\u82b1\u4e86\u591a\u5c11\u94b1"
    )

    assert [match.item.item_id for match in result.matches] == ["ad_spend_amt"]
    assert "\u5e73\u53f0\u82b1\u4e86\u591a\u5c11\u94b1" in result.matches[0].matched_aliases
