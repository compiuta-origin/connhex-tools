from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from connhex.errors import InvalidResponseError
from connhex.schemas.iam import IdentitiesPage, Identity

from connhex_mcp.mcp_instance import mcp
from connhex_mcp.tools import identities


@pytest.mark.asyncio
async def test_tools_delegate_to_sdk(monkeypatch):
    page = IdentitiesPage(
        identities=[Identity(id="one")],
        limit=2,
        offset=3,
        has_more=False,
    )
    iam = SimpleNamespace(
        list_identities=AsyncMock(return_value=page),
        get_identity=AsyncMock(return_value=page.identities[0]),
    )
    monkeypatch.setattr(
        identities, "get_connhex", lambda: SimpleNamespace(iam=iam)
    )
    assert await identities.list_identities(2, 3, "a@test.com") is page
    iam.list_identities.assert_awaited_once_with(
        limit=2, offset=3, credentials_identifier="a@test.com"
    )
    assert await identities.get_identity("one") is page.identities[0]
    iam.get_identity.assert_awaited_once_with("one")
    iam.list_identities.side_effect = InvalidResponseError("Invalid response")
    with pytest.raises(InvalidResponseError):
        await identities.list_identities()


@pytest.mark.asyncio
async def test_registered_tools_schema():
    tools = {t.name: t for t in await mcp.list_tools()}
    for name in ("list_identities", "get_identity"):
        tool = tools[name]
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
        assert "credentials" not in str(tool.output_schema)
        assert "page_token" not in str(tool.parameters)
    params = tools["list_identities"].parameters["properties"]
    assert params["limit"]["exclusiveMinimum"] == 0
    assert params["offset"]["minimum"] == 0
