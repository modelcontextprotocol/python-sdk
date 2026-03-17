"""Example demonstrating how to implement a custom transport
that complies with `BaseClientSession` without using read/write streams or JSON-RPC.
"""

import asyncio
from typing import Any

from mcp import types
from mcp.client.base_client_session import BaseClientSession
from mcp.shared.session import ProgressFnT


class CustomDirectSession:
    """A custom MCP session that communicates with a hypothetical internal API
    rather than using streaming JSON-RPC.

    It satisfies the `BaseClientSession` protocol simply by implementing the required
    methods – no inheritance from `BaseSession` or stream initialization required!
    """

    async def initialize(self) -> types.InitializeResult:
        print("[CustomSession] Initializing custom transport...")
        return types.InitializeResult(
            protocolVersion="2024-11-05",
            capabilities=types.ServerCapabilities(),
            serverInfo=types.Implementation(name="CustomDirectServer", version="1.0.0"),
        )

    async def list_tools(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListToolsResult:
        print("[CustomSession] Fetching tools...")
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="direct_tool",
                    description="A tool executed via direct internal Python call",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: types.RequestParamsMeta | None = None,
    ) -> types.CallToolResult:
        print(f"[CustomSession] Executing tool '{name}'...")
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text", text=f"Hello from the custom transport! Tool '{name}' executed successfully."
                )
            ]
        )

    # Note: To fully satisfy the structural protocol of BaseClientSession for static
    # type checking (mypy/pyright), all protocol methods must be defined.
    # Here we stub the remaining methods for brevity.
    async def send_ping(self, *, meta: types.RequestParamsMeta | None = None) -> types.EmptyResult:
        return types.EmptyResult()

    async def send_request(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def send_notification(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    async def send_progress_notification(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    async def list_resources(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def list_resource_templates(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def read_resource(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def subscribe_resource(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def unsubscribe_resource(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def list_prompts(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def get_prompt(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def set_logging_level(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    async def send_roots_list_changed(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()


# ---------------------------------------------------------------------------
# Using the session with code strictly typed against BaseClientSession
# ---------------------------------------------------------------------------

async def interact_with_mcp(session: BaseClientSession) -> None:
    """This function doesn't know or care if the session is communicating
    via stdio streams, SSE, or a custom internal API!
    It only depends on the abstract `BaseClientSession` methods.
    """

    # 1. Initialize
    init_result = await session.initialize()
    print(f"Connected to: {init_result.serverInfo.name}@{init_result.serverInfo.version}")

    # 2. List Tools
    tools_result = await session.list_tools()
    for tool in tools_result.tools:
        print(f"Found tool: {tool.name} - {tool.description}")

    # 3. Call Tool
    if tools_result.tools:
        call_result = await session.call_tool(tools_result.tools[0].name, arguments={})
        for content in call_result.content:
            if isinstance(content, types.TextContent):
                print(f"Tool Output: {content.text}")


async def main():
    # Instantiate our custom non-streaming transport session
    custom_session = CustomDirectSession()

    # Pass it to the generic runner!
    await interact_with_mcp(custom_session)


if __name__ == "__main__":
    asyncio.run(main())
