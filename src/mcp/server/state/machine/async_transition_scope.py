from __future__ import annotations
from types import TracebackType
from typing import Callable, Optional, Type, TYPE_CHECKING

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.callback import apply_callback_with_context
from mcp.server.state.types import FastMCPContext

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.state.machine.state_machine import StateMachine, State, InputSymbol

logger = get_logger(__name__)


class AsyncTransitionScope:
    """
    Async context manager that wraps an operation and emits SUCCESS/ERROR deltas.

    Behavior:
      - Applies an **exact-match** delta only (no default fallback).
      - Executes edge effects best-effort; failures are logged as warnings and never
        influence state updates.
      - **Terminal rule**: after applying the delta, check terminality for the emitted
        symbol on the **new** current state; if terminal → reset to initial.
      - On the error path, apply the ERROR delta, evaluate terminality, then re-raise
        the mapped exception.
    """

    def __init__(
        self,
        sm: "StateMachine",
        success_symbol: "InputSymbol",
        error_symbol: "InputSymbol",
        *,
        ctx: Optional[FastMCPContext] = None,
        log_exc: Callable[..., None] = logger.exception,
        exc_mapper: Callable[[BaseException], BaseException] = lambda e: ValueError(str(e)),
    ):
        self._sm = sm
        self._success = success_symbol
        self._error = error_symbol
        self._ctx = ctx
        self._log_exc = log_exc
        self._exc_mapper = exc_mapper

    async def __aenter__(self) -> "AsyncTransitionScope":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        # Decide which symbol we’re emitting based on success/error path
        symbol = self._success if exc_type is None else self._error

        # 1) Apply exact-matching delta if present (updates current state + runs effect)
        self._apply_exact_if_present(symbol)

        # 2) If the **new** current state is terminal for this symbol → reset
        if self._sm.is_terminal(symbol, ctx=self._ctx):
            self._sm.reset(ctx=self._ctx)

        # 3) Re-raise on error path (after state update + potential reset)
        if exc_type is None:
            return False  # do not suppress

        self._log_exc(
            "Exception during execution for symbol '%s/%s' in state '%s'",
            symbol.type, symbol.name, self._sm.current_state(ctx=self._ctx),
        )
        raise self._exc_mapper(exc or RuntimeError("Unknown failure")) from exc

    # ----------------------------
    # internals
    # ----------------------------

    def _apply_exact_if_present(self, symbol: "InputSymbol") -> None:
        """Apply the exact-match delta for `symbol` if present; otherwise sink => no-op."""
        state = self._state_or_fail(self._sm.current_state(ctx=self._ctx))
        for edge in state.deltas:
            if symbol == edge.input_symbol:
                # Set state first; effects must not affect semantics.
                self._sm.set_current_state(edge.to_state, ctx=self._ctx)
                try:
                    # Helper takes care of sync/async effect and receives ctx directly
                    apply_callback_with_context(edge.effect, self._ctx)
                except Exception as e:  # synchronous invocation failures only
                    logger.warning(
                        "Delta effect failed (state '%s' -> '%s', symbol %r): %s",
                        state.name, edge.to_state, symbol, e
                    )
                break  # exact match applied; stop scanning

    def _state_or_fail(self, name: str) -> "State":
        state = self._sm.get_state(name)
        if state is None:
            raise RuntimeError(f"State '{name}' not defined")
        return state
