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
    
    Parameters:
    sm : StateMachine
        Target machine to apply transitions to.
    success_symbol : InputSymbol
        Symbol to emit on successful operation completion (e.g., InputSymbol.for_*("<op_name>", SUCCESS)).
    error_symbol : InputSymbol
        Symbol to emit when an exception escapes the block (e.g., InputSymbol.for_*("<op_name>", ERROR)).
    log_exc : callable
        Logger-compatible callable used for error-path logging (default: logger.exception).
    exc_mapper : callable
        Maps the original exception → raised exception (default: ValueError(str(e))).

    Behavior:
    - Applies the **exact-match** transition only (no DEFAULT fallback).
    - Executes transition effects as fire-and-forget; failures are logged as warnings and **never**
      influence state changes.
    - If the resulting state is terminal, resets to the initial state.
    - On the error path, applies the ERROR transition **before** re-raising the mapped exception.
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
            return False  # do not suppress

        # Error path → apply error transition then re-raise (mapped)
        self._apply_exact_if_present(self._error)
        self._maybe_reset_if_terminal()
        self._log_exc(
            "Exception during execution for symbol '%s/%s' in state '%s'",
            self._error.type, self._error.name, self._sm.current_state
        )
        raise self._exc_mapper(exc or RuntimeError("Unknown failure")) from exc

    ### internals 

    def _apply_exact_if_present(self, symbol: "InputSymbol") -> None:
        """Apply the exact-match transition for `symbol` if present; otherwise no-op."""
        state = self._state_or_fail(self._sm.current_state)
        for tr in state.transitions:
            if symbol == tr.input_symbol:
                # Set state first; effects must not affect semantics.
                self._sm.set_current_state(tr.to_state)
                try:
                    apply_callback_with_context(tr.effect, self._sm.context_resolver)
                except Exception as e:  # synchronous invocation failures only
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
