from __future__ import annotations

import json
from pathlib import Path

from dataworks_agent.scripts.verify_autonomous_query import evaluate_cases


def test_autonomous_query_golden_corpus_passes():
    cases = json.loads(
        Path("tests/evaluation/autonomous_query_cases.json").read_text(encoding="utf-8")
    )

    report = evaluate_cases(cases)

    assert report["total"] >= 40
    assert report["failures"] == []
    assert report["passed"] == report["total"]
