"""Same four tools via lowlevel.Server — inputSchema is hand-written JSON Schema."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

# With lowlevel.Server there is no reflection layer: you author the JSON Schema
# yourself and validate/unpack `params.arguments` in the handler.
PERSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "title": {"type": "string"}},
    "required": ["name"],
}
TOOLS = [
    types.Tool(
        name=f"greet_{variant}",
        description=f"Greet ({variant} input shape)",
        input_schema={"type": "object", "properties": {"who": PERSON_SCHEMA}, "required": ["who"]},
    )
    for variant in ("pydantic", "typeddict", "dataclass")
]
TOOLS.append(
    types.Tool(
        name="greet_dict",
        description="Greet (free-form dict input)",
        input_schema={
            "type": "object",
            "properties": {"who": {"type": "object", "additionalProperties": True}},
            "required": ["who"],
        },
    )
)


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.arguments is not None
        who = params.arguments["who"]
        text = f"Hello {who['name']}, my {who.get('title', 'friend')}"
        return types.CallToolResult(content=[types.TextContent(text=text)])

    return Server("schema-validators-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
