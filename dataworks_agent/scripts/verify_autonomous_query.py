"""Golden-corpus gate for deterministic autonomous business queries."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from dataworks_agent.semantic.album_context import AlbumTable, DataAlbumContext
from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase
from dataworks_agent.semantic.query_planner import MetricQueryPlanner
from dataworks_agent.semantic.query_understanding import BusinessQueryUnderstanding

_CORPUS_PATH = Path("tests/evaluation/autonomous_query_cases.json")
_METRICS_PATH = Path("dataworks_agent/semantic/metrics.json")
_KNOWLEDGE_PATH = Path("dataworks_agent/semantic/knowledge.json")


class _NoSemanticOverrides:
    def list_definitions(self, **_: Any) -> list[Any]:
        return []


def _knowledge_base() -> SemanticKnowledgeBase:
    return SemanticKnowledgeBase(
        metrics_path=_METRICS_PATH,
        knowledge_path=_KNOWLEDGE_PATH,
        semantic_layer=_NoSemanticOverrides(),  # type: ignore[arg-type]
    )


def _planner() -> MetricQueryPlanner:
    return MetricQueryPlanner(
        knowledge_base=_knowledge_base(),
        query_understanding=BusinessQueryUnderstanding(lambda: date(2026, 7, 13)),
    )


def _albums() -> list[DataAlbumContext]:
    return [
        DataAlbumContext(
            album_id=505,
            name="\u91d1\u72ee\u5bb6\u65cf",
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="vw_dwd_fin_nr_product_spend_1014_df",
                ),
                AlbumTable(
                    project="giikin_aliyun",
                    name="vw_dwd_fin_sale_spend_by_country_1014_df",
                ),
            ],
        ),
        DataAlbumContext(
            album_id=888,
            name="\u8ba2\u5355",
            tables=[
                AlbumTable(project="giikin_aliyun", name="tb_dws_ord_order_si_crt_df"),
                AlbumTable(project="giikin_aliyun", name="tb_dwd_ord_gk_order_info_crt_df"),
            ],
        ),
    ]


def _is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _is_subset(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and expected == actual
    return expected == actual


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    planner = _planner()
    knowledge = _knowledge_base()
    albums = _albums()
    failures: list[dict[str, Any]] = []

    for case in cases:
        kind = case["kind"]
        details: dict[str, Any] = {}
        try:
            if kind == "understand":
                understood = planner.understand(case["message"])
                actual = understood[0].to_dict() if understood else None
                ok = actual is not None and _is_subset(case["expected"], actual)
                details = {"actual": actual, "expected": case["expected"]}
            elif kind == "reject":
                actual = planner.understand(case["message"])
                ok = actual is None
                details = {"actual": actual[0].to_dict() if actual else None}
            elif kind == "plan":
                plan = planner.plan(case["message"], albums)
                if plan is None:
                    ok = False
                    details = {"actual": None}
                else:
                    sql_contains = case.get("sql_contains", [])
                    sql_not_contains = case.get("sql_not_contains", [])
                    reconciliation_contains = case.get("reconciliation_contains", [])
                    reconciliation_not_contains = case.get("reconciliation_not_contains", [])
                    ok = (
                        plan.metric_id == case["metric_id"]
                        and all(item in plan.sql for item in sql_contains)
                        and all(item not in plan.sql for item in sql_not_contains)
                        and all(item in plan.reconciliation_sql for item in reconciliation_contains)
                        and all(
                            item not in plan.reconciliation_sql
                            for item in reconciliation_not_contains
                        )
                    )
                    if "album_status" in case:
                        ok = ok and plan.album_validation.get("status") == case["album_status"]
                    details = {
                        "metric_id": plan.metric_id,
                        "sql": plan.sql,
                        "reconciliation_sql": plan.reconciliation_sql,
                        "album_status": plan.album_validation.get("status"),
                    }
            elif kind == "refine":
                initial = planner.understand(case["initial"])
                refined = planner.refine(case["followup"], initial[0]) if initial else None
                actual = refined.to_dict() if refined else None
                if case.get("expected_none"):
                    ok = actual is None
                else:
                    ok = actual is not None and _is_subset(case["expected"], actual)
                details = {"actual": actual, "expected": case.get("expected")}
            elif kind == "knowledge":
                matches = knowledge.search(case["message"]).matches
                actual = [
                    {
                        "id": item.item.item_id,
                        "status": item.item.status,
                        "executable": bool(
                            item.item.status == "approved"
                            and item.item.query_contract
                            and knowledge.is_executable_definition(item.item.query_contract)
                        ),
                    }
                    for item in matches
                ]
                ok = bool(actual) and _is_subset(case["expected"], actual[0])
                details = {"actual": actual, "expected": case["expected"]}
            else:
                ok = False
                details = {"error": f"unsupported kind: {kind}"}
        except Exception as exc:
            ok = False
            details = {"error": f"{type(exc).__name__}: {exc}"}
        if not ok:
            failures.append({"id": case["id"], **details})

    total = len(cases)
    passed = total - len(failures)
    return {
        "corpus": str(_CORPUS_PATH),
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "failures": failures,
    }


def main() -> int:
    cases = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    report = evaluate_cases(cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
