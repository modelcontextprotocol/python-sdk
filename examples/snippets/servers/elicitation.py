"""Elicitation examples.

Form mode collects structured, non-sensitive data through a schema; URL mode
directs the user to an external URL for sensitive operations like OAuth or payments.
"""

import uuid

from mcp_types import ElicitRequestURLParams
from pydantic import BaseModel, Field

from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import UrlElicitationRequiredError

mcp = MCPServer(name="Elicitation Example")


class BookingPreferences(BaseModel):
    """Schema for collecting user preferences."""

    checkAlternative: bool = Field(description="Would you like to check another date?")
    alternativeDate: str = Field(
        default="2024-12-26",
        description="Alternative date (YYYY-MM-DD)",
    )


@mcp.tool()
async def book_table(date: str, time: str, party_size: int, ctx: Context) -> str:
    """Book a table with date availability check (form mode elicitation)."""
    if date == "2024-12-25":
        # Date unavailable - use form elicitation to ask for an alternative
        result = await ctx.elicit(
            message=(f"No tables available for {party_size} on {date}. Would you like to try another date?"),
            schema=BookingPreferences,
        )

        if result.action == "accept" and result.data:
            if result.data.checkAlternative:
                return f"[SUCCESS] Booked for {result.data.alternativeDate}"
            return "[CANCELLED] No booking made"
        return "[CANCELLED] Booking cancelled"

    return f"[SUCCESS] Booked for {date} at {time}"


@mcp.tool()
async def secure_payment(amount: float, ctx: Context) -> str:
    """Process a secure payment requiring URL confirmation (URL mode elicitation via `ctx.elicit_url`)."""
    elicitation_id = str(uuid.uuid4())

    result = await ctx.elicit_url(
        message=f"Please confirm payment of ${amount:.2f}",
        url=f"https://payments.example.com/confirm?amount={amount}&id={elicitation_id}",
        elicitation_id=elicitation_id,
    )

    if result.action == "accept":
        # In a real app, confirmation happens out-of-band; verify payment status from your backend
        return f"Payment of ${amount:.2f} initiated - check your browser to complete"
    elif result.action == "decline":
        return "Payment declined by user"
    return "Payment cancelled"


@mcp.tool()
async def connect_service(service_name: str, ctx: Context) -> str:
    """Connect to a third-party service requiring OAuth authorization."""
    elicitation_id = str(uuid.uuid4())

    # When the tool cannot proceed without user authorization, raise UrlElicitationRequiredError:
    # the framework converts it to a -32042 error telling the client to complete a URL elicitation.
    raise UrlElicitationRequiredError(
        [
            ElicitRequestURLParams(
                mode="url",
                message=f"Authorization required to connect to {service_name}",
                url=f"https://{service_name}.example.com/oauth/authorize?elicit={elicitation_id}",
                elicitation_id=elicitation_id,
            )
        ]
    )
