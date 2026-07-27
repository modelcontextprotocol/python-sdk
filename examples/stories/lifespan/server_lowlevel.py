"""Process-scoped dependency injection via lowlevel `Server(lifespan=...)`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args


@dataclass
class AppState:
    db: dict[str, str]


@asynccontextmanager
async def app_lifespan(server: Server[AppState]) -> AsyncIterator[AppState]:
    db = {"alpha": "one", "beta": "two"}
    try:
        yield AppState(db=db)
    finally:
        db.clear()


LOOKUP_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"key": {"type": "string"}},
    "required": ["key"],
}


def build_server() -> Server[AppState]:
    async def list_tools(
        ctx: ServerRequestContext[AppState], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="lookup",
                    description="Look up a key in the process-scoped store.",
                    input_schema=LOOKUP_INPUT_SCHEMA,
                )
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext[AppState], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        assert params.name == "lookup" and params.arguments is not None
        value = ctx.lifespan_context.db[params.arguments["key"]]
        return types.CallToolResult(content=[types.TextContent(text=value)])

    return Server[AppState](
        "lifespan-example",
        lifespan=app_lifespan,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
