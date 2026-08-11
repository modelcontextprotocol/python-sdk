"""`ClientSession.register_tool_schema` for tools absent from `list_tools`."""

import logging

import pytest
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    Tool,
)

from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext

_SCORE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"score": {"type": "integer"}},
    "required": ["score"],
}
_SCORE_AS_STRING_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"score": {"type": "string"}},
    "required": ["score"],
}


def _dynamic_tool_server(*, structured_content: dict[str, object]) -> Server:
    """`list_tools` advertises only a search meta-tool; `analyze` is callable but unlisted."""

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="search", input_schema={"type": "object"})])

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "analyze"
        return CallToolResult(content=[], structured_content=structured_content)

    return Server("test-server", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


@pytest.mark.anyio
async def test_register_tool_schema_lets_call_tool_validate_an_unlisted_tool() -> None:
    """SDK-defined: a schema registered for a tool absent from list_tools is used by call_tool."""
    server = _dynamic_tool_server(structured_content={"score": 1})
    async with Client(server) as client:
        client.register_tool_schema("analyze", _SCORE_SCHEMA)
        result = await client.call_tool("analyze", {})
        assert result.structured_content == {"score": 1}


@pytest.mark.anyio
async def test_register_tool_schema_makes_call_tool_reject_nonconforming_structured_content() -> None:
    """Without registration, an unlisted tool skips validation; with it, mismatches raise."""
    server = _dynamic_tool_server(structured_content={"score": "no"})
    async with Client(server) as client:
        # Unregistered: validation is skipped (tool never appears in list_tools).
        skipped = await client.call_tool("analyze", {})
        assert skipped.structured_content == {"score": "no"}

        client.register_tool_schema("analyze", _SCORE_SCHEMA)
        # Stable SDK prefix only: the message tail is jsonschema text that shifts with the dependency.
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool analyze"):
            await client.call_tool("analyze", {})


@pytest.mark.anyio
async def test_register_tool_schema_with_none_suppresses_the_unlisted_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: registering None marks the tool known without validating structuredContent."""
    server = _dynamic_tool_server(structured_content={"anything": True})
    async with Client(server) as client:
        client.register_tool_schema("analyze", None)
        with caplog.at_level(logging.WARNING, logger="client"):
            result = await client.call_tool("analyze", {})
        assert result.structured_content == {"anything": True}
        assert "not listed by server" not in caplog.text


@pytest.mark.anyio
async def test_register_tool_schema_evicts_the_compiled_validator_when_the_schema_changes() -> None:
    """SDK-defined: a changed registration must not reuse a validator compiled for the old schema."""
    server = _dynamic_tool_server(structured_content={"score": 1})
    async with Client(server) as client:
        client.register_tool_schema("analyze", _SCORE_SCHEMA)
        await client.session.validate_tool_result(
            "analyze", CallToolResult(content=[], structured_content={"score": 1})
        )
        compiled = client.session._tool_output_validators["analyze"]

        client.register_tool_schema("analyze", _SCORE_AS_STRING_SCHEMA)
        assert "analyze" not in client.session._tool_output_validators

        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool analyze"):
            await client.session.validate_tool_result(
                "analyze", CallToolResult(content=[], structured_content={"score": 1})
            )
        assert client.session._tool_output_validators["analyze"] is not compiled


@pytest.mark.anyio
async def test_register_tool_schema_keeps_the_validator_when_the_schema_is_unchanged() -> None:
    """SDK-defined: re-registering an equal schema keeps the compiled validator."""
    server = _dynamic_tool_server(structured_content={"score": 1})
    async with Client(server) as client:
        client.register_tool_schema("analyze", _SCORE_SCHEMA)
        result = CallToolResult(content=[], structured_content={"score": 1})
        await client.session.validate_tool_result("analyze", result)
        compiled = client.session._tool_output_validators["analyze"]

        client.register_tool_schema("analyze", dict(_SCORE_SCHEMA))
        await client.session.validate_tool_result("analyze", result)
        assert client.session._tool_output_validators["analyze"] is compiled


@pytest.mark.anyio
async def test_a_complete_list_tools_prunes_a_manually_registered_schema() -> None:
    """SDK-defined: a complete listing is still the full tool universe for prune — a registered
    tool omitted from that listing is dropped, same as listing-absorbed schemas."""
    server = _dynamic_tool_server(structured_content={"score": 1})
    async with Client(server) as client:
        client.register_tool_schema("analyze", _SCORE_SCHEMA)
        assert "analyze" in client.session._tool_output_schemas

        await client.session.list_tools()
        assert "analyze" not in client.session._tool_output_schemas
        assert set(client.session._tool_output_schemas) == {"search"}


@pytest.mark.anyio
async def test_list_tools_that_includes_a_registered_name_replaces_the_registered_schema() -> None:
    """SDK-defined: when the same name later appears in a listing, the listed schema wins."""

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name="analyze", input_schema={"type": "object"}, output_schema=_SCORE_AS_STRING_SCHEMA),
            ]
        )

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        raise NotImplementedError

    server = Server("test-server", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
    async with Client(server) as client:
        client.register_tool_schema("analyze", _SCORE_SCHEMA)
        await client.session.validate_tool_result(
            "analyze", CallToolResult(content=[], structured_content={"score": 1})
        )

        await client.session.list_tools()
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool analyze"):
            await client.session.validate_tool_result(
                "analyze", CallToolResult(content=[], structured_content={"score": 1})
            )
