"""Companion examples for src/mcp/server/mcpserver/server.py docstrings."""

from __future__ import annotations

from typing import Any, TypeAlias

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

Message: TypeAlias = dict[str, Any]


async def fetch_data() -> str: ...
async def fetch_weather(city: str) -> str: ...
def read_table_schema(table_name: str) -> str: ...
async def read_file(path: str) -> str: ...


def MCPServer_tool_basic(server: MCPServer) -> None:
    # region MCPServer_tool_basic
    @server.tool()
    def my_tool(x: int) -> str:
        return str(x)

    # endregion MCPServer_tool_basic


def MCPServer_tool_with_context(server: MCPServer) -> None:
    # region MCPServer_tool_with_context
    @server.tool()
    async def tool_with_context(x: int, ctx: Context) -> str:
        await ctx.info(f"Processing {x}")
        return str(x)

    # endregion MCPServer_tool_with_context


def MCPServer_tool_async(server: MCPServer) -> None:
    # region MCPServer_tool_async
    @server.tool()
    async def async_tool(x: int, context: Context) -> str:
        await context.report_progress(50, 100)
        return str(x)

    # endregion MCPServer_tool_async


def MCPServer_completion(server: MCPServer) -> None:
    # region MCPServer_completion
    @server.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        if isinstance(ref, ResourceTemplateReference):
            # Return completions based on ref, argument, and context
            return Completion(values=["option1", "option2"])
        return None

    # endregion MCPServer_completion


def MCPServer_resource_sync_static(server: MCPServer) -> None:
    # region MCPServer_resource_sync_static
    @server.resource("resource://my-resource")
    def get_data() -> str:
        return "Hello, world!"

    # endregion MCPServer_resource_sync_static


def MCPServer_resource_async_static(server: MCPServer) -> None:
    # region MCPServer_resource_async_static
    @server.resource("resource://my-resource")
    async def get_data() -> str:
        data = await fetch_data()
        return f"Hello, world! {data}"

    # endregion MCPServer_resource_async_static


def MCPServer_resource_sync_template(server: MCPServer) -> None:
    # region MCPServer_resource_sync_template
    @server.resource("resource://{city}/weather")
    def get_weather(city: str) -> str:
        return f"Weather for {city}"

    # endregion MCPServer_resource_sync_template


def MCPServer_resource_async_template(server: MCPServer) -> None:
    # region MCPServer_resource_async_template
    @server.resource("resource://{city}/weather")
    async def get_weather(city: str) -> str:
        data = await fetch_weather(city)
        return f"Weather for {city}: {data}"

    # endregion MCPServer_resource_async_template


def MCPServer_prompt_sync(server: MCPServer) -> None:
    # region MCPServer_prompt_sync
    @server.prompt()
    def analyze_table(table_name: str) -> list[Message]:
        schema = read_table_schema(table_name)
        return [
            {
                "role": "user",
                "content": f"Analyze this schema:\n{schema}",
            }
        ]

    # endregion MCPServer_prompt_sync


def MCPServer_prompt_async(server: MCPServer) -> None:
    # region MCPServer_prompt_async
    @server.prompt()
    async def analyze_file(path: str) -> list[Message]:
        content = await read_file(path)
        return [
            {
                "role": "user",
                "content": {
                    "type": "resource",
                    "resource": {
                        "uri": f"file://{path}",
                        "text": content,
                    },
                },
            }
        ]

    # endregion MCPServer_prompt_async


def MCPServer_custom_route(server: MCPServer) -> None:
    # region MCPServer_custom_route
    @server.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    # endregion MCPServer_custom_route


def Context_usage(server: MCPServer) -> None:
    # region Context_usage
    @server.tool()
    async def my_tool(x: int, ctx: Context) -> str:
        # Log messages to the client
        await ctx.info(f"Processing {x}")
        await ctx.debug("Debug info")
        await ctx.warning("Warning message")
        await ctx.error("Error message")

        # Report progress
        await ctx.report_progress(50, 100)

        # Access resources
        data = await ctx.read_resource("resource://data")

        # Get request info
        request_id = ctx.request_id
        client_id = ctx.client_id

        return str(x)

    # endregion Context_usage
