"""Client-side rejection of tools whose ``x-mcp-header`` annotation violates the 2026-07-28 spec.

The SDK gates the check on the negotiated version rather than the transport (a deliberate
superset of the spec's Streamable-HTTP scoping), so both 2026 matrix cells pin the eviction.
"""

import logging

import pytest
from inline_snapshot import snapshot
from mcp_types import ListToolsResult, PaginatedRequestParams, Tool

from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _listing_server(*tools: Tool) -> Server:
    """A server whose only job is to list the given tools."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=list(tools))

    return Server("x-mcp-header", on_list_tools=list_tools)


# Carries a valid annotation (not a plain schema) so survival proves the validator passes valid
# annotations; every test lists the broken tool first, so a client aborting the whole listing fails.
_VALID_TOOL = Tool(
    name="ok",
    input_schema={"type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "Region"}}},
)


@requirement("client:x-mcp-header:invalid-definition-rejected:empty")
@requirement("client:x-mcp-header:invalid-definition-rejected")
async def test_tool_with_empty_x_mcp_header_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool with an empty x-mcp-header is excluded from tools/list while the valid sibling survives.

    Same SDK token check as the non-tchar case below, but the spec states the two MUSTs separately.
    """
    broken = Tool(
        name="broken",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": ""}}},
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:non-tchar")
async def test_tool_with_non_token_x_mcp_header_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool whose x-mcp-header is not an RFC 9110 token (``1*tchar``) is excluded from tools/list."""
    broken = Tool(
        name="broken",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}},
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:control-chars")
async def test_tool_with_crlf_in_x_mcp_header_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool whose x-mcp-header contains CR/LF is excluded from tools/list.

    The control-character MUST NOT is its own spec sentence; the input is the header-injection shape.
    """
    broken = Tool(
        name="broken",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "string", "x-mcp-header": "X-Region\r\nEvil: 1"}},
        },
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:duplicate")
async def test_tool_with_case_insensitively_duplicate_x_mcp_headers_is_excluded_from_list_tools(
    connect: Connect,
) -> None:
    """A tool with two x-mcp-header values equal only case-insensitively is excluded from tools/list.

    ``Region``/``region`` defeats a validator that compares duplicates as exact strings.
    """
    broken = Tool(
        name="broken",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "string", "x-mcp-header": "Region"},
                "b": {"type": "string", "x-mcp-header": "region"},
            },
        },
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:non-primitive")
async def test_tool_with_x_mcp_header_on_a_number_property_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool annotating a ``number`` property with x-mcp-header is excluded from tools/list.

    ``number`` is the one JSON primitive the spec forbids, defeating an "any JSON primitive" check.
    """
    broken = Tool(
        name="broken",
        input_schema={"type": "object", "properties": {"amount": {"type": "number", "x-mcp-header": "Amount"}}},
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:not-statically-reachable")
async def test_x_mcp_header_under_items_invalidates_the_tool_while_a_nested_properties_chain_stays_valid(
    connect: Connect,
) -> None:
    """An x-mcp-header under ``items`` invalidates its tool; one nested via ``properties`` keys stays valid.

    The nested sibling covers both arms of the spec sentence, so the flat ``_VALID_TOOL`` is unused.
    """
    via_items = Tool(
        name="via-items",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "array", "items": {"type": "string", "x-mcp-header": "Region"}}},
        },
    )
    nested_ok = Tool(
        name="nested-ok",
        input_schema={
            "type": "object",
            "properties": {
                "cfg": {"type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "Region"}}}
            },
        },
    )

    async with connect(_listing_server(via_items, nested_ok)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["nested-ok"]


@requirement("client:x-mcp-header:invalid-tool-excluded:logs-warning")
async def test_rejecting_an_invalid_tool_logs_a_warning_naming_the_tool_and_reason(
    connect: Connect, caplog: pytest.LogCaptureFixture
) -> None:
    """Rejecting a tool over an invalid x-mcp-header logs a warning naming the tool and the reason.

    A single deterministic SDK-authored record, so the whole message is snapshot-pinned.
    """
    broken = Tool(
        name="broken",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}},
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        with caplog.at_level(logging.WARNING, logger="client"):
            listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]
    records = [record for record in caplog.records if record.name == "client"]
    assert len(records) == 1
    assert records[0].getMessage() == snapshot(
        "dropping tool 'broken': invalid x-mcp-header (property 'a': x-mcp-header 'bad name' is not an RFC 9110 token)"
    )
