from __future__ import annotations
from types import TracebackType
from typing import Callable, Optional, Type, Literal

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.transaction.manager import TransactionManager

from starlette.requests import Request
from mcp.server.fastmcp import Context
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.session import ServerSession

FastMCPContext = Context[ServerSession, LifespanResultT, Request]
logger = get_logger(__name__)
Outcome = Literal["success", "error"]


class AsyncTransactionScope:
    """
    Prepare both outcome-qualified transactions on enter; on exit:
      - if outcome is "success": COMMIT success key, ABORT error key
      - if outcome is "error"  : COMMIT error key,   ABORT success key

    If any PREPARE fails: abort any successfully prepared keys and raise (no inner block runs).
    If COMMIT fails: attempt ABORT of both keys, then raise.
    All ABORT failures are logged and do not suppress the original error.
    """

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
        self._success_key = (state, kind, name, "success")
        self._error_key   = (state, kind, name, "error")
        self._ctx = ctx
        self._log_exc = log_exc
        self._exc_mapper = exc_mapper
        self._prepared_success = False
        self._prepared_error = False

    async def __aenter__(self) -> "AsyncTransactionScope":
        if self._txm is None:
            return self

        try:
            # Prepare both outcomes (manager should no-op if none registered)
            ps = await self._txm.prepare_for(self._success_key, self._ctx)
            pe = await self._txm.prepare_for(self._error_key, self._ctx)
            self._prepared_success = ps > 0
            self._prepared_error = pe > 0
            logger.debug(
                "Prepared transactions: success=%d, error=%d for keys=(%s, %s)",
                ps, pe, self._success_key, self._error_key
            )
        except Exception as e:
            # Best-effort abort of anything that did prepare
            try:
                if self._prepared_success:
                    await self._txm.abort_for(self._success_key, self._ctx)
                if self._prepared_error:
                    await self._txm.abort_for(self._error_key, self._ctx)
            except Exception as aerr:
                logger.warning("Abort after prepare failure also failed: %s", aerr)
            self._log_exc("Transaction prepare failed: %s", e)
            raise self._exc_mapper(e) from e

        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        if self._txm is None:
            return False

        outcome: Outcome = "error" if exc_type is not None else "success"

        commit_key = self._success_key if outcome == "success" else self._error_key
        abort_key  = self._error_key   if outcome == "success" else self._success_key

        # Commit the taken path
        try:
            await self._txm.commit_for(commit_key, self._ctx)
        except Exception as e:
            # Try to clean up both paths; then raise mapped commit error
            try:
                await self._txm.abort_for(commit_key, self._ctx)
            except Exception as a1:
                logger.warning("Abort(after commit failure) failed for %s: %s", commit_key, a1)
            try:
                await self._txm.abort_for(abort_key, self._ctx)
            except Exception as a2:
                logger.warning("Abort(other path) failed for %s: %s", abort_key, a2)
            raise self._exc_mapper(e) from e

        # Abort the non-taken path (best-effort)
        try:
            await self._txm.abort_for(abort_key, self._ctx)
        except Exception as e:
            logger.warning("Abort(non-taken path) failed for %s: %s", abort_key, e)

        return False  # never suppress
