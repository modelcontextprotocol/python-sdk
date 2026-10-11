"""Compiled tool validators are built once per listing and reused (issue #3676).

One-shot `jsonschema.validate` re-selects the validator class, checks the
schema against the meta-schema, and resolves `$ref`s on every `tools/call`.
The server now compiles per-tool validators once and reuses them, mirroring
the client-side fix from #3134.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

import mcp.server.lowlevel.server as lowlevel_server
from mcp.server import Server
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, ListToolsRequest, TextContent, Tool


def make_tool(extra_required: bool = False) -> Tool:
    required = ["name"] + (["nickname"] if extra_required else [])
    return Tool(
        name="greet",
        description="Greet someone",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "nickname": {"type": "string"},
            },
            "required": required,
            "additionalProperties": False,
        },
        outputSchema={
            "type": "object",
            "properties": {"greeting": {"type": "string"}},
            "required": ["greeting"],
            "additionalProperties": False,
        },
    )


def make_server(
    tools: Callable[[], list[Tool]],
    handler: Callable[[str, dict[str, Any]], Awaitable[Any]],
) -> Server:
    server = Server("test")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        return await handler(name, arguments)

    return server


def call_request(name: str, arguments: dict[str, Any]) -> CallToolRequest:
    return CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )


async def greet_handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    assert name == "greet"
    return {"greeting": f"Hello, {arguments['name']}!"}


async def call(server: Server, arguments: dict[str, Any]) -> CallToolResult:
    handler = server.request_handlers[CallToolRequest]
    result = await handler(call_request("greet", arguments))
    assert result is not None
    assert isinstance(result.root, CallToolResult)
    return result.root


@pytest.mark.anyio
async def test_validators_compiled_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    """N calls compile exactly one input and one output validator."""
    calls = 0
    real_validator_for = lowlevel_server.validator_for

    def counting_validator_for(schema: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_validator_for(schema, *args, **kwargs)

    monkeypatch.setattr(lowlevel_server, "validator_for", counting_validator_for)

    server = make_server(lambda: [make_tool()], greet_handler)
    for _ in range(3):
        res = await call(server, {"name": "Ada"})
        assert not res.isError
    assert calls == 2  # one input-schema compile + one output-schema compile


@pytest.mark.anyio
async def test_invalid_input_message_preserved() -> None:
    """Same error contract as one-shot validation: isError + prefix."""
    server = make_server(lambda: [make_tool()], greet_handler)
    res = await call(server, {})
    assert res.isError
    first = res.content[0]
    assert isinstance(first, TextContent)
    assert first.text.startswith("Input validation error: ")
    assert "'name' is a required property" in first.text


@pytest.mark.anyio
async def test_invalid_output_message_preserved() -> None:
    """Structured output violating outputSchema keeps the error contract."""

    async def bad_handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"wrong": "shape"}

    server = make_server(lambda: [make_tool()], bad_handler)
    res = await call(server, {"name": "Ada"})
    assert res.isError
    first = res.content[0]
    assert isinstance(first, TextContent)
    assert first.text.startswith("Output validation error: ")


@pytest.mark.anyio
async def test_relisted_schema_is_recompiled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A re-listed tool object triggers exactly one recompile and new rules apply."""
    calls = 0
    real_validator_for = lowlevel_server.validator_for

    def counting_validator_for(schema: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_validator_for(schema, *args, **kwargs)

    monkeypatch.setattr(lowlevel_server, "validator_for", counting_validator_for)

    current = {"tool": make_tool()}
    server = make_server(lambda: [current["tool"]], greet_handler)

    res = await call(server, {"name": "Ada"})
    assert not res.isError
    assert calls == 2

    # Re-list with a stricter schema: refreshed tool objects must recompile.
    # The failing call recompiles only the input validator (lazy output
    # compile is skipped on the error path).
    current["tool"] = make_tool(extra_required=True)
    await server.request_handlers[ListToolsRequest](None)
    res = await call(server, {"name": "Ada"})
    assert res.isError
    first = res.content[0]
    assert isinstance(first, TextContent)
    assert "'nickname' is a required property" in first.text
    assert calls == 3

    # A valid call under the new schema compiles the output validator too.
    res = await call(server, {"name": "Ada", "nickname": "A"})
    assert not res.isError
    assert calls == 4


@pytest.mark.anyio
async def test_validate_input_false_skips_input_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate_input=False keeps skipping input validation entirely."""
    calls = 0
    real_validator_for = lowlevel_server.validator_for

    def counting_validator_for(schema: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_validator_for(schema, *args, **kwargs)

    monkeypatch.setattr(lowlevel_server, "validator_for", counting_validator_for)

    server = Server("test")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [make_tool()]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        assert name == "greet"
        return {"greeting": "Hello!"}

    # Invalid input passes through; only the output schema compiles.
    res = await call(server, {})
    assert not res.isError
    assert calls == 1
