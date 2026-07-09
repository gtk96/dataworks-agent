"""get_lineage_provider 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from dataworks_agent.governance.lineage_provider import OpenAPILineageProvider, get_lineage_provider


class TestGetLineageProvider:
    def test_prefers_bff(self):
        bff = MagicMock()
        openapi = MagicMock()
        with patch("dataworks_agent.state.app_state") as st:
            st._bff_client = bff
            st._openapi_client = openapi
            assert get_lineage_provider() is bff

    def test_openapi_when_no_bff(self):
        openapi = MagicMock()
        with patch("dataworks_agent.state.app_state") as st:
            st._bff_client = None
            st._openapi_client = openapi
            provider = get_lineage_provider(mc_project="dataworks")
            assert isinstance(provider, OpenAPILineageProvider)

    def test_raises_when_none(self):
        with patch("dataworks_agent.state.app_state") as st:
            st._bff_client = None
            st._openapi_client = None
            with pytest.raises(HTTPException) as exc:
                get_lineage_provider()
            assert exc.value.status_code == 503
