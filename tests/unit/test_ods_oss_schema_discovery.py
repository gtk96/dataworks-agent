"""Bounded OSS JSON schema discovery tests."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from dataworks_agent.services.ods_oss import schema_discovery


@dataclass
class FakeObject:
    key: str
    size: int


class FakeReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, size: int) -> bytes:
        return self.payload[:size]


class FakeBucket:
    def __init__(self, objects: list[FakeObject], payloads: dict[str, bytes]) -> None:
        self.objects = objects
        self.payloads = payloads

    def get_object(self, key: str) -> FakeReader:
        return FakeReader(self.payloads[key])


def install_fake_oss(monkeypatch: pytest.MonkeyPatch, files: dict[str, bytes]) -> FakeBucket:
    bucket = FakeBucket(
        [FakeObject(key=key, size=len(payload)) for key, payload in files.items()],
        files,
    )
    monkeypatch.setattr(schema_discovery, "_build_bucket", lambda location: bucket)
    monkeypatch.setattr(schema_discovery, "_endpoint_reachable", lambda endpoint: True)
    monkeypatch.setattr(
        schema_discovery.oss2,
        "ObjectIterator",
        lambda current_bucket, **kwargs: iter(current_bucket.objects),
    )
    return bucket


def test_discovers_json_lines_and_merges_scalar_types(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_oss(
        monkeypatch,
        {
            "ads/report/part-000.jsonl": (
                b'{"id":1,"cost":1,"enabled":true,"meta":{"a":1},"tags":["x"],"note":null}\n'
                b'{"id":2,"cost":1.5,"enabled":false,"meta":{"b":2},"tags":[],"note":"ok"}\n'
            )
        },
    )

    result = schema_discovery.discover_oss_schema("oss://bucket-name/ads/report/", "json")

    assert result["success"] is True
    assert result["sample_object"] == "ads/report/part-000.jsonl"
    assert result["record_count"] == 2
    assert result["columns"] == [
        {"name": "id", "type": "BIGINT"},
        {"name": "cost", "type": "DOUBLE"},
        {"name": "enabled", "type": "BOOLEAN"},
        {"name": "meta", "type": "STRING"},
        {"name": "tags", "type": "STRING"},
        {"name": "note", "type": "STRING"},
    ]


def test_discovers_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps([{"material_id": 1, "name": "a"}, {"material_id": 2, "name": "b"}]).encode()
    install_fake_oss(monkeypatch, {"ads/report/data.json": payload})

    result = schema_discovery.discover_oss_schema("oss://bucket-name/ads/report/", None)

    assert result["success"] is True
    assert result["file_format"] == "json"
    assert result["record_count"] == 2
    assert result["columns"] == [
        {"name": "material_id", "type": "BIGINT"},
        {"name": "name", "type": "STRING"},
    ]


def test_empty_prefix_returns_actionable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_oss(monkeypatch, {})

    result = schema_discovery.discover_oss_schema("oss://bucket-name/empty/", "json")

    assert result["success"] is False
    assert result["error_code"] == "empty_prefix"
    assert "ListObjects" in result["next_action"]


def test_invalid_json_returns_actionable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_oss(monkeypatch, {"ads/report/data.json": b"not-json"})

    result = schema_discovery.discover_oss_schema("oss://bucket-name/ads/report/", "json")

    assert result["success"] is False
    assert result["error_code"] == "invalid_sample"
    assert "UTF-8 JSON" in result["next_action"]


def test_unsafe_json_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_oss(monkeypatch, {"ads/report/data.json": b'{"bad-name":1}'})

    result = schema_discovery.discover_oss_schema("oss://bucket-name/ads/report/", "json")

    assert result["success"] is False
    assert result["error_code"] == "invalid_sample"
    assert "bad-name" in result["error"]


def test_endpoint_style_location_is_preserved_as_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_oss(monkeypatch, {"ads/report/data.json": b'{"id":1}'})

    result = schema_discovery.discover_oss_schema(
        "oss://oss-cn-shenzhen-internal.aliyuncs.com/bucket-name/ads/report/",
        "json",
    )

    assert result["success"] is True
    assert result["location"]["endpoint"] == "oss-cn-shenzhen-internal.aliyuncs.com"
    assert result["location"]["bucket"] == "bucket-name"

def test_internal_endpoint_network_error_retries_public_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket = FakeBucket(
        [FakeObject(key="ads/report/data.json", size=8)],
        {"ads/report/data.json": b'{"id":1}'},
    )
    endpoints: list[str] = []

    def build_bucket(location: dict[str, object]) -> FakeBucket:
        endpoint = str(location["endpoint"])
        endpoints.append(endpoint)
        if "-internal." in endpoint:
            raise schema_discovery.oss2.exceptions.RequestError(TimeoutError("timed out"))
        return bucket

    monkeypatch.setattr(schema_discovery, "_build_bucket", build_bucket)
    monkeypatch.setattr(schema_discovery, "_endpoint_reachable", lambda endpoint: True)
    monkeypatch.setattr(
        schema_discovery.oss2,
        "ObjectIterator",
        lambda current_bucket, **kwargs: iter(current_bucket.objects),
    )

    result = schema_discovery.discover_oss_schema(
        "oss://oss-cn-shenzhen-internal.aliyuncs.com/bucket-name/ads/report/",
        "json",
    )

    assert result["success"] is True
    assert endpoints == [
        "oss-cn-shenzhen-internal.aliyuncs.com",
        "oss-cn-shenzhen.aliyuncs.com",
    ]
    assert result["endpoint_used"] == "oss-cn-shenzhen.aliyuncs.com"
    assert result["attempted_endpoints"] == endpoints



def test_unreachable_internal_endpoint_skips_sdk_call_and_uses_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket = FakeBucket(
        [FakeObject(key="ads/report/data.json", size=8)],
        {"ads/report/data.json": b'{"id":1}'},
    )
    endpoints: list[str] = []

    def build_bucket(location: dict[str, object]) -> FakeBucket:
        endpoints.append(str(location["endpoint"]))
        return bucket

    monkeypatch.setattr(schema_discovery, "_build_bucket", build_bucket)
    monkeypatch.setattr(schema_discovery, "_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(
        schema_discovery.oss2,
        "ObjectIterator",
        lambda current_bucket, **kwargs: iter(current_bucket.objects),
    )

    result = schema_discovery.discover_oss_schema(
        "oss://oss-cn-shenzhen-internal.aliyuncs.com/bucket-name/ads/report/",
        "json",
    )

    assert result["success"] is True
    assert endpoints == ["oss-cn-shenzhen.aliyuncs.com"]
    assert result["attempted_endpoints"] == [
        "oss-cn-shenzhen-internal.aliyuncs.com",
        "oss-cn-shenzhen.aliyuncs.com",
    ]
