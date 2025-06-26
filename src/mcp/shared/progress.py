from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generic

from pydantic import BaseModel

from mcp.shared.context import LifespanContextT, RequestContext
from mcp.shared.session import (
    BaseSession,
    ReceiveNotificationT,
    ReceiveRequestT,
    ReceiveResultT,
    SendNotificationT,
    SendRequestT,
    SendResultT,
)
from mcp.types import ProgressToken


class Progress(BaseModel):
    progress: float
    total: float | None


@dataclass
class ProgressContext(
    Generic[SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveNotificationT, ReceiveResultT]
):
    session: BaseSession[
        SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveResultT, ReceiveNotificationT
    ]
    progress_token: ProgressToken
    total: float | None
    current: float = field(default=0.0, init=False)

    async def progress(self, amount: float, message: str | None = None) -> None:
        self.current += amount

        await self.session.send_progress_notification(
            self.progress_token, self.current, total=self.total, message=message
        )


@contextmanager
def progress(
    ctx: RequestContext[
        BaseSession[
            SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveResultT, ReceiveNotificationT
        ],
        LifespanContextT,
    ],
    total: float | None = None,
) -> Generator[
    ProgressContext[
        SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveNotificationT, ReceiveResultT
    ],
    None,
]:
    if ctx.meta is None or ctx.meta.progressToken is None:
        raise ValueError("No progress token provided")

    progress_ctx = ProgressContext(ctx.session, ctx.meta.progressToken, total)
    try:
        yield progress_ctx
    finally:
        pass
