"""Tasks: task-augmented tool execution via the interceptive half of the extension API.

`Tasks` is an opt-in `Extension`. It intercepts `tools/call`: a plain call runs
inline and returns its `CallToolResult`, but a call carrying a `task` field is
recorded under a task id and returned with that id in
`_meta["io.modelcontextprotocol/related-task"]`, so the client can poll
`tasks/get` / `tasks/result` instead of blocking. `render_report` is the kind of
slower, multi-step tool a caller would rather run as a task.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import Tasks
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("tasks-example", extensions=[Tasks()])

    @mcp.tool(description="Render a multi-section report for the given title.", structured_output=False)
    def render_report(title: str, sections: int) -> str:
        body = "\n".join(f"## Section {n}\n(generated)" for n in range(1, sections + 1))
        return f"# {title}\n\n{body}"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
