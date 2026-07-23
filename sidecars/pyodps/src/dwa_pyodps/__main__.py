"""Supervisor process: NDJSON over stdin/stdout with diagnostics on stderr.

The main loop reads one JSON object per stdin line, dispatches the request
to either the cancel or the query handler, and writes a single JSON object
per stdout line. stderr carries any human-readable diagnostics — never
credentials, never SQL literals.

A bounded thread pool caps in-flight queries at 4. Cancellation is
cooperative: a ``cancel`` request sets the ``threading.Event`` that the
query watcher watches, causing the executor to raise a ``_CancelledError``
which the main loop translates into a typed protocol error.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from threading import Event, Semaphore

from .protocol import (
    ParseError,
    RequestEnvelope,
    decode_request,
    truncate_rows,
)

# pyodps is optional — only required in real mode.
with contextlib.suppress(ImportError):  # pragma: no cover - module is always present
    from .query import _CancelledError, _TimeoutError


MAX_CONCURRENT = 4

# Codes used by the supervisor; chosen for stability under version skew.
PROTOCOL_ERROR_CODES = {
    "INVALID_JSON",
    "INVALID_SHAPE",
    "INVALID_UTF8",
    "MISSING_ID",
    "MISSING_METHOD",
    "UNKNOWN_METHOD",
    "INVALID_PARAMS",
    "MISSING_CANCEL_TARGET",
    "LINE_TOO_LONG",
    "BUSY",
    "QUERY_FAILED",
    "TIMEOUT",
    "CANCELLED",
    "UPSTREAM_ERROR",
    "INTERNAL",
}


def _log(level: str, message: str, **fields: object) -> None:
    """Write a single structured diagnostic line to stderr.

    Credentials and SQL literals are never included in ``fields`` or
    ``message``. Use only counts and IDs.
    """
    payload = {"ts": time.time(), "level": level, "message": message}
    for key, value in fields.items():
        payload[key] = value
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stderr.flush()


class Sidecar:
    def __init__(self, *, dry_run: bool, version: str = "0.1.0") -> None:
        self.dry_run = dry_run
        self.version = version
        self._write_lock = threading.Lock()
        self._out = sys.stdout.buffer
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, Event] = {}
        self._slots = Semaphore(MAX_CONCURRENT)
        self._seq = 0
        self._seq_lock = threading.Lock()

    # -- output helpers ----------------------------------------------------
    def _write_line(self, payload: dict) -> None:
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            self._out.write(line)
            self._out.flush()

    def _send_result(self, req_id: str, result: dict) -> None:
        self._write_line({"id": req_id, "result": result})

    def _send_error(self, req_id: str | None, code: str, message: str, retryable: bool) -> None:
        rid = req_id if isinstance(req_id, str) else ""
        self._write_line(
            {
                "id": rid,
                "error": {"code": code, "message": message, "retryable": retryable},
            }
        )

    # -- request dispatch ---------------------------------------------------
    def handle_raw(self, raw: bytes) -> None:
        try:
            envelope = decode_request(raw)
        except ParseError as exc:
            self._send_error(None, exc.code, exc.message, exc.retryable)
            _log("warn", "protocol_parse_error", code=exc.code)
            return
        if envelope.method == "health":
            self._send_result(
                envelope.id, {"ok": True, "version": self.version, "dry_run": self.dry_run}
            )
            return
        if envelope.method == "cancel":
            target = envelope.params.get("id")
            with self._inflight_lock:
                ev = self._inflight.get(target or "")
            if isinstance(ev, Event):
                ev.set()
                self._send_result(envelope.id, {"ok": True, "cancelled": target})
            else:
                self._send_result(envelope.id, {"ok": False, "reason": "no_inflight_query"})
            return
        if envelope.method == "query":
            self._dispatch_query(envelope)
            return
        # Should be unreachable because decode_request already enforces KNOWN_METHODS.
        self._send_error(envelope.id, "UNKNOWN_METHOD", envelope.method, retryable=False)

    # -- query execution ---------------------------------------------------
    def _allocate_id(self, prefix: str) -> str:
        with self._seq_lock:
            self._seq += 1
            return f"{prefix}_{self._seq}"

    def _dispatch_query(self, envelope: RequestEnvelope) -> None:
        if not self._slots.acquire(blocking=False):
            self._send_error(
                envelope.id,
                "BUSY",
                f"max {MAX_CONCURRENT} concurrent queries in flight",
                retryable=True,
            )
            return
        cancel_event = Event()
        with self._inflight_lock:
            self._inflight[envelope.id] = cancel_event
        thread = threading.Thread(
            target=self._run_query,
            args=(envelope, cancel_event),
            daemon=True,
            name=f"odps-query-{envelope.id}",
        )
        thread.start()

    def _run_query(self, envelope: RequestEnvelope, cancel_event: Event) -> None:
        start = time.monotonic()
        try:
            # pyodps is an optional dependency; only the real executor needs it.
            from .query import execute_query  # type: ignore[attr-not-found]

            timeout_ms = int(envelope.params.get("timeout_ms") or 300_000)
            max_rows = int(envelope.params.get("max_rows") or 10_000)
            max_bytes = int(envelope.params.get("max_bytes") or 10 * 1024 * 1024)

            result = execute_query(
                params=envelope.params,
                dry_run=self.dry_run,
                cancel_event=cancel_event,
                timeout_ms=timeout_ms,
                max_rows=max_rows,
                max_bytes=max_bytes,
            )

            result.setdefault("duration_ms", int((time.monotonic() - start) * 1000))
            result["duration_ms"] = int((time.monotonic() - start) * 1000)
            columns = result.get("columns") or []
            truncated_rows, truncated = truncate_rows(
                result.get("rows") or [], columns, max_rows, max_bytes
            )
            result["rows"] = truncated_rows
            result["truncated"] = truncated or bool(result.get("truncated", False))
            result["duration_ms"] = int((time.monotonic() - start) * 1000)

            self._send_result(envelope.id, result)
        except _CancelledError:
            self._send_error(
                envelope.id, "CANCELLED", "query cancelled by supervisor", retryable=False
            )
        except _TimeoutError as exc:
            self._send_error(
                envelope.id, "TIMEOUT", str(exc) or "query exceeded timeout", retryable=False
            )
        except Exception as exc:
            self._send_error(
                envelope.id,
                "QUERY_FAILED",
                str(exc) or exc.__class__.__name__,
                retryable=True,
            )
            _log("warn", "query_failed", id=envelope.id, type=exc.__class__.__name__)
        finally:
            with self._inflight_lock:
                self._inflight.pop(envelope.id, None)
            self._slots.release()


def _detect_dry_run() -> bool:
    env_value = os.environ.get("DWA_PYODPS_DRY_RUN")
    if env_value and env_value.lower() in {"1", "true", "yes"}:
        return True
    return any(arg == "--dry-run" for arg in sys.argv[1:])


def main() -> int:
    dry_run = _detect_dry_run()
    sidecar = Sidecar(dry_run=dry_run)
    _log("info", "sidecar_started", dry_run=dry_run, version=sidecar.version)
    try:
        for raw in sys.stdin.buffer:
            if not raw:
                continue
            sidecar.handle_raw(raw)
    except KeyboardInterrupt:
        _log("info", "sidecar_interrupted")
        return 0
    _log("info", "sidecar_stdin_closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
