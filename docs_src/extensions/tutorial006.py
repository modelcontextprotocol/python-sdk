from collections.abc import Sequence
from typing import Any, Literal

import mcp_types as types

from mcp import Client
from mcp.client import ClaimContext, ClientExtension, ResultClaim
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver import MCPServer

EXTENSION_ID = "com.example/receipts"


class ReceiptResult(types.Result):
    """The claimed result shape; `result_type` pins the wire tag."""

    result_type: Literal["receipt"] = "receipt"
    request_state: str


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
        return {"resultType": "receipt", "requestState": "r-117"}


class Receipts(ClientExtension):
    """Client half: claims the `receipt` shape and supplies the code that finishes it."""

    identifier = EXTENSION_ID

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="receipt", model=ReceiptResult, resolve=self._redeem)]

    async def _redeem(self, claimed: ReceiptResult, ctx: ClaimContext) -> types.CallToolResult:
        return await ctx.session.call_tool("redeem", {"token": claimed.request_state})


mcp = MCPServer("shop", extensions=[ReceiptIssuer()])


@mcp.tool()
def buy(item: str) -> types.CallToolResult:
    """Buy an item."""
    raise NotImplementedError  # ReceiptIssuer answers `buy` before the tool runs


@mcp.tool()
def redeem(token: str) -> str:
    """Exchange a receipt token for the goods."""
    return f"goods for {token}"


async def main() -> None:
    async with Client(mcp, extensions=[Receipts()]) as client:
        result = await client.call_tool("buy", {"item": "lamp"})
        print(result.content)
        # [TextContent(text='goods for r-117')]
