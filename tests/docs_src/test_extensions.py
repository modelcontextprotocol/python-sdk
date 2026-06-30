"""`docs/advanced/extensions.md`: every claim the page makes, proved against the real SDK."""

import logging

import pytest
from inline_snapshot import snapshot
from mcp_types import METHOD_NOT_FOUND, MISSING_REQUIRED_CLIENT_CAPABILITY, TextContent
from pydantic import ValidationError

from docs_src.extensions import (
    tutorial001,
    tutorial002,
    tutorial003,
    tutorial004,
    tutorial005,
    tutorial006,
    tutorial007,
)
from mcp import Client, MCPError
from mcp.client import advertise
from mcp.server.extension import Extension

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_using_an_extension_advertises_its_capability() -> None:
    """tutorial001: `extensions=[Apps()]` is all it takes for the server to advertise
    the extension under `capabilities.extensions`."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/ui": {}}


def test_a_prefixless_identifier_fails_at_class_definition() -> None:
    """tutorial002 + the page's TypeError block: the identifier is validated when the
    subclass is defined, with the exact message the page shows."""
    assert tutorial002.Stamps.identifier == "com.example/stamps"
    with pytest.raises(TypeError) as exc_info:
        type("Stamps", (Extension,), {"identifier": "stamps"})
    assert str(exc_info.value) == snapshot(
        "Stamps.identifier must be a `vendor-prefix/name` string (reverse-DNS prefix required), got 'stamps'"
    )


async def test_extension_settings_advertised_under_capabilities() -> None:
    """tutorial003: `settings()` becomes the entry at `capabilities.extensions[identifier]`."""
    async with Client(tutorial003.mcp) as client:
        assert client.server_capabilities.extensions == {"com.example/stamps": {"sealed": True}}


async def test_contributed_tool_is_listed_and_callable() -> None:
    """tutorial003: a `ToolBinding` registers like any `add_tool` call: listed and callable."""
    async with Client(tutorial003.mcp) as client:
        listed = await client.list_tools()
        assert [tool.name for tool in listed.tools] == ["stamp"]
        result = await client.call_tool("stamp", {"text": "hello"})
    assert result.content == [TextContent(type="text", text="[stamped] hello")]


async def test_the_stamps_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial003: `main()` is the literal client program on the page; both printed
    lines match the page's comments."""
    await tutorial003.main()
    out = capsys.readouterr().out
    assert "{'com.example/stamps': {'sealed': True}}" in out
    assert "[stamped] hello" in out


async def test_the_search_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial004: `main()` declares the extension and gets the vendor method's result."""
    await tutorial004.main()
    assert "['mcp-0', 'mcp-1', 'mcp-2']" in capsys.readouterr().out


async def test_vendor_method_rejects_a_non_declaring_client_with_32021() -> None:
    """tutorial004: `require_client_extension` answers a non-declaring client with `-32021`
    and the machine-readable `requiredCapabilities` payload."""
    async with Client(tutorial004.mcp) as client:
        request = tutorial004.SearchRequest(params=tutorial004.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request, tutorial004.SearchResult)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == {"requiredCapabilities": {"extensions": {"com.example/search": {}}}}


async def test_version_pinned_method_is_not_found_on_a_legacy_connection() -> None:
    """tutorial004: `protocol_versions={"2026-07-28"}` makes the method METHOD_NOT_FOUND
    at any other wire version; for a legacy client it doesn't exist."""
    async with Client(tutorial004.mcp, mode="legacy", extensions=[advertise(tutorial004.EXTENSION_ID)]) as client:
        request = tutorial004.SearchRequest(params=tutorial004.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request, tutorial004.SearchResult)
    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_interceptor_observes_the_call_and_passes_the_result_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """tutorial005: the interceptor logs the tool name and returns `call_next`'s result unchanged."""
    with caplog.at_level(logging.INFO, logger=tutorial005.logger.name):
        async with Client(tutorial005.mcp) as client:
            result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"result": 5}
    messages = [record.getMessage() for record in caplog.records if record.name == tutorial005.logger.name]
    assert messages == ["tool 'add' called"]


async def test_the_receipts_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial006: `main()` runs as printed and the output is the redeemed result, never the claimed shape."""
    await tutorial006.main()
    assert "goods for r-117" in capsys.readouterr().out


async def test_a_claimed_shape_fails_validation_without_the_extension() -> None:
    """The page's off-by-default claim: a client without `Receipts` rejects the `receipt` shape as invalid."""
    async with Client(tutorial006.mcp) as client:
        with pytest.raises(ValidationError):
            await client.call_tool("buy", {"item": "lamp"})


async def test_session_tier_allow_claimed_returns_the_raw_shape() -> None:
    """The page's escape hatch: `allow_claimed=True` returns the parsed claim model, not the resolved result."""
    async with Client(tutorial006.mcp, extensions=[tutorial006.Receipts()]) as client:
        result = await client.session.call_tool("buy", {"item": "lamp"}, allow_claimed=True)
    assert isinstance(result, tutorial006.ReceiptResult)
    assert result.receipt_token == "r-117"


async def test_the_jobs_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial007: a vendor request with `name_param` round-trips `send_request` with no registration."""
    await tutorial007.main()
    assert "job-7 is running" in capsys.readouterr().out
