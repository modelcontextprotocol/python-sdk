"""
Async transition scope for StateMachine operations.

This context manager wraps an arbitrary operation and drives SUCCESS/ERROR transitions
against a provided StateMachine instance. It implements the full transition logic
(exact match, DEFAULT fallback, terminal reset, and effect callbacks).

Usage
-----
    async with sm.transition_scope(
        success_symbol=InputSymbol.for_tool("t_run", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_run", ToolResultType.ERROR),
    ):
        await run_the_tool(...)
"""
from __future__ import annotations

from types import TracebackType
from typing import Callable, Optional, Type, TYPE_CHECKING

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.callback import apply_callback_with_context
from mcp.server.state.types import DEFAULT_QUALIFIER

# Import only for static type checking to avoid circular imports at runtime.
if TYPE_CHECKING:
    from mcp.server.state.machine.state_machine import StateMachine, State, InputSymbol  # pragma: no cover

logger = get_logger(__name__)


class AsyncTransitionScope:
    """
    Async context manager that wraps an operation and emits SUCCESS/ERROR transitions.

    Parameters
    ----------
    sm : StateMachine
        Target machine to apply transitions to.
    success_symbol : InputSymbol
        Symbol to emit on successful operation completion.
    error_symbol : InputSymbol
        Symbol to emit when an exception escapes the block.
    log_exc : callable
        Logger-compatible callable (default: logger.exception).
    exc_mapper : callable
        Maps original exception -> raised exception (default: ValueError(str(e))).

    Behavior
    --------
    - Exact-match attempt with DEFAULT fallback if no exact edge matches.
    - Runs transition effects via `apply_callback_with_context`.
    - Resets to the initial state when landing in a terminal state.
    """

    def __init__(
        self,
        sm: "StateMachine",
        *,
        success_symbol: "InputSymbol",
        error_symbol: "InputSymbol",
        log_exc: Callable[..., None] = logger.exception,
        exc_mapper: Callable[[BaseException], BaseException] = lambda e: ValueError(str(e)),
    ):
        self._sm = sm
        self._success = success_symbol
        self._error = error_symbol
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
        if exc_type is None:
            self._apply_with_fallback(self._success)
            return False  # do not suppress
        self._apply_with_fallback(self._error)
        self._log_exc(
            "Exception during execution for symbol '%s/%s' in state '%s'",
            self._error.type, self._error.name, self._sm.current_state
        )
        # exc can be None in odd cases; map safely
        raise self._exc_mapper(exc or RuntimeError("Unknown failure")) from exc

    # ---- full transition logic lives here -----------------------------------

    def _apply_with_fallback(self, symbol: "InputSymbol") -> None:
        """Apply exact-match transition; if none, retry with DEFAULT qualifier (no-op if still unmatched)."""
        state = self._state_or_fail(self._sm.current_state)

        if self._apply_exact(state, symbol):
            self._maybe_reset_if_terminal()
            return

        # Lazy import here to avoid circular import at module import time.
        from mcp.server.state.machine.state_machine import InputSymbol as _InputSymbol

        fallback = _InputSymbol(type=symbol.type, name=symbol.name, qualifier=DEFAULT_QUALIFIER)
        self._apply_exact(state, fallback)  # no-op if still unmatched
        self._maybe_reset_if_terminal()

    def _apply_exact(self, state: "State", symbol: "InputSymbol") -> bool:
        """Try to apply an exact transition for `symbol`; update state and run effect if found."""
        for tr in state.transitions:
            if symbol == tr.input_symbol:
                self._sm.set_current_state(tr.to_state)
                apply_callback_with_context(tr.effect, self._sm.context_resolver)
                return True
        return False

    def _maybe_reset_if_terminal(self) -> None:
        """Reset to initial when the current state is terminal."""
        if self._sm.is_terminal(self._sm.current_state):
            # Uses public property from StateMachine
            self._sm.set_current_state(self._sm.initial_state)

    def _state_or_fail(self, name: str) -> "State":
        state = self._sm.get_state(name)
        if state is None:
            raise RuntimeError(f"State '{name}' not defined")
        return state
