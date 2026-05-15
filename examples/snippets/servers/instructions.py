from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="Workflow Assistant",
    instructions=(
        "Use the project tools together: call get_project_status first, "
        "then use create_task only for missing or blocked work."
    ),
)


@mcp.tool()
def get_project_status(project_id: str) -> str:
    """Summarize current project status."""
    return f"Project {project_id} is on track."


@mcp.tool()
def create_task(project_id: str, title: str) -> str:
    """Create a follow-up task for the project."""
    return f"Created task '{title}' for project {project_id}."
