"""
Async transition scope for StateMachine operations.

This context manager wraps an operation and emits SUCCESS/ERROR transitions.
It applies only exact-match transitions (no DEFAULT fallback), executes any
transition effect as a fire-and-forget side effect, and never lets effect
failures influence state changes (failures are logged as warnings).

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

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.state.machine.state_machine import StateMachine, State, InputSymbol

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
    - Apply the exact matching transition only (no DEFAULT fallback).
    - Execute transition effects as fire-and-forget; log a warning on failure.
    - If the resulting state is terminal, reset to the initial state.
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
            self._apply_exact_if_present(self._success)
            self._maybe_reset_if_terminal()
            return False  # do not suppress return value

        # Error path → apply error transition and re-raise (mapped)
        self._apply_exact_if_present(self._error)
        self._maybe_reset_if_terminal()
        self._log_exc(
            "Exception during execution for symbol '%s/%s' in state '%s'",
            self._error.type, self._error.name, self._sm.current_state
        )
        raise self._exc_mapper(exc or RuntimeError("Unknown failure")) from exc

    ### transition mechanics

    def _apply_exact_if_present(self, symbol: "InputSymbol") -> None:
        """Apply the exact-match transition for `symbol` if present; otherwise no-op."""
        state = self._state_or_fail(self._sm.current_state)

        for tr in state.transitions:
            if symbol == tr.input_symbol:
                # set state first (effect is not allowed to interfere with transition)
                self._sm.set_current_state(tr.to_state)

                # Fire-and-forget effect; warn on synchronous failure
                try:
                    apply_callback_with_context(tr.effect, self._sm.context_resolver)
                except Exception as e:  # only synchronous invocation failures are caught here
                    logger.warning(
                        "Transition effect failed (state '%s' -> '%s', symbol %r): %s",
                        state.name, tr.to_state, symbol, e
                    )
                break  # exact match applied; stop scanning

    def _maybe_reset_if_terminal(self) -> None:
        """Reset to initial when the current state is terminal."""
        if self._sm.is_terminal(self._sm.current_state):
            self._sm.set_current_state(self._sm.initial_state)

    def _state_or_fail(self, name: str) -> "State":
        state = self._sm.get_state(name)
        if state is None:
            raise RuntimeError(f"State '{name}' not defined")
        return state
