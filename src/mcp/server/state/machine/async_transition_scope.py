from __future__ import annotations
from types import TracebackType
from typing import Callable, Optional, Type, TYPE_CHECKING

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.callback import apply_callback_with_context
from mcp.server.state.types import FastMCPContext

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.state.machine.state_machine import StateMachine, InputSymbol

logger = get_logger(__name__)


class AsyncTransitionScope:
    """
    Async context manager that wraps an operation and emits SUCCESS/ERROR transitions.

    Session handling:
      - This scope does **not** bind or resolve sessions.
      - The ambient session (if any) must be set by the caller (e.g. via SessionScope).
      - All StateMachine calls use the current ambient session or fall back to global state.

    Behavior:
      - Looks up an exact transition for the emitted symbol from the current state.
      - If such a transition exists:
          * the state is updated to the edge's `to_state`
          * the edge's effect is executed best-effort (failures are logged only).
      - If no transition exists:
          * a reflexive self-transition is assumed (stay in the current state, no effect).
      - After the transition, terminality is evaluated for the symbol-id; if terminal → reset.
      - On the error path, state is updated, terminality is evaluated, then the mapped exception
        is re-raised.
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
        self._ctx = ctx  # passed to edge effects only
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
        # Decide which symbol to emit based on success/error path
        symbol = self._success if exc_type is None else self._error
        symbol_id = symbol.id  # stable over (type, ident, result)

        # 1) Apply exact match OR reflexive self-transition (no-op)
        self._apply_exact_or_self(symbol_id)

        # 2) If the **new** current state is terminal for this symbol-id → reset
        if self._sm.is_terminal(symbol_id):
            self._sm.reset()

        # 3) Re-raise on error path (after state update + potential reset)
        if exc_type is None:
            return False  # do not suppress

        self._log_exc(
            "Exception during execution for symbol '%s/%s' in state '%s'",
            symbol.type, symbol.ident, self._sm.current_state(),
        )
        raise self._exc_mapper(exc or RuntimeError("Unknown failure")) from exc

    # ----------------------------
    # internals
    # ----------------------------

    def _apply_exact_or_self(self, symbol_id: str) -> None:
        """
        Apply the exact transition for `symbol_id` from the current state if present;
        otherwise perform a reflexive self-transition (stay in current state, no effect).

        Self-transition semantics:
          - If no edge is defined for (current_state, symbol_id), the current state
            is preserved and no effect is executed.
          - Terminality is still evaluated afterwards, which allows symbol-driven
            resets even without an explicit edge.
        """
        edge = self._sm.get_edge(symbol_id)
        if edge is None:
            cur = self._sm.current_state()
            logger.debug(
                "Reflexive self-transition: staying in '%s' for symbol_id=%s",
                cur, symbol_id,
            )
            return

        # Exact match: set next state, then best-effort effect
        self._sm.set_current_state(edge.to_state)
        try:
            apply_callback_with_context(edge.effect, self._ctx)
        except Exception as e:  # synchronous invocation failures only
            logger.warning(
                "Transition effect failed (from '%s' -> '%s', symbol_id=%s): %s",
                edge.from_state, edge.to_state, symbol_id, e
            )
