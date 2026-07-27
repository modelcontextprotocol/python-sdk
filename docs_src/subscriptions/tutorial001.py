from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer("Sprint Board")

BOARDS = {
    "sprint": {"design": False, "build": False, "ship": False},
    "backlog": {"tidy docs": False},
}


@mcp.resource("board://{name}")
def board(name: str) -> str:
    tasks = BOARDS[name]
    return "\n".join(f"[{'x' if done else ' '}] {task}" for task, done in tasks.items())


@mcp.tool()
async def complete_task(board: str, task: str, ctx: Context) -> str:
    BOARDS[board][task] = True
    await ctx.notify_resource_updated(f"board://{board}")
    return f"{task}: done"


def sprint_report() -> str:
    done = sum(done for tasks in BOARDS.values() for done in tasks.values())
    return f"{done} task(s) done"


@mcp.tool()
async def enable_reports(ctx: Context) -> str:
    mcp.add_tool(sprint_report)
    await ctx.notify_tools_changed()
    return "reporting is live"
