import mcp.types as types
from mcp import ClientSession


async def cancel_request(session: ClientSession) -> None:
    """Send a cancellation notification for a previously-issued request."""
    await session.send_notification(
        types.ClientNotification(
            types.CancelledNotification(
                params=types.CancelledNotificationParams(
                    requestId="request-id-to-cancel",
                    reason="User navigated away",
                )
            )
        )
    )
