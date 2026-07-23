"""Tests for the sidecar NDJSON protocol layer."""

import json
import math

import pytest
from dwa_pyodps.protocol import (
    ParseError,
    decode_request,
    encode_error,
    encode_result,
    truncate_rows,
)


def _row_bytes(*cells: object) -> int:
    total = 0
    for cell in cells:
        if cell is None:
            total += 4
        else:
            total += len(str(cell))
    return total


def test_decode_malformed_json_raises_parse_error_with_invalid_json_code() -> None:
    with pytest.raises(ParseError) as exc:
        decode_request(b"{not valid json")
    assert exc.value.code == "INVALID_JSON"


def test_decode_non_object_payload_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        decode_request(b"[1, 2, 3]")
    assert exc.value.code == "INVALID_SHAPE"


def test_decode_missing_id_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        decode_request(json.dumps({"method": "query"}).encode("utf-8"))
    assert exc.value.code == "MISSING_ID"


def test_decode_missing_method_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        decode_request(json.dumps({"id": "req_01"}).encode("utf-8"))
    assert exc.value.code == "MISSING_METHOD"


def test_decode_unknown_method_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        decode_request(json.dumps({"id": "x", "method": "drop"}).encode("utf-8"))
    assert exc.value.code == "UNKNOWN_METHOD"


def test_decode_query_request_returns_envelope() -> None:
    payload = {
        "id": "req_01",
        "method": "query",
        "params": {
            "endpoint": "https://example.odps",
            "project": "proj",
            "sql": "select 1",
            "timeout_ms": 5000,
            "max_rows": 10,
            "max_bytes": 1024,
            "access_key_id": "AK",
            "access_key_secret": "SK",
        },
    }
    envelope = decode_request(json.dumps(payload).encode("utf-8"))
    assert envelope.id == "req_01"
    assert envelope.method == "query"
    assert envelope.params["sql"] == "select 1"


def test_decode_health_request_returns_envelope() -> None:
    payload = {"id": "req_health", "method": "health"}
    envelope = decode_request(json.dumps(payload).encode("utf-8"))
    assert envelope.method == "health"


def test_truncate_respects_max_rows() -> None:
    rows = [[i] for i in range(100)]
    out, truncated = truncate_rows(rows, [{"name": "x"}], max_rows=5, max_bytes=10_000_000)
    assert len(out) == 5
    assert truncated is True


def test_truncate_no_truncation_when_below_both_limits() -> None:
    rows = [[i] for i in range(3)]
    out, truncated = truncate_rows(rows, [{"name": "x"}], max_rows=10, max_bytes=10_000)
    assert len(out) == 3
    assert truncated is False


def test_truncate_respects_max_bytes_caps_total_size() -> None:
    rows = [["a" * 500] for _ in range(100)]
    out, truncated = truncate_rows(rows, [{"name": "x"}], max_rows=10_000, max_bytes=2_000)
    rendered = json.dumps(out).encode("utf-8")
    assert len(rendered) <= 2_000
    assert truncated is True


def test_truncate_byte_limit_is_exact_for_short_rows() -> None:
    rows = [[f"row_{i}"] for i in range(50)]
    out, truncated = truncate_rows(rows, [{"name": "n"}], max_rows=10_000, max_bytes=120)
    assert truncated is True
    assert len(out) < 50


def test_truncate_byte_limit_zero_returns_no_rows() -> None:
    rows = [["anything"], ["more"]]
    out, truncated = truncate_rows(rows, [{"name": "n"}], max_rows=100, max_bytes=0)
    assert out == []
    assert truncated is True


def test_truncate_handles_null_cells_for_byte_accounting() -> None:
    rows = [[None, "abc"], ["x", None]]
    out, truncated = truncate_rows(rows, [{"name": "a"}, {"name": "b"}], max_rows=10, max_bytes=128)
    assert len(out) == 2
    assert truncated is False


def test_cancel_request_parses_with_target_id() -> None:
    payload = {"id": "req_cancel", "method": "cancel", "params": {"id": "req_01"}}
    envelope = decode_request(json.dumps(payload).encode("utf-8"))
    assert envelope.method == "cancel"
    assert envelope.params["id"] == "req_01"


def test_cancel_request_missing_target_id_raises_parse_error() -> None:
    payload = {"id": "req_cancel", "method": "cancel"}
    with pytest.raises(ParseError) as exc:
        decode_request(json.dumps(payload).encode("utf-8"))
    assert exc.value.code == "MISSING_CANCEL_TARGET"


def test_encode_result_produces_single_line_with_id_and_result() -> None:
    line = encode_result("req_01", {"ok": True, "value": 42})
    text = line.decode("utf-8")
    assert "\n" in text
    assert text.count("\n") == 1
    parsed = json.loads(text.strip())
    assert parsed["id"] == "req_01"
    assert parsed["result"]["ok"] is True
    assert parsed["result"]["value"] == 42


def test_encode_error_produces_single_line_with_id_error_code_message_retryable() -> None:
    line = encode_error("req_01", "TIMEOUT", "Query exceeded 5000ms", retryable=False)
    text = line.decode("utf-8")
    parsed = json.loads(text.strip())
    assert parsed["id"] == "req_01"
    assert parsed["error"]["code"] == "TIMEOUT"
    assert parsed["error"]["message"] == "Query exceeded 5000ms"
    assert parsed["error"]["retryable"] is False


def test_decode_oversized_line_raises_parse_error() -> None:
    huge = b"a" * (16 * 1024 * 1024 + 1)
    with pytest.raises(ParseError) as exc:
        decode_request(huge)
    assert exc.value.code == "LINE_TOO_LONG"


def test_truncate_numeric_and_floating_cells() -> None:
    rows = [[1, 2.5], [3, math.pi]]
    out, truncated = truncate_rows(
        rows, [{"name": "a"}, {"name": "b"}], max_rows=10, max_bytes=1024
    )
    assert out == rows
    assert truncated is False
