"""FlowSpec 构建器单元测试（Task 8b）— 结构对齐真机 get_node().Node.Spec。"""

from __future__ import annotations

import json

import pytest

from dataworks_agent.api_clients.flowspec import build_node_flowspec
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS


def _build(**overrides):
    kwargs = {
        "name": "dwd_mkt_ad_group_hourly",
        "script_content": "insert overwrite table dwd_mkt_ad_group_hourly select 1",
        "script_path": "业务流程/测试/02_DWD/dwd_mkt_ad_group_hourly",
        "output_ref": "dataworks.dwd_mkt_ad_group_hourly",
        "cron": "00 30 00-23/1 * * ?",
        "cycle_type": "NotDaily",
        "parameters": HOURLY_SQL_PARAMETERS,
    }
    kwargs.update(overrides)
    return json.loads(build_node_flowspec(**kwargs))


class TestDILanguage:
    def test_di_node_shape(self):
        """DI 节点：language=json、runtime.command=DI/commandTypeId=23、datasource=null。"""
        datax = '{"type":"job","version":"2.0","steps":[]}'
        spec = _build(
            language="di", script_content=datax, cron="00 30 06 * * ?", cycle_type="Daily"
        )
        node = spec["spec"]["nodes"][0]
        assert node["datasource"] is None
        assert node["script"]["language"] == "json"
        assert node["script"]["runtime"]["command"] == "DI"
        assert node["script"]["runtime"]["commandTypeId"] == 23
        assert node["script"]["content"] == datax

    def test_sql_node_keeps_datasource(self):
        spec = _build()
        node = spec["spec"]["nodes"][0]
        assert node["datasource"] == {"name": "dataworks", "type": "odps"}
        assert node["script"]["language"] == "odps-sql"


class TestEnvelope:
    def test_version_and_kind(self):
        spec = _build()
        assert spec["version"] == "1.1.0"
        assert spec["kind"] == "CycleWorkflow"
        assert len(spec["spec"]["nodes"]) == 1

    def test_returns_json_string(self):
        out = build_node_flowspec(
            name="t",
            script_content="select 1",
            script_path="p",
            output_ref="dataworks.t",
            cron="00 30 00-23/1 * * ?",
        )
        assert isinstance(out, str)
        assert json.loads(out)["kind"] == "CycleWorkflow"


class TestScript:
    def test_odps_runtime(self):
        node = _build()["spec"]["nodes"][0]
        assert node["script"]["language"] == "odps-sql"
        assert node["script"]["runtime"]["command"] == "ODPS_SQL"
        assert node["script"]["runtime"]["commandTypeId"] == 10
        assert node["script"]["runtime"]["cu"] == "0.25"
        assert node["datasource"] == {"name": "dataworks", "type": "odps"}

    def test_holo_runtime(self):
        node = _build(language="holo")["spec"]["nodes"][0]
        assert node["script"]["runtime"]["command"] == "HOLOGRES_SQL"
        # 真机核实 Holo commandTypeId=1093
        assert node["script"]["runtime"]["commandTypeId"] == 1093
        assert node["datasource"]["type"] == "holo"

    def test_content_and_path(self):
        node = _build()["spec"]["nodes"][0]
        assert node["script"]["content"].startswith("insert overwrite table")
        assert node["script"]["path"].endswith("dwd_mkt_ad_group_hourly")

    def test_parameters_mapped_to_variable(self):
        node = _build()["spec"]["nodes"][0]
        params = node["script"]["parameters"]
        assert len(params) == len(HOURLY_SQL_PARAMETERS)
        for p in params:
            assert p["artifactType"] == "Variable"
            assert p["scope"] == "NodeParameter"
            assert p["type"] == "System"
            assert "name" in p and "value" in p

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError):
            build_node_flowspec(
                name="t",
                script_content="x",
                script_path="p",
                output_ref="dataworks.t",
                cron="c",
                language="spark-sql",
            )


class TestTrigger:
    def test_trigger_fields(self):
        node = _build()["spec"]["nodes"][0]
        trig = node["trigger"]
        assert trig["type"] == "Scheduler"
        assert trig["cron"] == "00 30 00-23/1 * * ?"
        assert trig["cycleType"] == "NotDaily"
        assert trig["timezone"] == "Asia/Shanghai"
        assert trig["startTime"] == "1970-01-01 00:00:00"
        assert trig["endTime"] == "9999-01-01 00:00:00"


class TestOutputsAndDependency:
    def test_self_output(self):
        node = _build()["spec"]["nodes"][0]
        outs = node["outputs"]["nodeOutputs"]
        assert len(outs) == 1
        assert outs[0]["data"] == "dataworks.dwd_mkt_ad_group_hourly"
        assert outs[0]["refTableName"] == "dataworks.dwd_mkt_ad_group_hourly"
        assert outs[0]["isDefault"] is True

    def test_self_dependency_added(self):
        spec = _build()
        flow = spec["spec"]["flow"]
        assert flow[0]["nodeId"] == "dwd_mkt_ad_group_hourly"
        dep = flow[0]["depends"][0]
        assert dep["type"] == "CrossCycleDependsOnSelf"
        assert dep["output"] == "dataworks.dwd_mkt_ad_group_hourly"

    def test_self_dependency_disabled(self):
        spec = _build(self_dependency=False)
        assert "flow" not in spec["spec"]

    def test_node_id_used_for_update(self):
        spec = _build(node_id="32334642")
        node = spec["spec"]["nodes"][0]
        assert node["id"] == "32334642"
        assert spec["spec"]["flow"][0]["nodeId"] == "32334642"


class TestNodeStrategy:
    def test_defaults(self):
        node = _build()["spec"]["nodes"][0]
        assert node["recurrence"] == "Normal"
        assert node["instanceMode"] == "Immediately"
        assert node["rerunMode"] == "Allowed"
        assert node["autoParse"] is True
