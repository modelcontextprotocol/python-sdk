"""Tools primitive (lowlevel API): hand-built Tool descriptors and CallToolResult."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

CALC_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["add", "sub", "mul"]},
        "a": {"type": "number"},
        "b": {"type": "number"},
    },
    "required": ["op", "a", "b"],
}
CALC_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"op": {"type": "string"}, "result": {"type": "number"}},
    "required": ["op", "result"],
}
ECHO_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="calc",
                    title="Calculator",
                    description="Apply an arithmetic operation to two numbers.",
                    input_schema=CALC_INPUT_SCHEMA,
                    output_schema=CALC_OUTPUT_SCHEMA,
                    annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
                ),
                types.Tool(
                    name="echo",
                    description="Echo the input back as plain text.",
                    input_schema=ECHO_INPUT_SCHEMA,
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.arguments is not None
        if params.name == "calc":
            op, a, b = params.arguments["op"], float(params.arguments["a"]), float(params.arguments["b"])
            result = a + b if op == "add" else a - b if op == "sub" else a * b
            payload = {"op": op, "result": result}
            return types.CallToolResult(
                content=[types.TextContent(text=f"{a} {op} {b} = {result}")],
                structured_content=payload,
            )
        if params.name == "echo":
            return types.CallToolResult(content=[types.TextContent(text=str(params.arguments["text"]))])
        raise NotImplementedError

    return Server("tools-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
