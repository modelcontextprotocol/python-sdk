from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bistro")


@mcp.tool()
async def pay_deposit(booking_id: str, ctx: Context) -> str:
    """Take the deposit that confirms a booking."""
    result = await ctx.elicit_url(
        message="A 20 EUR deposit confirms your booking.",
        url=f"https://pay.example.com/deposit/{booking_id}",
        elicitation_id=f"deposit-{booking_id}",
    )
    if result.action == "accept":
        return "Complete the payment in your browser."
    return "No deposit taken. The booking expires in one hour."


@mcp.tool()
async def confirm_deposit(booking_id: str, ctx: Context) -> str:
    """Record a payment reported by the payment provider."""
    await ctx.session.send_elicit_complete(f"deposit-{booking_id}")
    return f"Deposit received for booking {booking_id}."
