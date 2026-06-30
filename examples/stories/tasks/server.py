"""Tasks (SEP-2663): the server defers a tool call as a task the client fetches.

`Tasks` is an opt-in `Extension`. The server decides, per request, to return a
`CreateTaskResult` instead of a `CallToolResult` for a client that declared the
`io.modelcontextprotocol/tasks` extension; the client then fetches the result via
`tasks/get`. `render_report` is the kind of slower, multi-step tool a caller
would rather run as a task than block on.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import Tasks
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("tasks-example", extensions=[Tasks(default_ttl_ms=60_000)])

    @mcp.tool(description="Render a multi-section report for the given title.", structured_output=False)
    def render_report(title: str, sections: int) -> str:
        body = "\n".join(f"## Section {n}\n(generated)" for n in range(1, sections + 1))
        return f"# {title}\n\n{body}"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
