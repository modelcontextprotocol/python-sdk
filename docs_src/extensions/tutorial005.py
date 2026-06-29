import logging
from typing import Any

from mcp_types import CallToolRequestParams

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)


class AuditLog(Extension):
    """Observe every tools/call without touching its result."""

    identifier = "com.example/audit"

    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        logger.info("tool %r called", params.name)
        return await call_next(ctx)


mcp = MCPServer("audited", extensions=[AuditLog()])


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
