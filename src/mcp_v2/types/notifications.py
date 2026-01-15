from typing import Annotated, Literal

from pydantic import Field

from mcp_v2.types.base import NotificationParams, ProgressToken
from mcp_v2.types.json_rpc import NotificationBase


class ProgressNotificationParams(NotificationParams):
    """Parameters for a notifications/progress notification."""

    progress_token: Annotated[ProgressToken, Field(alias="progressToken")]
    progress: float
    total: float | None = None
    message: str | None = None


class ProgressNotification(NotificationBase[Literal["notifications/progress"], ProgressNotificationParams]):
    """Out-of-band notification to inform the receiver of a progress update for a long-running request."""

    method: Literal["notifications/progress"] = "notifications/progress"
