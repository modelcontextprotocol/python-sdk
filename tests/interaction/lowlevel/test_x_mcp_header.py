"""The 2026-07-28 ``x-mcp-header`` schema-extension constraints, enforced client-side.

A tool definition whose ``x-mcp-header`` annotation violates the spec's constraints is rejected by
the modern client: the tool is excluded from the tools/list result while valid sibling tools
survive, so a single malformed definition never takes down the rest of the listing. The spec
scopes the rejection MUST to clients using the Streamable HTTP transport (other transports MAY
ignore the annotations); the SDK gates on the negotiated modern version instead, so the eviction
also runs on the in-memory 2026 connection -- a deliberate superset these fixture-driven tests pin
on both 2026 matrix cells.
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


# A valid-annotated sibling, not a plain schema: its survival proves the validator passes valid
# annotations rather than evicting everything that mentions x-mcp-header. Every test lists the
# broken tool FIRST, so the eviction assertion also proves the spec's stated rationale -- "a single
# malformed tool definition does not prevent other valid tools from being used"; a client that
# aborted the listing at the first invalid tool would fail.
_VALID_TOOL = Tool(
    name="ok",
    input_schema={"type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "Region"}}},
)


@requirement("client:x-mcp-header:invalid-definition-rejected:empty")
@requirement("client:x-mcp-header:invalid-definition-rejected")
async def test_tool_with_empty_x_mcp_header_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool whose x-mcp-header annotation is the empty string is excluded from the tools/list
    result while the valid sibling survives (spec MUST: the value MUST NOT be empty; rejection
    means exclusion from the tools/list result).

    The SDK funnels the empty string through the same RFC 9110 token check as the non-tchar case
    below, but the spec states the two MUSTs separately, so each keeps its own test and input.
    """
    broken = Tool(
        name="broken",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": ""}}},
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    # Membership is the property: list equality, not a full-result snapshot, so this test does not
    # re-pin tools-result semantics (caching fields, schema echo) owned by other entries.
    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:non-tchar")
async def test_tool_with_non_token_x_mcp_header_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool whose x-mcp-header annotation is not an RFC 9110 field-name token is excluded from
    the tools/list result while the valid sibling survives (spec MUST: the value MUST match
    ``1*tchar``, RFC 9110 section 5.1) -- a space is not a tchar.
    """
    broken = Tool(
        name="broken",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}},
    )

    async with connect(_listing_server(broken, _VALID_TOOL)) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["ok"]


@requirement("client:x-mcp-header:invalid-definition-rejected:control-chars")
async def test_tool_with_crlf_in_x_mcp_header_is_excluded_from_list_tools(connect: Connect) -> None:
    """A tool whose x-mcp-header annotation contains CR/LF is excluded from the tools/list result
    while the valid sibling survives (spec MUST NOT contain control characters, naming CR and LF
    -- the header-injection shape).

    The SDK enforces this through the single RFC 9110 token regex (control characters are not
    tchars); the test pins the spec observable -- exclusion -- not the code path.
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
    """A tool whose inputSchema carries two x-mcp-header values equal only under case-insensitive
    comparison is excluded from the tools/list result while the valid sibling survives (spec MUST:
    values are case-insensitively unique among all x-mcp-header values in the inputSchema).

    ``Region``/``region`` differ as exact strings, so a validator doing an exact-string duplicate
    check would keep the tool and fail this test. Which of the two properties the rejection names
    is walk-order implementation detail, deliberately not asserted.
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
    """A tool annotating a ``number``-typed property with x-mcp-header is excluded from the
    tools/list result while the valid sibling survives (spec MUST: the annotation is only
    permitted on integer/string/boolean properties; ``number`` is the one JSON-Schema primitive
    the spec forbids by name, so a validator merely checking "is a JSON primitive" would fail here).

    The ``object``/``array``/missing-``type`` variants take the same code arm and are deliberately
    not swept here -- one input per entry, and the entry's spec sentence names ``number``.
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
    """An x-mcp-header annotation reachable only through ``items`` invalidates its tool, while a
    sibling annotated at the end of a nested pure-``properties`` chain stays listed (spec MUST:
    the annotation applies only to properties statically reachable from the schema root via a
    chain consisting solely of ``properties`` keys; nested object properties are explicitly
    permitted).

    The valid sibling here is the nested one, doing double duty for both arms of the spec
    sentence (the flat ``_VALID_TOOL`` is not used); ``items`` is the spec's first-named
    forbidden keyword and stands for the rest -- the per-applicator sweep is unit-test
    territory, not interaction.
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
    """Rejecting a tool definition over an invalid x-mcp-header logs a warning naming the tool
    and the reason for rejection (a spec SHOULD, not MUST). The eviction itself is co-asserted
    so the log claim is not proven in a vacuum.

    The warning is a single deterministic record of fully SDK-authored text, so the whole
    message is snapshot-pinned -- unlike the multi-record registration warning in
    ``mcpserver/test_tools.py``, where only a stable prefix is asserted.
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
