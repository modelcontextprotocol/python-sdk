from collections.abc import Sequence
from typing import Any, Literal

import anyio

import mcp.types as types
from mcp import Client
from mcp.client import ClaimContext, ClientExtension, ResultClaim

EXTENSION_ID = "com.example/receipts"


class ReceiptResult(types.Result):
    """The claimed result shape; `result_type` pins the wire tag."""

    result_type: Literal["receipt"] = "receipt"
    receipt_token: str


class Receipts(ClientExtension):
    """Client half: claims the `receipt` shape and supplies the code that finishes it."""

    identifier = EXTENSION_ID

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="receipt", model=ReceiptResult, resolve=self._redeem)]

    async def _redeem(self, claimed: ReceiptResult, ctx: ClaimContext) -> types.CallToolResult:
        return await ctx.session.call_tool("redeem", {"token": claimed.receipt_token})


async def main() -> None:
    async with Client("http://localhost:8000/mcp", extensions=[Receipts()]) as client:
        result = await client.call_tool("buy", {"item": "lamp"})
        print(result.content)
        # [TextContent(type='text', text='goods for r-117', annotations=None, meta=None)]


if __name__ == "__main__":
    anyio.run(main)
