"""serve_one / serve_connection mechanics: the kernel drivers a transport entry composes.

`handle_one()` is the single-exchange recipe; `main()` is the loop recipe (what `Server.run()`
does for stdio). Lowlevel-only: `MCPServer` has no public accessor for its underlying `Server` yet.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types as types
from mcp_types.version import LATEST_MODERN_VERSION

from mcp.server.connection import Connection  # deep-path import; shorter re-export planned
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.runner import serve_connection, serve_one  # deep-path import; shorter re-export planned
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.transport_context import TransportContext

__all__ = ["SingleExchangeContext", "build_server", "handle_one"]


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="add", description="Add two integers.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "add" and params.arguments is not None
        total = params.arguments["a"] + params.arguments["b"]
        return types.CallToolResult(content=[types.TextContent(text=str(total))], structured_content={"result": total})

    return Server("serve-one-example", on_list_tools=list_tools, on_call_tool=call_tool)


@dataclass
class SingleExchangeContext:
    """Minimal `DispatchContext` for one inbound request with no back-channel.

    A custom transport entry hand-builds one per request; the SDK ships no public concrete class yet.
    """

    request_id: int | str | None
    transport: TransportContext = field(default_factory=lambda: TransportContext(kind="custom", can_send_request=False))
    message_metadata: None = None
    can_send_request: bool = False
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)

    async def send_raw_request(self, method: str, params: Mapping[str, Any] | None, opts: Any = None) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: Any = None) -> None:
        return None

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        return None


async def handle_one(
    server: Server[Any], method: str, params: Mapping[str, Any], *, lifespan_state: Any
) -> dict[str, Any]:
    """Serve exactly one modern-era request and return its raw result dict.

    The envelope rides in `params._meta` (the 2026 wire shape). Enter `server.lifespan(server)`
    once and thread `lifespan_state` to every call — never enter the lifespan per-request.
    """
    meta = params.get("_meta", {})
    connection = Connection.from_envelope(
        meta.get(types.PROTOCOL_VERSION_META_KEY, LATEST_MODERN_VERSION),
        meta.get(types.CLIENT_INFO_META_KEY),
        meta.get(types.CLIENT_CAPABILITIES_META_KEY),
    )
    return await serve_one(
        server,
        SingleExchangeContext(request_id=1),
        method,
        params,
        connection=connection,
        lifespan_state=lifespan_state,
    )


async def main() -> None:
    """Serve over stdio by building the dispatcher + Connection by hand (loop mode)."""
    server = build_server()
    async with server.lifespan(server) as lifespan_state:
        async with stdio_server() as (read_stream, write_stream):
            dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
                read_stream, write_stream, inline_methods=frozenset({"initialize"})
            )
            connection = Connection.for_loop(dispatcher)
            await serve_connection(server, dispatcher, connection=connection, lifespan_state=lifespan_state)


if __name__ == "__main__":
    anyio.run(main)
