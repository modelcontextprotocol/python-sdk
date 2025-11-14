"""Example server demonstrating task-based execution with long-running tools."""

import asyncio

from examples.shared.in_memory_task_store import InMemoryTaskStore
from mcp.server.fastmcp import FastMCP

# Create a task store to enable task-based execution
task_store = InMemoryTaskStore()
mcp = FastMCP(name="Task-Based Tool Example", task_store=task_store)


@mcp.tool()
async def long_running_computation(data: str, delay_seconds: float = 2.0) -> str:
    """
    Simulate a long-running computation that benefits from task-based execution.

    This tool demonstrates the 'call-now, fetch-later' pattern where clients can:
    1. Initiate the task without waiting
    2. Disconnect and reconnect later
    3. Poll for status and retrieve results when ready

    Args:
        data: Input data to process
        delay_seconds: Simulated processing time
    """
    # Simulate long-running work
    await asyncio.sleep(delay_seconds)

    # Return processed result
    result = f"Processed: {data.upper()} (took {delay_seconds}s)"
    return result
