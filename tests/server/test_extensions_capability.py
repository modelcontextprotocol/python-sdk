"""SEP-2133 extensions capability advertisement and negotiation.

Covers only the extension-map plumbing, independent of any concrete extension;
per-extension contribution wiring lives in `test_extension.py`.
"""

import mcp_types as types
import pytest
from inline_snapshot import snapshot

from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio

_EXTENSION_ID = "com.example/x"
_OTHER_EXTENSION_ID = "com.example/other"


class _Extension(Extension):
    identifier = _EXTENSION_ID

    def settings(self) -> dict[str, object]:
        return {"k": 1}


def test_get_capabilities_omits_extensions_when_none_registered() -> None:
    server = Server("bare")
    assert server.get_capabilities().extensions is None


def test_get_capabilities_advertises_populated_self_extensions() -> None:
    server = Server("with-ext")
    settings = {"k": 1}
    server.extensions = {_EXTENSION_ID: settings}
    assert server.get_capabilities().extensions == {_EXTENSION_ID: settings}


async def test_modern_connection_carries_the_advertised_extensions_map() -> None:
    server = MCPServer("host", extensions=[_Extension()])
    async with Client(server, mode="auto") as client:
        assert client.server_capabilities.extensions == snapshot({"com.example/x": {"k": 1}})


async def test_legacy_handshake_drops_the_extensions_map() -> None:
    """Pinned gap: the 2025 wire schema's `initialize` result has no `extensions`
    field, so a legacy handshake drops the map and the client sees `None`."""
    server = MCPServer("host", extensions=[_Extension()])
    async with Client(server, mode="legacy") as client:
        assert client.server_capabilities.extensions is None


async def test_server_accepts_capability_for_client_advertised_extension() -> None:
    queried = types.ClientCapabilities(extensions={_EXTENSION_ID: {}})
    supported: list[bool] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "probe"
        supported.append(ctx.session.check_client_capability(queried))
        return types.CallToolResult(content=[])

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="probe", input_schema={"type": "object"})])

    server = Server("checker", on_call_tool=call_tool, on_list_tools=list_tools)
    async with Client(server, extensions={_EXTENSION_ID: {"mimeTypes": ["text/html"]}}) as client:
        await client.call_tool("probe", {})

    assert supported == [True]


async def test_server_rejects_capability_for_undeclared_extension() -> None:
    """Presence of the identifier, not its settings value, is what is checked."""
    queried = types.ClientCapabilities(extensions={_OTHER_EXTENSION_ID: {}})
    supported: list[bool] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "probe"
        supported.append(ctx.session.check_client_capability(queried))
        return types.CallToolResult(content=[])

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="probe", input_schema={"type": "object"})])

    server = Server("checker", on_call_tool=call_tool, on_list_tools=list_tools)
    async with Client(server, extensions={_EXTENSION_ID: {"mimeTypes": ["text/html"]}}) as client:
        await client.call_tool("probe", {})

    assert supported == [False]


async def test_server_rejects_capability_when_client_advertises_no_extensions() -> None:
    queried = types.ClientCapabilities(extensions={_EXTENSION_ID: {}})
    supported: list[bool] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "probe"
        supported.append(ctx.session.check_client_capability(queried))
        return types.CallToolResult(content=[])

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="probe", input_schema={"type": "object"})])

    server = Server("checker", on_call_tool=call_tool, on_list_tools=list_tools)
    async with Client(server) as client:
        await client.call_tool("probe", {})

    assert supported == [False]
