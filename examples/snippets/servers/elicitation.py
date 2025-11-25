"""Elicitation examples demonstrating form and URL mode elicitation.

Form mode elicitation collects structured, non-sensitive data through a schema.
URL mode elicitation directs users to external URLs for sensitive operations
like OAuth flows, credential collection, or payment processing.
"""

import uuid

from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import ElicitRequestURLParams

mcp = FastMCP(name="Elicitation Example")


class BookingPreferences(BaseModel):
    """Schema for collecting user preferences."""

    checkAlternative: bool = Field(description="Would you like to check another date?")
    alternativeDate: str = Field(
        default="2024-12-26",
        description="Alternative date (YYYY-MM-DD)",
    )


@mcp.tool()
async def book_table(date: str, time: str, party_size: int, ctx: Context[ServerSession, None]) -> str:
    """Book a table with date availability check.

    This demonstrates form mode elicitation for collecting non-sensitive user input.
    """
    # Check if date is available
    if date == "2024-12-25":
        # Date unavailable - ask user for alternative
        result = await ctx.elicit(
            message=(f"No tables available for {party_size} on {date}. Would you like to try another date?"),
            schema=BookingPreferences,
        )

        if result.action == "accept" and result.data:
            if result.data.checkAlternative:
                return f"[SUCCESS] Booked for {result.data.alternativeDate}"
            return "[CANCELLED] No booking made"
        return "[CANCELLED] Booking cancelled"

    # Date available
    return f"[SUCCESS] Booked for {date} at {time}"


@mcp.tool()
async def secure_payment(amount: float, ctx: Context[ServerSession, None]) -> str:
    """Process a secure payment requiring URL confirmation.

    This demonstrates URL mode elicitation using ctx.elicit_url() for
    operations that require out-of-band user interaction.
    """
    elicitation_id = str(uuid.uuid4())

    result = await ctx.elicit_url(
        message=f"Please confirm payment of ${amount:.2f}",
        url=f"https://payments.example.com/confirm?amount={amount}&id={elicitation_id}",
        elicitation_id=elicitation_id,
    )

    if result.action == "accept":
        # In a real app, the payment confirmation would happen out-of-band
        # and you'd verify the payment status from your backend
        return f"Payment of ${amount:.2f} initiated - check your browser to complete"
    elif result.action == "decline":
        return "Payment declined by user"
    return "Payment cancelled"


@mcp.tool()
async def connect_service(service_name: str, ctx: Context[ServerSession, None]) -> str:
    """Connect to a third-party service requiring OAuth authorization.

    This demonstrates the "throw error" pattern using UrlElicitationRequiredError.
    Use this pattern when the tool cannot proceed without user authorization.
    """
    elicitation_id = str(uuid.uuid4())

    # Raise UrlElicitationRequiredError to signal that the client must complete
    # a URL elicitation before this request can be processed.
    # The MCP framework will convert this to a -32042 error response.
    raise UrlElicitationRequiredError(
        [
            ElicitRequestURLParams(
                mode="url",
                message=f"Authorization required to connect to {service_name}",
                url=f"https://{service_name}.example.com/oauth/authorize?elicit={elicitation_id}",
                elicitationId=elicitation_id,
            )
        ]
    )
