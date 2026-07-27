"""Sampling primitive (lowlevel API): the same server→client round-trip, hand-built."""

from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="summarize",
                    description="Summarize text by asking the host's LLM via sampling/createMessage.",
                    input_schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "summarize"
        assert params.arguments is not None
        prompt = f"Summarize in one sentence:\n\n{params.arguments['text']}"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[types.SamplingMessage(role="user", content=types.TextContent(text=prompt))],
            max_tokens=200,
        )
        assert isinstance(result.content, types.TextContent)
        return types.CallToolResult(content=[types.TextContent(text=result.content.text)])

    return Server("sampling-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
