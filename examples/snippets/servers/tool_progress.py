from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer(name="Progress Example")


@mcp.tool()
async def long_running_task(task_name: str, ctx: Context, steps: int = 5) -> str:
    """Execute a task with progress updates."""
    await ctx.info(f"Starting: {task_name}")  # pyright: ignore[reportDeprecated]

    for i in range(steps):
        progress = (i + 1) / steps
        await ctx.report_progress(
            progress=progress,
            total=1.0,
            message=f"Step {i + 1}/{steps}",
        )
        await ctx.debug(f"Completed step {i + 1}")  # pyright: ignore[reportDeprecated]

    return f"Task '{task_name}' completed"
