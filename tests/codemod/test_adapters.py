"""The generated lowlevel adapters, pinned against the installed v2 at runtime.

Real v1 registration code is migrated and served to a v1-shaped `ClientSession`,
so every template is proven against the installed package, not expectations.
"""

import textwrap
from typing import Any, cast

import anyio
import mcp_types
import pytest
from mcp_codemod import transform
from mcp_codemod._adapters import ADAPTER_IMPORTS, LOWLEVEL_HANDLER_SPECS, build_adapter

from mcp import ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_client_server_memory_streams

KITCHEN_SINK_V1 = textwrap.dedent("""\
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from pydantic import AnyUrl

    app = Server("kitchen-sink")
    SUBSCRIBED: list[str] = []


    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="add",
                description="Add two numbers",
                inputSchema={
                    "type": "object",
                    "required": ["a", "b"],
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                },
            )
        ]


    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name != "add":
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=str(arguments["a"] + arguments["b"]))]


    @app.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [types.Resource(uri=AnyUrl("demo://greeting"), name="greeting", mimeType="text/plain")]


    @app.read_resource()
    async def read_resource(uri: AnyUrl) -> str:
        return f"resource at {uri}"


    @app.subscribe_resource()
    async def subscribe(uri: AnyUrl) -> None:
        SUBSCRIBED.append(str(uri))


    @app.get_prompt()
    async def get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(role="user", content=types.TextContent(type="text", text=f"prompt {name}"))
            ]
        )
""")


def _load_migrated(source: str) -> dict[str, Any]:
    result = transform(source)
    assert result.code.count("# mcp-codemod:") == 0, result.code
    namespace: dict[str, Any] = {"__name__": "migrated"}
    exec(compile(result.code, "migrated.py", "exec"), namespace)
    return namespace


@pytest.mark.anyio
async def test_a_migrated_kitchen_sink_server_serves_a_v1_client_over_the_legacy_protocol() -> None:
    """Unknown tools and schema-invalid arguments come back as `is_error` results, not protocol errors."""
    namespace = _load_migrated(KITCHEN_SINK_V1)
    app = cast(Server[Any], namespace["app"])
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as task_group:

            async def serve() -> None:
                await app.run(server_streams[0], server_streams[1], app.create_initialization_options())

            task_group.start_soon(serve)
            async with ClientSession(client_streams[0], client_streams[1]) as session:
                with anyio.fail_after(5):
                    init = await session.initialize()
                    assert init.protocol_version == "2025-11-25"
                    tools = await session.list_tools()
                    assert [tool.name for tool in tools.tools] == ["add"]
                    ok = await session.call_tool("add", {"a": 2, "b": 3})
                    assert not ok.is_error
                    assert cast(mcp_types.TextContent, ok.content[0]).text == "5"
                    unknown = await session.call_tool("nope", {})
                    assert unknown.is_error
                    assert "Unknown tool: nope" in cast(mcp_types.TextContent, unknown.content[0]).text
                    invalid = await session.call_tool("add", {"a": 1})
                    assert invalid.is_error
                    assert "Input validation error" in cast(mcp_types.TextContent, invalid.content[0]).text
                    resources = await session.list_resources()
                    assert resources.resources[0].name == "greeting"
                    read = await session.read_resource("demo://greeting")
                    assert cast(mcp_types.TextResourceContents, read.contents[0]).text == "resource at demo://greeting"
                    await session.subscribe_resource("demo://greeting")
                    assert namespace["SUBSCRIBED"] == ["demo://greeting"]
                    prompt = await session.get_prompt("hello", None)
                    content = cast(mcp_types.TextContent, prompt.messages[0].content)
                    assert content.text == "prompt hello"
            task_group.cancel_scope.cancel()


def test_the_migration_is_idempotent_on_its_own_output() -> None:
    once = transform(KITCHEN_SINK_V1).code
    assert transform(once).code == once


def test_every_template_renders_to_parseable_python() -> None:
    import ast

    for kind in LOWLEVEL_HANDLER_SPECS:
        ast.parse(build_adapter(kind, "user_fn", "srv"))
        ast.parse(build_adapter(kind, "user_fn", "srv", validate_input=False))


def test_no_template_emits_a_2026_era_surface() -> None:
    """The codemod's goal forbids routing users onto 2026-era features."""
    for kind in LOWLEVEL_HANDLER_SPECS:
        block = build_adapter(kind, "user_fn", "srv")
        for forbidden in ("InputRequiredResult", "subscriptions/listen", "cache_hints", "extensions", "Resolve"):
            assert forbidden not in block, (kind, forbidden)


def test_every_adapter_import_statement_resolves_on_the_installed_v2() -> None:
    for statement in ADAPTER_IMPORTS.values():
        exec(statement, {})


def test_every_spec_params_model_exists_in_mcp_types() -> None:
    """The registration passes `mcp_types.<Model>` by name; the name must exist."""
    for kind in LOWLEVEL_HANDLER_SPECS:
        rendered = build_adapter(kind, "user_fn", "srv")
        registration = [
            line
            for line in rendered.splitlines()
            if "add_request_handler" in line or "add_notification_handler" in line
        ]
        assert len(registration) == 1, kind
        model = registration[0].split("mcp_types.")[1].split(",")[0]
        assert hasattr(mcp_types, model), (kind, model)


def test_every_spec_method_registers_on_the_installed_server() -> None:
    """Pins the emitted method strings and registration calls against the installed `Server`."""
    server: Server[Any] = Server("ratchet")

    async def handler(ctx: object, params: object) -> None:
        return None

    anyio.run(handler, None, None)
    for kind in LOWLEVEL_HANDLER_SPECS:
        rendered = build_adapter(kind, "user_fn", "srv")
        line = next(line for line in rendered.splitlines() if ".add_" in line)
        method = line.split('"')[1]
        if "add_notification_handler" in line:
            server.add_notification_handler(method, cast("type[Any]", object), cast(Any, handler))
        else:
            server.add_request_handler(method, cast("type[Any]", object), cast(Any, handler))
