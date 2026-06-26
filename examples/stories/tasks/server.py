"""Tasks: task-augmented tool execution via the interceptive half of the extension API.

`Tasks` is an opt-in `Extension`. It intercepts `tools/call`: a plain call passes
through, but a call carrying a `task` field is recorded under a task id and
returned with that id in `_meta`. It also serves the `tasks/*` methods so a
client can poll status and fetch the payload.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import Tasks
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("tasks-example", extensions=[Tasks()])

    @mcp.tool(description="Echo the input back as plain text.", structured_output=False)
    def echo(text: str) -> str:
        return text

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
