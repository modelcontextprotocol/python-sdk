
import asyncio, inspect

from mcp.server.state.types import Callback, ContextResolver
from mcp.server.state.helper.inject_ctx import inject_context

from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

def apply_callback_with_context(callback : Callback, ctx_resolver: ContextResolver):
    """ Applies callback if present. Ignores the result. Injects context if resolvable."""
    if callable(callback):
        logger.debug("Executing callback function '%s'.", callback.__name__)#

        ctx = ctx_resolver() if callable(ctx_resolver) else None
        result = inject_context(callback, ctx)

        if inspect.isawaitable(result):
            asyncio.ensure_future(result)  # Async? fire & forget