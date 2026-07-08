"""Load warehouse governance config from bundled YAML files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_WAREHOUSE_DIR = Path(__file__).resolve().parent.parent / "warehouse"

_LAYER_FILE_MAP: dict[str, str] = {
    "common": "common.yaml",
    "ods": "ods_layer.yaml",
    "dwd": "dwd_layer.yaml",
    "dws": "dws_layer.yaml",
    "dmr": "dmr_layer.yaml",
}


@lru_cache(maxsize=1)
def load_common_config() -> dict[str, Any]:
    path = _WAREHOUSE_DIR / "common.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_conventions(layer: str) -> dict[str, Any]:
    """Load YAML conventions for common / ods / dwd / dws / dmr."""
    layer_lower = layer.lower()
    filename = _LAYER_FILE_MAP.get(layer_lower)
    if filename is None:
        valid = ", ".join(sorted(_LAYER_FILE_MAP))
        raise ValueError(f"Unknown layer '{layer}'. Valid layers: {valid}")

    path = _WAREHOUSE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Convention file not found: {path}")

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_field_suffix_rules() -> list[dict[str, Any]]:
    return list(load_common_config().get("field_suffix_rules") or [])


def load_type_mapping() -> dict[str, Any]:
    return dict(load_common_config().get("type_mapping") or {})


def load_data_reference_rules() -> dict[str, Any]:
    return dict(load_common_config().get("data_reference_rules") or {})


def load_coding_standards() -> dict[str, Any]:
    return dict(load_common_config().get("coding_standards") or {})


def load_warehouse_standards_bundle() -> dict[str, Any]:
    """Aggregate YAML rules used by validation / type inference."""
    common = load_common_config()
    return {
        "version": common.get("version", 1),
        "subject_domains": load_subject_domains(),
        "update_modes": load_update_modes(),
        "field_suffix_rules": load_field_suffix_rules(),
        "type_mapping": load_type_mapping(),
        "data_reference_rules": load_data_reference_rules(),
        "coding_standards": load_coding_standards(),
        "layers": {
            layer: load_conventions(layer) for layer in _LAYER_FILE_MAP if layer != "common"
        },
    }


def load_subject_domains() -> list[dict[str, str]]:
    data = load_common_config()
    return [
        {
            "code": str(item.get("code", "")).upper(),
            "name_cn": str(item.get("name_cn", "")),
            "description": str(item.get("description", "")),
        }
        for item in data.get("subject_domains", [])
        if item.get("code")
    ]


def load_update_modes() -> list[dict[str, str]]:
    data = load_common_config()
    return [
        {
            "code": str(item.get("code", "")),
            "name_cn": str(item.get("name_cn", "")),
        }
        for item in data.get("update_modes", [])
        if item.get("code")
    ]


def load_bus_matrix_rules() -> dict[str, Any]:
    path = _WAREHOUSE_DIR / "bus_matrix" / "dimension_rules.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
