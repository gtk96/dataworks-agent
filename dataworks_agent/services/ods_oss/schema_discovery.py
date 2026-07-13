"""Bounded OSS sample discovery and JSON schema inference."""

from __future__ import annotations

import json
import logging
import re
import socket
import time
from itertools import islice
from typing import Any
from urllib.parse import urlsplit

import oss2

from dataworks_agent.auth import CredentialMissingError, load_credentials
from dataworks_agent.config import settings
from dataworks_agent.services.ods_oss.config import (
    SUPPORTED_FILE_FORMATS,
    infer_file_format,
    parse_oss_path,
)

logger = logging.getLogger(__name__)

_MAX_OBJECTS = 50
_MAX_SAMPLE_BYTES = 1024 * 1024
_MAX_RECORDS = 100
_SAFE_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_SAFE_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JSON_SUFFIXES = (".json", ".jsonl", ".ndjson")


def _endpoint_url(endpoint: str) -> str:
    host = endpoint.strip() or f"oss-{settings.dataworks_region}.aliyuncs.com"
    return host if host.startswith(("http://", "https://")) else f"https://{host}"


def _endpoint_reachable(endpoint: str, timeout_seconds: float = 1.5) -> bool:
    """Fail fast when an internal endpoint is unreachable from this runtime."""
    host = urlsplit(_endpoint_url(endpoint)).hostname
    if not host:
        return False
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False

    deadline = time.monotonic() + timeout_seconds
    for family, sock_type, proto, _, address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with socket.socket(family, sock_type, proto) as connection:
                connection.settimeout(remaining)
                connection.connect(address)
                return True
        except OSError:
            continue
    return False


def _build_bucket(location: dict[str, Any]) -> Any:
    credentials = load_credentials()
    auth = oss2.Auth(credentials.access_key_id, credentials.access_key_secret)
    return oss2.Bucket(
        auth,
        _endpoint_url(str(location.get("endpoint") or "")),
        str(location["bucket"]),
        region=settings.dataworks_region,
        connect_timeout=5,
    )


def _object_format(key: str) -> str:
    lowered = key.lower()
    if lowered.endswith(_JSON_SUFFIXES):
        return "json"
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith(".parquet"):
        return "parquet"
    return ""


def _select_object(
    bucket: Any,
    location: dict[str, Any],
    requested_format: str,
) -> tuple[Any | None, str, list[str]]:
    object_key = str(location.get("object_key") or "")
    prefix = f"{object_key.rstrip('/')}" if object_key else ""
    if location.get("is_prefix") and prefix:
        prefix += "/"

    objects = [
        item
        for item in islice(
            oss2.ObjectIterator(bucket, prefix=prefix, max_keys=_MAX_OBJECTS),
            _MAX_OBJECTS,
        )
        if item.key and not item.key.endswith("/") and int(getattr(item, "size", 0) or 0) > 0
    ]
    if not objects:
        return None, requested_format, []

    exact = next((item for item in objects if item.key == object_key), None)
    candidates = [exact] if exact is not None else objects
    candidates = [item for item in candidates if item is not None]
    detected_formats = sorted(
        {fmt for item in candidates if (fmt := _object_format(str(item.key)))}
    )

    selected_format = requested_format
    if not selected_format:
        if len(detected_formats) > 1:
            return None, "", detected_formats
        selected_format = detected_formats[0] if detected_formats else ""
    if selected_format:
        matching = [
            item
            for item in candidates
            if not _object_format(str(item.key)) or _object_format(str(item.key)) == selected_format
        ]
        if matching:
            candidates = matching
    return candidates[0], selected_format, detected_formats


def _read_sample(bucket: Any, key: str) -> tuple[bytes, bool]:
    result = bucket.get_object(key)
    payload = result.read(_MAX_SAMPLE_BYTES + 1)
    truncated = len(payload) > _MAX_SAMPLE_BYTES
    return payload[:_MAX_SAMPLE_BYTES], truncated


def _scan_json_array(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    records: list[dict[str, Any]] = []
    index = 1
    while index < len(text) and len(records) < _MAX_RECORDS:
        while index < len(text) and text[index] in " \r\n\t,":
            index += 1
        if index >= len(text) or text[index] == "]":
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            records.append(value)
    return records


def _parse_json_records(payload: bytes, truncated: bool) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("JSON 样本不是 UTF-8 编码") from exc
    stripped = text.strip()
    if not stripped:
        raise ValueError("JSON 样本为空")

    if not truncated:
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            records = [item for item in value[:_MAX_RECORDS] if isinstance(item, dict)]
            if records:
                return records

    records: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        if len(records) >= _MAX_RECORDS:
            break
        line = line.strip().rstrip(",")
        if not line or line in {"[", "]"}:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    if records:
        return records

    if stripped.startswith("["):
        records = _scan_json_array(stripped)
        if records:
            return records
    raise ValueError("未在有限样本中识别到 JSON 对象或 JSON Lines 记录")


def _value_type(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "BIGINT"
    if isinstance(value, float):
        return "DOUBLE"
    return "STRING"


def _merge_types(current: str, incoming: str) -> str:
    if current == incoming:
        return current
    if current == "NULL":
        return incoming
    if incoming == "NULL":
        return current
    if {current, incoming} <= {"BIGINT", "DOUBLE"}:
        return "DOUBLE"
    return "STRING"


def infer_json_columns(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Infer stable MaxCompute scalar types from JSON object samples."""
    inferred: dict[str, str] = {}
    invalid_names: list[str] = []
    for record in records:
        for raw_name, value in record.items():
            name = str(raw_name)
            if not _SAFE_COLUMN.fullmatch(name) or "`" in name:
                invalid_names.append(name)
                continue
            incoming = _value_type(value)
            inferred[name] = _merge_types(inferred.get(name, "NULL"), incoming)

    if invalid_names:
        preview = "、".join(dict.fromkeys(invalid_names[:5]))
        raise ValueError(f"JSON 含不安全或不兼容的字段名：{preview}")
    reserved = [name for name in inferred if name.lower() in {"dt", "ht"}]
    if reserved:
        raise ValueError(f"JSON 字段与 ODS 分区字段冲突：{'、'.join(reserved)}")
    if not inferred:
        raise ValueError("JSON 样本中没有可建表的对象字段")
    return [
        {"name": name, "type": "STRING" if data_type == "NULL" else data_type}
        for name, data_type in inferred.items()
    ]


def _failure(
    *,
    location: dict[str, Any] | None,
    file_format: str,
    code: str,
    error: str,
    next_action: str,
    detected_formats: list[str] | None = None,
    endpoint_used: str = "",
    attempted_endpoints: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "location": location or {},
        "file_format": file_format,
        "error_code": code,
        "error": error,
        "next_action": next_action,
        "detected_formats": detected_formats or [],
        "endpoint_used": endpoint_used,
        "attempted_endpoints": attempted_endpoints or [],
    }


def _endpoint_candidates(location: dict[str, Any]) -> list[str]:
    requested = str(location.get("endpoint") or "").strip()
    primary = requested or f"oss-{settings.dataworks_region}.aliyuncs.com"
    candidates = [primary]
    if "-internal." in primary:
        public = primary.replace("-internal.", ".", 1)
        if public not in candidates:
            candidates.append(public)
    return candidates


def _with_endpoint(location: dict[str, Any], endpoint: str) -> dict[str, Any]:
    candidate = dict(location)
    candidate["endpoint"] = endpoint
    return candidate


def _discover_sample(
    location: dict[str, Any],
    requested_format: str,
) -> dict[str, Any]:
    bucket = _build_bucket(location)
    selected, selected_format, detected_formats = _select_object(bucket, location, requested_format)
    if selected is None:
        if detected_formats:
            return _failure(
                location=location,
                file_format="",
                code="ambiguous_format",
                error=f"目录中检测到多种文件格式：{', '.join(detected_formats)}",
                next_action="请明确文件格式，例如“文件格式是 JSON”。",
                detected_formats=detected_formats,
            )
        return _failure(
            location=location,
            file_format=requested_format,
            code="empty_prefix",
            error="OSS 路径下未找到可读取的非空对象",
            next_action="请检查路径是否正确、目录是否有数据，以及 AK/SK 是否具备 ListObjects 权限。",
        )
    if not selected_format:
        return _failure(
            location=location,
            file_format="",
            code="format_required",
            error="对象没有可识别的文件扩展名",
            next_action="请明确文件格式，例如“文件格式是 JSON”。",
        )
    if selected_format != "json":
        return _failure(
            location=location,
            file_format=selected_format,
            code="schema_discovery_not_supported",
            error=f"{selected_format.upper()} 自动字段推断尚未接入",
            next_action="请直接提供字段定义，或改用 JSON 样本自动发现。",
        )

    payload, truncated = _read_sample(bucket, str(selected.key))
    records = _parse_json_records(payload, truncated)
    columns = infer_json_columns(records)
    result = {
        "success": True,
        "location": location,
        "file_format": selected_format,
        "sample_object": str(selected.key),
        "sample_bytes": len(payload),
        "sample_truncated": truncated,
        "record_count": len(records),
        "columns": columns,
    }
    logger.info(
        "OSS schema discovered bucket=%s key=%s records=%d columns=%d bytes=%d",
        location["bucket"],
        selected.key,
        len(records),
        len(columns),
        len(payload),
    )
    return result


def _oss_error_detail(exc: oss2.exceptions.OssError) -> tuple[str, str]:
    code = str(getattr(exc, "code", "") or exc.__class__.__name__)
    message = str(getattr(exc, "message", "") or "").strip()
    if isinstance(exc, oss2.exceptions.RequestError):
        underlying = getattr(exc, "exception", None)
        underlying_text = str(underlying or "").strip() or repr(underlying)
        message = underlying_text if underlying_text and underlying_text != "None" else message
    detail = f"{code}: {message or str(exc)}"
    request_id = str(getattr(exc, "request_id", "") or "")
    if request_id:
        detail += f" (RequestId: {request_id})"
    return code, detail


def discover_oss_schema(oss_path: str, file_format: str | None = None) -> dict[str, Any]:
    """List a bounded prefix, read at most 1 MiB, and infer JSON columns.

    Internal endpoints are attempted first. If the current runtime cannot reach the
    Alibaba Cloud internal network, discovery retries once through the public
    regional endpoint and keeps both attempts as user-visible evidence.
    """
    try:
        location = parse_oss_path(oss_path)
    except ValueError as exc:
        return _failure(
            location=None,
            file_format="",
            code="invalid_location",
            error=str(exc),
            next_action="请提供有效的 oss://bucket/path 或 endpoint/bucket/path 地址。",
        )

    bucket_name = str(location["bucket"])
    if not _SAFE_BUCKET.fullmatch(bucket_name):
        return _failure(
            location=location,
            file_format="",
            code="invalid_bucket",
            error=f"OSS bucket 名称不合法：{bucket_name}",
            next_action="请检查 endpoint 风格地址中 endpoint 与 bucket 的位置。",
        )

    requested_format = infer_file_format(oss_path, file_format)
    if requested_format and requested_format not in SUPPORTED_FILE_FORMATS:
        return _failure(
            location=location,
            file_format=requested_format,
            code="unsupported_format",
            error=f"不支持的 OSS 文件格式：{requested_format}",
            next_action="目前支持 JSON、CSV、Parquet；请明确其中一种格式。",
        )

    attempted: list[str] = []
    endpoint_candidates = _endpoint_candidates(location)
    for endpoint in endpoint_candidates:
        attempted.append(endpoint)
        if (
            "-internal." in endpoint
            and endpoint != endpoint_candidates[-1]
            and not _endpoint_reachable(endpoint)
        ):
            logger.warning(
                "OSS internal endpoint preflight failed, using public endpoint: %s",
                endpoint,
            )
            continue
        candidate = _with_endpoint(location, endpoint)
        try:
            result = _discover_sample(candidate, requested_format)
            result["location"] = location
            result["endpoint_used"] = endpoint
            result["attempted_endpoints"] = list(attempted)
            return result
        except CredentialMissingError as exc:
            return _failure(
                location=location,
                file_format=requested_format,
                code="credential_missing",
                error=str(exc),
                next_action="请在本地环境配置 OSS 可读 AK/SK 后重试；凭证不会写入仓库。",
                endpoint_used=endpoint,
                attempted_endpoints=attempted,
            )
        except oss2.exceptions.RequestError as exc:
            if endpoint != endpoint_candidates[-1]:
                logger.warning("OSS endpoint unreachable, retrying public endpoint: %s", endpoint)
                continue
            code, detail = _oss_error_detail(exc)
            return _failure(
                location=location,
                file_format=requested_format,
                code=code.lower(),
                error=detail,
                next_action=(
                    "当前 OSS endpoint 无法连通；请检查网络、DNS 或地域 endpoint，"
                    "如使用 internal endpoint，请确认运行环境在阿里云内网。"
                ),
                endpoint_used=endpoint,
                attempted_endpoints=attempted,
            )
        except oss2.exceptions.OssError as exc:
            code, detail = _oss_error_detail(exc)
            return _failure(
                location=location,
                file_format=requested_format,
                code=code.lower(),
                error=detail,
                next_action=(
                    "OSS endpoint 已连通，但 AK/SK 无权读取该路径。"
                    "请为 bucket/prefix 授予 ListObjects、GetObject 最小读权限，"
                    "或在当前对话直接提供字段定义。"
                ),
                endpoint_used=endpoint,
                attempted_endpoints=attempted,
            )
        except (ValueError, UnicodeError) as exc:
            return _failure(
                location=location,
                file_format=requested_format,
                code="invalid_sample",
                error=str(exc),
                next_action="请确认样本是有效的 UTF-8 JSON/JSON Lines，或直接提供字段定义。",
                endpoint_used=endpoint,
                attempted_endpoints=attempted,
            )
        except Exception as exc:  # pragma: no cover - SDK/network defensive boundary
            logger.exception("Unexpected OSS schema discovery failure")
            return _failure(
                location=location,
                file_format=requested_format,
                code="discovery_failed",
                error=f"OSS 字段探测失败：{exc}",
                next_action="请检查 endpoint 与 OSS 读权限，或直接提供字段定义。",
                endpoint_used=endpoint,
                attempted_endpoints=attempted,
            )

    return _failure(  # pragma: no cover - endpoint candidates are never empty
        location=location,
        file_format=requested_format,
        code="discovery_failed",
        error="未找到可用的 OSS endpoint",
        next_action="请检查 OSS endpoint 配置。",
        attempted_endpoints=attempted,
    )
