from __future__ import annotations

from dataworks_agent.services.ods_oss.directory_guard import (
    find_node_by_path,
    infer_existing_directory,
    node_record_uuid,
    normalize_node_path,
    parent_node_path,
)


def test_normalize_and_parent_path_are_non_destructive():
    path = "  ????/106_????/MaxCompute/????/00_ODS/node  "
    assert normalize_node_path(path) == "????/106_????/MaxCompute/????/00_ODS/node"
    assert parent_node_path(path) == "????/106_????/MaxCompute/????/00_ODS"


def test_existing_node_is_resolved_by_exact_script_path_only():
    records = [
        {"uuid": "wrong", "script": {"path": "????/00_ODS/node_other"}},
        {"uuid": "right", "script": {"path": "????/00_ODS/node"}},
    ]
    match = find_node_by_path(records, "????/00_ODS/node")
    assert match is not None
    assert node_record_uuid(match) == "right"
    assert find_node_by_path(records, "????/00_ODS/nope") is None


def test_directory_is_confirmed_only_from_positive_child_node_evidence():
    records = [{"Id": "n1", "Script": {"Path": "????/00_ODS/existing_node"}}]
    assert infer_existing_directory(records, "????/00_ODS") is True
    assert infer_existing_directory(records, "????/01_DWD") is False
