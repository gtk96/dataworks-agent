from unittest.mock import AsyncMock

import pytest

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.api_clients.provider_errors import ProviderAuthenticationError


@pytest.mark.asyncio
async def test_search_tables_raises_auth_error_for_http_200_business_403001() -> None:
    client = DataWorksClient()
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"code": 403001, "reason": "USER_NOT_LOGGED_IN"}
    )

    with pytest.raises(ProviderAuthenticationError) as caught:
        await client.search_tables("订单")

    assert caught.value.code == "cookie_auth_required"
    assert caught.value.reason == "USER_NOT_LOGGED_IN"


@pytest.mark.asyncio
async def test_empty_decrypted_cookie_stops_before_http(monkeypatch) -> None:
    client = DataWorksClient()
    http = AsyncMock()
    monkeypatch.setattr(client, "_client", lambda: http)
    monkeypatch.setattr("dataworks_agent.api_clients.bff_client.decrypt_cookie", lambda: "")

    with pytest.raises(ProviderAuthenticationError) as caught:
        await client._get("dma/searchTables", {"keyword": "订单"})

    assert caught.value.code == "cookie_decrypt_failed"
    http.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticated_empty_search_result_remains_a_valid_empty_list() -> None:
    client = DataWorksClient()
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"code": 200, "data": {"data": []}}
    )

    assert await client.search_tables("不存在的表") == []
