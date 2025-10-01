"""
Async tool with elicitation example.

cd to the `examples/snippets/clients` directory and run:
    uv run server async_tool_elicitation stdio
"""

import anyio
from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Async Tool Elicitation")


class UserPreferences(BaseModel):
    """Schema for collecting user preferences."""

    continue_processing: bool = Field(description="Should we continue with the operation?")
    priority_level: str = Field(
        default="normal",
        description="Priority level: low, normal, high",
    )


class FileOperationChoice(BaseModel):
    """Schema for file operation confirmation."""

    confirm_operation: bool = Field(description="Confirm the file operation?")
    backup_first: bool = Field(default=True, description="Create backup before operation?")


@mcp.tool(invocation_modes=["async"])
async def process_with_confirmation(operation: str, ctx: Context[ServerSession, None]) -> str:
    """Process an operation that requires user confirmation."""
    await ctx.info(f"Starting operation: {operation}")

    # Simulate some initial processing
    await anyio.sleep(0.5)
    await ctx.report_progress(0.3, 1.0, "Initial processing complete")

    # Ask user for preferences
    result = await ctx.elicit(
        message=f"Operation '{operation}' requires user input. How should we proceed?",
        schema=UserPreferences,
    )

    if result.action == "accept" and result.data:
        if result.data.continue_processing:
            await ctx.info(f"Continuing with {result.data.priority_level} priority")
            # Simulate processing based on user choice
            processing_time = {"low": 0.5, "normal": 1.0, "high": 1.5}.get(result.data.priority_level, 1.0)
            await anyio.sleep(processing_time)
            await ctx.report_progress(1.0, 1.0, "Operation complete")
            return f"Operation '{operation}' completed successfully with {result.data.priority_level} priority"
        else:
            await ctx.warning("User chose not to continue")
            return f"Operation '{operation}' cancelled by user"
    else:
        await ctx.error("User declined or cancelled the operation")
        return f"Operation '{operation}' aborted"


@mcp.tool(invocation_modes=["async"])
async def file_operation(file_path: str, operation_type: str, ctx: Context[ServerSession, None]) -> str:
    """Perform file operation with user confirmation."""
    await ctx.info(f"Analyzing file: {file_path}")

    # Simulate initial analysis
    await anyio.sleep(1)
    await ctx.report_progress(0.3, 1.0, "File analysis complete")

    # Simulate finding something that requires user confirmation
    await ctx.warning(f"About to perform {operation_type} on {file_path} - requires confirmation")

    # Ask user for confirmation
    result = await ctx.elicit(
        message=f"Confirm {operation_type} operation on {file_path}?",
        schema=FileOperationChoice,
    )

    if result.action == "accept" and result.data:
        if result.data.confirm_operation:
            if result.data.backup_first:
                await ctx.info("Creating backup first...")
                await anyio.sleep(0.5)
                await ctx.report_progress(0.7, 1.0, "Backup created")

            await ctx.info(f"Performing {operation_type} operation...")
            await anyio.sleep(1)
            await ctx.report_progress(1.0, 1.0, "Operation complete")

            backup_msg = " (with backup)" if result.data.backup_first else " (no backup)"
            return f"Successfully performed {operation_type} on {file_path}{backup_msg}"
        else:
            return f"Operation {operation_type} on {file_path} cancelled by user"
    else:
        return f"Operation {operation_type} on {file_path} declined"


if __name__ == "__main__":
    mcp.run()
