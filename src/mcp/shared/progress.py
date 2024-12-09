from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from pydantic import BaseModel

from mcp.shared.context import RequestContext
from mcp.shared.session import BaseSession
from mcp.types import ProgressToken


class Progress(BaseModel):
    progress: float
    total: float | None


@dataclass
class ProgressContext:
    session: BaseSession
    progress_token: ProgressToken
    total: float | None
    current: float = field(default=0.0, init=False)

    async def progress(self, amount: float) -> None:
        """Update progress by the given amount and send notification."""
        self.current += amount
        await self.session.send_progress_notification(
            self.progress_token, self.current, total=self.total
        )

    async def final_progress(self) -> None:
        """Send the final progress notification."""
        if self.total is not None and self.current < self.total:
            self.current = self.total
            await self.session.send_progress_notification(
                self.progress_token, self.current, total=self.total
            )


@asynccontextmanager
async def progress(ctx: RequestContext, total: float | None = None):
    """Context manager for progress tracking and notification.

    Args:
        ctx: Request context containing the session and progress token
        total: Optional total progress amount
    """
    if ctx.meta is None or ctx.meta.progressToken is None:
        raise ValueError("No progress token provided")

    progress_ctx = ProgressContext(ctx.session, ctx.meta.progressToken, total)
    try:
        yield progress_ctx
    finally:
        await progress_ctx.final_progress()