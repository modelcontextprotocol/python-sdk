from __future__ import annotations

import asyncio
import inspect
from typing import Optional, Awaitable, Any

from mcp.server.state.types import Callback, FastMCPContext
from mcp.server.state.helper.inject_ctx import inject_context
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


async def _runner(awaitable: Awaitable[Any]) -> None:
    """Await the awaitable and log any exception; used to satisfy create_task's coroutine type."""
    try:
        await awaitable
    except asyncio.CancelledError:
        # Silent: cancellation is a normal shutdown path.
        pass
    except Exception as exc:
        logger.warning("Async callback raised: %s", exc)


def _schedule_fire_and_forget(awaitable: Awaitable[Any]) -> None:
    """
    Schedule the given awaitable as a Task in the current loop.
    Uses a coroutine wrapper so typeshed's create_task(Coroutine) signature is satisfied.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running event loop; dropping async callback result.")
        return

    loop.create_task(_runner(awaitable))


def apply_callback_with_context(
    callback: Optional[Callback],
    ctx: Optional[FastMCPContext],
) -> None:
    """
    Apply callback if present. Result is ignored.
    Context is always passed to `inject_context` (it can handle None).
    Async callbacks are scheduled fire-and-forget.
    """
    if not callable(callback):
        return

    logger.debug(
        "Executing callback function '%s'.",
        getattr(callback, "__name__", repr(callback))
    )

    result: Any = inject_context(callback, ctx)

    if inspect.isawaitable(result):
        _schedule_fire_and_forget(result)
