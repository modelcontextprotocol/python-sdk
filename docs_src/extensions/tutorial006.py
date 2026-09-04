from typing import Any

import mcp.types as types
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver import MCPServer, require_client_extension

EXTENSION_ID = "com.example/receipts"


class ReceiptIssuer(Extension):
    """Server half: answers `buy` with a receipt instead of a final result."""

    identifier = EXTENSION_ID

    async def intercept_tool_call(
        self,
        params: types.CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if params.name != "buy":
            return await call_next(ctx)
        require_client_extension(ctx, EXTENSION_ID)
        return {"resultType": "receipt", "receiptToken": "r-117"}


mcp = MCPServer("shop", extensions=[ReceiptIssuer()])


@mcp.tool()
def buy(item: str) -> types.CallToolResult:
    """Buy an item."""
    raise NotImplementedError  # ReceiptIssuer answers `buy` before the tool runs


@mcp.tool()
def redeem(token: str) -> str:
    """Exchange a receipt token for the goods."""
    return f"goods for {token}"
