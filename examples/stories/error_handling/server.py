"""Two error channels: ToolError -> is_error result; MCPError -> JSON-RPC protocol error."""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("error-handling-example")

    @mcp.tool()
    def divide(a: float, b: float) -> float:
        """Divide a by b. Division by zero is an execution error the LLM should see."""
        if b == 0:
            # ToolError is caught by the tool wrapper and returned as
            # CallToolResult(is_error=True) — the LLM reads the message and can
            # self-correct.
            raise ToolError("cannot divide by zero")
        return a / b

    @mcp.tool()
    def restricted() -> str:
        """A tool that always rejects the caller at the protocol level."""
        # MCPError escapes the tool wrapper and becomes a JSON-RPC error
        # response — the *host* sees code/message/data, not the LLM.
        raise MCPError(code=INVALID_PARAMS, message="this tool is gated", data={"reason": "demo"})

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
