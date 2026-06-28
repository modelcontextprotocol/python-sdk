"""`docs/advanced/extensions.md`: every claim the page makes, proved against the real SDK."""

import logging
from typing import Literal, cast

import mcp_types as types
import pytest
from mcp_types import METHOD_NOT_FOUND, MISSING_REQUIRED_CLIENT_CAPABILITY, TextContent

from docs_src.extensions import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


class _SearchRequest(types.Request[tutorial002.SearchParams, Literal["com.example/search"]]):
    method: Literal["com.example/search"] = "com.example/search"
    params: tutorial002.SearchParams


async def test_extension_settings_advertised_under_capabilities() -> None:
    """tutorial001: `settings()` becomes the entry at `capabilities.extensions[identifier]`."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_capabilities.extensions == {"com.example/stamps": {"sealed": True}}


async def test_contributed_tool_is_listed_and_callable() -> None:
    """tutorial001: a `ToolBinding` registers like any `add_tool` call: listed and callable."""
    async with Client(tutorial001.mcp) as client:
        listed = await client.list_tools()
        assert [tool.name for tool in listed.tools] == ["stamp"]
        result = await client.call_tool("stamp", {"text": "hello"})
    assert result.content == [TextContent(type="text", text="[stamped] hello")]


async def test_vendor_method_served_to_a_declaring_client() -> None:
    """tutorial002: a client that declared the extension gets the vendor method's result."""
    async with Client(tutorial002.mcp, extensions={tutorial002.EXTENSION_ID: {}}) as client:
        request = _SearchRequest(params=tutorial002.SearchParams(query="mcp", limit=3))
        result = await client.session.send_request(cast("types.ClientRequest", request), tutorial002.SearchResult)
    assert result.items == ["mcp-0", "mcp-1", "mcp-2"]


async def test_vendor_method_rejects_a_non_declaring_client_with_32021() -> None:
    """tutorial002: `require_client_extension` answers a non-declaring client with `-32021`
    and the machine-readable `requiredCapabilities` payload."""
    async with Client(tutorial002.mcp) as client:
        request = _SearchRequest(params=tutorial002.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(cast("types.ClientRequest", request), tutorial002.SearchResult)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == {"requiredCapabilities": {"extensions": {"com.example/search": {}}}}


async def test_version_pinned_method_is_not_found_on_a_legacy_connection() -> None:
    """tutorial002: `protocol_versions={"2026-07-28"}` makes the method METHOD_NOT_FOUND
    at any other wire version; for a legacy client it doesn't exist."""
    async with Client(tutorial002.mcp, mode="legacy", extensions={tutorial002.EXTENSION_ID: {}}) as client:
        request = _SearchRequest(params=tutorial002.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(cast("types.ClientRequest", request), tutorial002.SearchResult)
    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_interceptor_observes_the_call_and_passes_the_result_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """tutorial003: the interceptor logs the tool name and returns `call_next`'s result unchanged."""
    with caplog.at_level(logging.INFO, logger=tutorial003.logger.name):
        async with Client(tutorial003.mcp) as client:
            result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"result": 5}
    messages = [record.getMessage() for record in caplog.records if record.name == tutorial003.logger.name]
    assert messages == ["tool 'add' called"]
