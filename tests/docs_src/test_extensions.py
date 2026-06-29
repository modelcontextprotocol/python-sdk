"""`docs/advanced/extensions.md`: every claim the page makes, proved against the real SDK."""

import logging
from typing import cast

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import METHOD_NOT_FOUND, MISSING_REQUIRED_CLIENT_CAPABILITY, TextContent

from docs_src.extensions import tutorial001, tutorial002, tutorial003, tutorial004, tutorial005
from mcp import Client, MCPError
from mcp.server.extension import Extension

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_using_an_extension_advertises_its_capability() -> None:
    async with Client(tutorial001.mcp) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/ui": {}}


def test_a_prefixless_identifier_fails_at_class_definition() -> None:
    assert tutorial002.Stamps.identifier == "com.example/stamps"
    with pytest.raises(TypeError) as exc_info:
        type("Stamps", (Extension,), {"identifier": "stamps"})
    assert str(exc_info.value) == snapshot(
        "Stamps.identifier must be a `vendor-prefix/name` string (reverse-DNS prefix required), got 'stamps'"
    )


async def test_extension_settings_advertised_under_capabilities() -> None:
    async with Client(tutorial003.mcp) as client:
        assert client.server_capabilities.extensions == {"com.example/stamps": {"sealed": True}}


async def test_contributed_tool_is_listed_and_callable() -> None:
    async with Client(tutorial003.mcp) as client:
        listed = await client.list_tools()
        assert [tool.name for tool in listed.tools] == ["stamp"]
        result = await client.call_tool("stamp", {"text": "hello"})
    assert result.content == [TextContent(type="text", text="[stamped] hello")]


async def test_the_stamps_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    await tutorial003.main()
    out = capsys.readouterr().out
    assert "{'com.example/stamps': {'sealed': True}}" in out
    assert "[stamped] hello" in out


async def test_the_search_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    await tutorial004.main()
    assert "['mcp-0', 'mcp-1', 'mcp-2']" in capsys.readouterr().out


async def test_vendor_method_rejects_a_non_declaring_client_with_32021() -> None:
    async with Client(tutorial004.mcp) as client:
        request = tutorial004.SearchRequest(params=tutorial004.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(cast("types.ClientRequest", request), tutorial004.SearchResult)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == {"requiredCapabilities": {"extensions": {"com.example/search": {}}}}


async def test_version_pinned_method_is_not_found_on_a_legacy_connection() -> None:
    """tutorial004 pins the method to `protocol_versions={"2026-07-28"}`; on a legacy connection it doesn't exist."""
    async with Client(tutorial004.mcp, mode="legacy", extensions={tutorial004.EXTENSION_ID: {}}) as client:
        request = tutorial004.SearchRequest(params=tutorial004.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(cast("types.ClientRequest", request), tutorial004.SearchResult)
    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_interceptor_observes_the_call_and_passes_the_result_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=tutorial005.logger.name):
        async with Client(tutorial005.mcp) as client:
            result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"result": 5}
    messages = [record.getMessage() for record in caplog.records if record.name == tutorial005.logger.name]
    assert messages == ["tool 'add' called"]
