from mcp_types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult

from mcp.server.mcpserver import Context, MCPServer

CONFIRM = ElicitRequest(
    params=ElicitRequestFormParams(
        message="Issue this refund?",
        requested_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    )
)


def make_server() -> MCPServer:
    """Every worker process builds one of these, once, at import."""
    mcp = MCPServer("billing")

    @mcp.tool()
    async def refund(amount: int, ctx: Context) -> str | InputRequiredResult:
        """Refund an amount, once a human has confirmed it."""
        if ctx.input_responses is None:
            return InputRequiredResult(input_requests={"ok": CONFIRM}, request_state=f"refund:{amount}")
        answer = (ctx.input_responses or {}).get("ok")
        if not isinstance(answer, ElicitResult) or answer.action != "accept" or not (answer.content or {}).get("ok"):
            return "refund cancelled"
        return f"refunded ${amount}"

    return mcp
