"""
Async transaction scope (prepare/commit/abort), independent of StateMachine.

Usage
-----
    async with AsyncTransactionScope(
        tx_manager=txm,
        state=sm.current_state,
        kind="tool",
        name=tool_name,
        ctx=ctx,
    ):
        await run_the_tool(...)
"""
from __future__ import annotations

from types import TracebackType
from typing import Callable, Optional, Type

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.transaction.manager import TxKey, TransactionManager

from starlette.requests import Request
from mcp.server.fastmcp import Context
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.session import ServerSession

# Short Context alias (no dependency back to state-machine internals)
FastMCPContext = Context[ServerSession, LifespanResultT, Request]

logger = get_logger(__name__)


class AsyncTransactionScope:
    """Prepare on enter; commit on success; abort on error (or on commit failure)."""

    def __init__(
        self,
        *,
        tx_manager: TransactionManager | None,
        state: str,
        kind: str,   # "tool" | "prompt" | "resource"
        name: str,
        ctx: FastMCPContext,    
        log_exc: Callable[..., None] = logger.exception,
        exc_mapper: Callable[[BaseException], BaseException] = lambda e: ValueError(str(e)),
    ):
        self._txm = tx_manager
        self._key: TxKey = (state, kind, name)
        self._ctx = ctx
        self._log_exc = log_exc
        self._exc_mapper = exc_mapper

    async def __aenter__(self) -> "AsyncTransactionScope":
        # No manager or no context → no-op
        if self._txm is None:
            return self

        try:
            prepared = await self._txm.prepare_for(self._key, self._ctx)
            if prepared:
                logger.debug("Prepared %d transaction(s) for key=%s", prepared, self._key)
        except Exception as e:
            # Surface prepare failures to caller
            self._log_exc("Transaction prepare failed for key=%s: %s", self._key, e)
            raise self._exc_mapper(e) from e

        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        if self._txm is None:
            return False  # nothing to do; do not suppress

        if exc_type is None:
            # success → commit; if commit fails, abort best-effort then raise
            try:
                await self._txm.commit_for(self._key, self._ctx)
                return False
            except Exception as e:
                try:
                    await self._txm.abort_for(self._key, self._ctx)
                except Exception as aerr:
                    logger.warning("Abort after commit failure also failed for key=%s: %s", self._key, aerr)
                raise self._exc_mapper(e) from e

        # error path → abort best-effort, then raise original (mapped)
        try:
            await self._txm.abort_for(self._key, self._ctx)
        except Exception as e:
            logger.warning("Abort failed for key=%s: %s", self._key, e)

        raise self._exc_mapper(exc or RuntimeError("Unknown failure")) from exc
