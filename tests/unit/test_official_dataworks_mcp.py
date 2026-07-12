from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.mcp.official_dataworks import OfficialDataWorksMCPClient


def test_server_parameters_keep_credentials_in_child_environment(monkeypatch):
    monkeypatch.setattr("dataworks_agent.mcp.official_dataworks.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "dataworks_agent.mcp.official_dataworks.settings.aliyun_access_key_id", "test-ak"
    )
    monkeypatch.setattr(
        "dataworks_agent.mcp.official_dataworks.settings.aliyun_access_key_secret", "test-sk"
    )
    client = OfficialDataWorksMCPClient()
    params = client._server_parameters()

    assert params.args[0] == "-y"
    assert "ACCESS_KEY" not in " ".join(params.args)
    assert params.env["ALIBABA_CLOUD_ACCESS_KEY_ID"]
    assert params.env["ALIBABA_CLOUD_ACCESS_KEY_SECRET"]
    assert "ListNodes" in params.env["TOOL_NAMES"]


@pytest.mark.asyncio
async def test_call_tool_parses_json_content():
    client = OfficialDataWorksMCPClient()
    client._status.tools = ["GetNode"]
    client._session = AsyncMock()
    client._session.call_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(text='{"Id":"n1"}')], isError=False
    )

    result = await client.call_tool("GetNode", {"Id": "n1"})

    assert result == {"Id": "n1"}
    client._session.call_tool.assert_awaited_once_with("GetNode", {"Id": "n1"})


@pytest.mark.asyncio
async def test_call_tool_rejects_non_allowlisted_tool():
    client = OfficialDataWorksMCPClient()
    client._status.tools = ["GetNode"]
    client._session = AsyncMock()

    with pytest.raises(ValueError):
        await client.call_tool("DeleteNode", {})
