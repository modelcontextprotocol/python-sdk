"""`docs/advanced/extensions.md`: every claim the page makes, proved against the real SDK."""

import logging

import pytest
from inline_snapshot import snapshot
from mcp_types import METHOD_NOT_FOUND, MISSING_REQUIRED_CLIENT_CAPABILITY, TextContent

from docs_src.extensions import (
    tutorial001,
    tutorial002,
    tutorial003,
    tutorial004,
    tutorial004_client,
    tutorial005,
    tutorial006,
    tutorial006_client,
    tutorial007,
    tutorial007_client,
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
    """tutorial003: `settings()` becomes the entry at `capabilities.extensions[identifier]`,
    which is the first line tutorial003_client prints."""
    async with Client(tutorial003.mcp) as client:
        assert client.server_capabilities.extensions == {"com.example/stamps": {"sealed": True}}


async def test_contributed_tool_is_listed_and_callable() -> None:
    """tutorial003: a `ToolBinding` registers like any `add_tool` call: listed and callable,
    with the content tutorial003_client prints."""
    async with Client(tutorial003.mcp) as client:
        listed = await client.list_tools()
        assert [tool.name for tool in listed.tools] == ["stamp"]
        result = await client.call_tool("stamp", {"text": "hello"})
    assert result.content == [TextContent(type="text", text="[stamped] hello")]


async def test_declaring_client_gets_the_vendor_method_result() -> None:
    """tutorial004_client's request against tutorial004's server, driven in-process: a client
    that advertises the extension gets the vendor method's typed result, and the client's
    own copy of the wire types agrees with the server's."""
    async with Client(tutorial004.mcp, extensions=[advertise(tutorial004_client.EXTENSION_ID)]) as client:
        request = tutorial004_client.SearchRequest(params=tutorial004_client.SearchParams(query="mcp", limit=3))
        result = await client.session.send_request(request, tutorial004_client.SearchResult)
    assert result.items == ["mcp-0", "mcp-1", "mcp-2"]


async def test_vendor_method_rejects_a_non_declaring_client_with_32021() -> None:
    """tutorial004: `require_client_extension` answers a non-declaring client with `-32021`
    and the machine-readable `requiredCapabilities` payload."""
    async with Client(tutorial004.mcp) as client:
        request = tutorial004_client.SearchRequest(params=tutorial004_client.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request, tutorial004_client.SearchResult)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == {"requiredCapabilities": {"extensions": {"com.example/search": {}}}}


async def test_version_pinned_method_is_not_found_on_a_legacy_connection() -> None:
    """tutorial004: `protocol_versions={"2026-07-28"}` makes the method METHOD_NOT_FOUND
    at any other wire version; for a legacy client it doesn't exist."""
    async with Client(
        tutorial004.mcp, mode="legacy", extensions=[advertise(tutorial004_client.EXTENSION_ID)]
    ) as client:
        request = tutorial004_client.SearchRequest(params=tutorial004_client.SearchParams(query="mcp"))
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request, tutorial004_client.SearchResult)
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


async def test_declaring_client_receives_the_redeemed_result_not_the_claimed_shape() -> None:
    """tutorial006_client's `Receipts` against tutorial006's server, driven in-process:
    `call_tool("buy")` returns what the resolver redeemed, never the claimed receipt shape."""
    async with Client(tutorial006.mcp, extensions=[tutorial006_client.Receipts()]) as client:
        result = await client.call_tool("buy", {"item": "lamp"})
    assert result.content == [TextContent(type="text", text="goods for r-117")]


async def test_a_client_without_the_extension_is_refused_by_the_gate() -> None:
    """The page's off-by-default claim: the server's capability gate refuses a non-declaring client."""
    async with Client(tutorial006.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("buy", {"item": "lamp"})
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY


async def test_session_tier_allow_claimed_returns_the_raw_shape() -> None:
    """The page's escape hatch: `allow_claimed=True` returns the parsed claim model, not the resolved result."""
    async with Client(tutorial006.mcp, extensions=[tutorial006_client.Receipts()]) as client:
        result = await client.session.call_tool("buy", {"item": "lamp"}, allow_claimed=True)
    assert isinstance(result, tutorial006_client.ReceiptResult)
    assert result.receipt_token == "r-117"


async def test_name_param_request_round_trips_with_no_client_registration() -> None:
    """tutorial007_client's `JobStatusRequest` against tutorial007's server, driven in-process:
    a vendor request declaring `name_param` round-trips `send_request` with no client-side
    registration."""
    async with Client(tutorial007.mcp, extensions=[advertise(tutorial007_client.EXTENSION_ID)]) as client:
        request = tutorial007_client.JobStatusRequest(params=tutorial007_client.JobParams(job_id="job-7"))
        result = await client.session.send_request(request, tutorial007_client.JobStatus)
    assert result.status == "job-7 is running"
