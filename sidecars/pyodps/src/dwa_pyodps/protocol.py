"""Pure NDJSON protocol layer used by the sidecar.

This module contains no I/O and no third-party imports so that it can be
unit tested without touching pyodps. The main loop in ``__main__.py`` calls
into these helpers to validate each stdin line and to format stdout
responses.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# 16 MB hard cap on a single line — matches the Bun supervisor requirement.
MAX_LINE_BYTES = 16 * 1024 * 1024

# Recognised request methods — anything else is rejected with PARSE_ERROR.
KNOWN_METHODS = frozenset({"query", "cancel", "health"})


class ParseError(Exception):
    """Raised when a request line cannot be coerced into the protocol."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class RequestEnvelope:
    """A parsed NDJSON request, independent of the underlying transport."""

    id: str
    method: str
    params: dict


def decode_request(raw: bytes) -> RequestEnvelope:
    """Validate one stdin line and return the structured envelope.

    On failure a :class:`ParseError` is raised with a stable machine code.
    The caller is expected to translate the error into a single NDJSON
    response line so the supervisor never sees a Python traceback.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise ParseError("INVALID_SHAPE", "request must be bytes")
    raw_bytes = bytes(raw)
    if len(raw_bytes) > MAX_LINE_BYTES:
        raise ParseError(
            "LINE_TOO_LONG",
            f"line exceeds {MAX_LINE_BYTES} bytes (got {len(raw_bytes)})",
        )
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("INVALID_UTF8", f"non-utf8 bytes: {exc.reason}") from None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError("INVALID_JSON", f"json decode failed: {exc.msg}") from None
    if not isinstance(obj, dict):
        raise ParseError("INVALID_SHAPE", "request must be a JSON object")
    if "id" not in obj:
        raise ParseError("MISSING_ID", "id is required")
    if not isinstance(obj["id"], str) or not obj["id"]:
        raise ParseError("MISSING_ID", "id must be a non-empty string")
    if "method" not in obj:
        raise ParseError("MISSING_METHOD", "method is required")
    if not isinstance(obj["method"], str):
        raise ParseError("MISSING_METHOD", "method must be a string")
    if obj["method"] not in KNOWN_METHODS:
        raise ParseError("UNKNOWN_METHOD", f"method {obj['method']} not supported")
    params = obj.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ParseError("INVALID_PARAMS", "params must be an object")
    if obj["method"] == "cancel" and not isinstance(params.get("id"), str):
        raise ParseError("MISSING_CANCEL_TARGET", "cancel.params.id is required")
    return RequestEnvelope(id=obj["id"], method=obj["method"], params=params)


def encode_result(req_id: str, result: dict) -> bytes:
    """Format a successful response line and append a trailing newline."""
    if not isinstance(req_id, str) or not req_id:
        raise ValueError("req_id must be a non-empty string")
    payload = {"id": req_id, "result": result}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def encode_error(req_id: str, code: str, message: str, retryable: bool = False) -> bytes:
    """Format an error response line and append a trailing newline.

    ``req_id`` is allowed to be the empty string when the upstream line could
    not be parsed (no id was available).
    """
    if not isinstance(req_id, str):
        raise ValueError("req_id must be a string")
    payload = {
        "id": req_id,
        "error": {
            "code": code,
            "message": message,
            "retryable": bool(retryable),
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def _cell_size(cell: object) -> int:
    if cell is None:
        return 4  # "null"
    if isinstance(cell, bool):
        return 1 if cell else 0
    return len(str(cell))


def _row_size(row: Sequence[object]) -> int:
    return sum(_cell_size(cell) for cell in row)


def truncate_rows(
    rows: Iterable[Sequence[object]],
    _columns: Sequence[dict],
    max_rows: int,
    max_bytes: int,
) -> tuple[list[Sequence[object]], bool]:
    """Walk ``rows`` and emit the prefix that fits within the limits.

    The byte budget is computed from the JSON-serialised row including the
    brackets and commas. The function returns ``(out_rows, truncated)``.
    ``max_rows`` and ``max_bytes`` are upper bounds; pass any positive
    integer to disable a limit.
    """
    out: list[Sequence[object]] = []
    total = 2  # opening + closing bracket of the JSON array
    for used_rows, row in enumerate(rows):
        if used_rows >= max_rows:
            return out, True
        cell_bytes = sum(_cell_size(cell) + 1 for cell in row)  # +1 for comma
        # First row keeps opening [ and no leading comma.
        boundary = total + (1 if used_rows else 0)
        if boundary + cell_bytes > max_bytes:
            return out, True
        total = boundary + cell_bytes
        out.append(list(row))
    return out, False
