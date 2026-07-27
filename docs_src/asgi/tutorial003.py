from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import MCPServer

notes = MCPServer("Notes")
tasks = MCPServer("Tasks")


@notes.tool()
def add_note(text: str) -> str:
    """Save a note."""
    return f"Saved: {text}"


@tasks.tool()
def add_task(title: str) -> str:
    """Create a task."""
    return f"Created: {title}"


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(notes.session_manager.run())
        await stack.enter_async_context(tasks.session_manager.run())
        yield


app = Starlette(
    routes=[
        Mount("/notes", app=notes.streamable_http_app()),
        Mount("/tasks", app=tasks.streamable_http_app()),
    ],
    lifespan=lifespan,
)
