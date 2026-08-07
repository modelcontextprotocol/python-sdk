"""Tools primitive: register, list, call, structured output, annotations."""

from typing import Literal

from pydantic import BaseModel

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from stories._hosting import run_server_from_args


class CalcResult(BaseModel):
    op: str
    result: float


def build_server() -> MCPServer:
    mcp = MCPServer("tools-example")

    @mcp.tool(
        title="Calculator",
        description="Apply an arithmetic operation to two numbers.",
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    def calc(op: Literal["add", "sub", "mul"], a: float, b: float) -> CalcResult:
        result = a + b if op == "add" else a - b if op == "sub" else a * b
        return CalcResult(op=op, result=result)

    @mcp.tool(description="Echo the input back as plain text.", structured_output=False)
    def echo(text: str) -> str:
        return text

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
