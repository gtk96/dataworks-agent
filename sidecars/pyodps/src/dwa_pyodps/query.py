"""Query executor for the sidecar.

The executor has two modes:

* **dry-run**: returns a deterministic synthetic result for any SQL. No
  network call is made and no pyodps import occurs. This lets the Bun
  supervisor exercise the protocol end-to-end without staging credentials.
* **real**: lazily imports pyodps and runs the SQL against an ODPS
  endpoint. Records are streamed lazily so we can truncate by ``max_rows``
  or ``max_bytes`` without ever loading the full result set in memory.

Cancellation is cooperative: the executor polls ``cancel_event`` between
records and aborts the underlying ODPS instance via
``Instance.pause()`` when set. A separate timeout is enforced by a watcher
thread that sets the same event.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import List, Optional, Sequence


@dataclass
class Column:
    name: str
    type: str


class _CancelledError(Exception):
    """Raised when a query is cancelled mid-flight."""


class _TimeoutError(Exception):
    """Raised when a query exceeds its timeout."""


def _dry_run_rows(sql: str) -> tuple[List[Column], List[List[object]], Optional[str]]:
    """Return a tiny synthetic result for dry-run mode.

    Real Aliyun ODPS columns and rows never appear here. The returned shape
    is intentionally generic so the protocol test can assert on ``columns``
    and ``rows`` without coupling to a production SQL.
    """
    normalised = " ".join(sql.strip().lower().split())
    if normalised == "select 1":
        return [Column("_c0", "BIGINT")], [[1]], None
    if normalised.startswith("show"):
        return [Column("name", "STRING"), Column("type", "STRING")], [["dry_run_table", "TABLE"]], None
    if normalised.startswith("desc") or normalised.startswith("describe"):
        return [Column("field", "STRING"), Column("type", "STRING")], [["id", "BIGINT"]], None
    # Default: one synthetic row carrying the parsed SQL fingerprint.
    return [Column("dry_run", "STRING")], [[f"row-for:{normalised[:32]}"]], None


def _normalise_row_size(row: Sequence[object]) -> int:
    return len(json.dumps(row, ensure_ascii=False))


def execute_query(
    *,
    params: dict,
    dry_run: bool,
    cancel_event: Event,
    timeout_ms: int,
    max_rows: int,
    max_bytes: int,
    client_factory=None,
) -> dict:
    """Execute a single ODPS query and return the result envelope payload.

    Returns a dict containing ``columns``, ``rows`` (pre-truncation), and
    ``instance_id``. Truncation is applied by ``protocol.truncate_rows``
    in the main loop so that test_protocol does not need to depend on the
    executor.
    """
    sql = str(params.get("sql") or "").strip()
    if not sql:
        raise ValueError("sql is required")
    project = str(params.get("project") or "")

    if dry_run:
        start = time.monotonic()
        while not cancel_event.wait(timeout=0):
            break
        if cancel_event.is_set():
            raise _CancelledError()
        columns, rows, instance_id = _dry_run_rows(sql)
        _ = project
        return {
            "columns": [{"name": c.name, "type": c.type} for c in columns],
            "rows": rows,
            "truncated": False,
            "instance_id": instance_id or "dry-run",
            "duration_ms": int((time.monotonic() - start) * 1000),
        }

    # Real mode — pyodps is imported lazily so dry-run works without it.
    from odps import ODPS  # type: ignore[import-not-found]

    access_key_id = str(params.get("access_key_id") or "")
    access_key_secret = str(params.get("access_key_secret") or "")
    endpoint = str(params.get("endpoint") or "")

    def _build_odps():
        return ODPS(
            access_key_id=access_key_id,
            secret_access_key=access_key_secret,
            project=project,
            endpoint=endpoint,
        )

    # A watcher thread fires the cancel event when the deadline expires.
    cancel_event.clear()

    def _watcher() -> None:
        deadline = timeout_ms / 1000.0 if timeout_ms > 0 else None
        if deadline is None:
            return
        if cancel_event.wait(timeout=deadline):
            return
        cancel_event.set()

    Thread(target=_watcher, daemon=True).start()
    start = time.monotonic()

    client = (client_factory or _build_odps)()
    instance = None
    try:
        instance = client.execute_sql(sql)
        columns: List[Column] = []
        rows: List[List[object]] = []
        budget = max_bytes if max_bytes > 0 else 0
        with instance.open_reader() as reader:
            schema_records = getattr(reader, "_schema", None)
            if schema_records is None:
                try:
                    schema_records = reader._source_schema  # type: ignore[attr-defined]
                except AttributeError:
                    schema_records = None
            for col in getattr(schema_records or [], "_columns", []) or []:
                columns.append(Column(col.name, str(col.type)))
            record_iter = reader
            for record in record_iter:
                if cancel_event.is_set():
                    raise _CancelledError()
                row_values = list(record.values)
                if budget:
                    if len(json.dumps(row_values).encode("utf-8")) > budget:
                        break
                rows.append(row_values)
                if len(rows) >= max_rows and max_rows > 0:
                    break
        return {
            "columns": [{"name": c.name, "type": c.type} for c in columns],
            "rows": rows,
            "truncated": False,
            "instance_id": str(getattr(instance, "id", None) or ""),
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
    finally:
        if instance is not None and cancel_event.is_set():
            try:
                instance.stop()
            except Exception:
                pass


def cancel_query() -> None:
    """Module-level hook to keep the public surface symmetric."""
    return None
