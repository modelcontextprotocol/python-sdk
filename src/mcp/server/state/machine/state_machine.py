from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set, Dict

import threading

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.extract_session_id import extract_session_id
from mcp.server.state.machine.async_transition_scope import AsyncTransitionScope
from mcp.server.state.types import (
    Callback,
    FastMCPContext,
    PromptResultType,
    ResourceResultType,
    ToolResultType,
)

logger = get_logger(__name__)


# ------ Σ (input alphabet)

@dataclass(frozen=True)
class InputSymbol:
    """
    Input alphabet letter: (type, name, result).

    Formal role (Σ):
      - Symbols are triples (type, name, qualifier) and distinguish
        tools/prompts/resources and their outcomes (SUCCESS/ERROR).
    """
    type: str
    name: str
    qualifier: str

    @classmethod
    def for_tool(cls, name: str, result: ToolResultType) -> "InputSymbol":
        """Create a tool symbol with a type-safe result qualifier."""
        return cls("tool", name, result.value)

    @classmethod
    def for_prompt(cls, name: str, result: PromptResultType) -> "InputSymbol":
        """Create a prompt symbol with a type-safe result qualifier."""
        return cls("prompt", name, result.value)

    @classmethod
    def for_resource(cls, name: str, result: ResourceResultType) -> "InputSymbol":
        """Create a resource symbol with a type-safe result qualifier."""
        return cls("resource", name, result.value)


# ------ δ edges

@dataclass(frozen=True)
class Edge:
    """
    Directed δ-edge: on an exact input symbol, move to `to_state`,
    then optionally run `effect`.

    Formal role (δ):
      - Encodes one δ entry from the *current* state: δ(q, a) = q'.
      - The source state is implicit via membership in a State.deltas list.
    """
    to_state: str
    input_symbol: InputSymbol
    effect: Callback | None = field(default=None, compare=False, repr=False)


# ------ Q (states)

@dataclass(frozen=True)
class State:
    """
    Named state (element of Q).

    Terminal rule (symbol-driven):
      - A state is considered terminal for a given symbol if that symbol
        equals `termination_symbol` configured on the state.
      - Outgoing δ-edges are represented as `deltas` for convenience.
        (Formally, δ lives on the automaton.)
    """
    name: str
    deltas: list[Edge] = field(default_factory=list[Edge], compare=False, repr=False)
    terminals: list[InputSymbol] = field(default_factory=list[InputSymbol], compare=False, repr=False)


# ------ DFA runtime

class StateMachine:
    """
    Core runtime of the state machine and main API surface.

    Summary:
      - Deterministic DFA over input triples (type, name, result).
      - `step(success, error, ctx)` returns an `AsyncTransitionScope` that acts as the step function.
      - Session-aware: when `ctx` provides a usable `session_id`, state is tracked per session; otherwise global.

    Formal aggregation:
      - Q (states) via `states_by_name`
      - Σ (alphabet) is implicit in `Edge.input_symbol`
      - δ via the edges held on states
      - q0 via `initial_state`
      - F is derived at runtime via `is_terminal(symbol, ctx)` and each state's `terminals`.
    """

    def __init__(self, initial_state: str, states: Dict[str, "State"]) -> None:
        """Bind an initial state and the immutable state graph."""
        if initial_state not in states:
            raise ValueError(f"Unknown initial state: {initial_state}")
        self._states: Dict[str, "State"] = states
        self._initial: str = initial_state

        # Global (fallback) current state
        self._current_global: str = initial_state

        # Per-session state map (only used when ctx is provided and yields a session id)
        self._current_by_session_id: Dict[str, str] = {}

        # Coarse-grained lock to protect the session map and current state updates
        self._lock = threading.RLock()

    # ----------------------------
    # State access
    # ----------------------------

    @property
    def initial_state(self) -> str:
        """Expose initial state name (q0)."""
        return self._initial

    def current_state(self, ctx: Optional[FastMCPContext] = None) -> str:
        """
        Return the current state name for the given `ctx` (per-session), or the global state if `ctx` is None
        or does not contain a resolvable session id.
        """
        sid = self._resolve_session_id(ctx)
        if sid is None:
            with self._lock:
                return self._current_global
        with self._lock:
            # Initialize lazily to q0 if unseen
            return self._current_by_session_id.setdefault(sid, self._initial)

    def reset(self, ctx: Optional[FastMCPContext] = None) -> None:
        """
        Reset the runtime state to q0 for the given `ctx` (per-session), or the global state if `ctx` is None.
        """
        sid = self._resolve_session_id(ctx)
        with self._lock:
            if sid is None:
                self._current_global = self._initial
            else:
                self._current_by_session_id[sid] = self._initial

    def set_current_state(self, new_state: str, ctx: Optional[FastMCPContext] = None) -> None:
        """
        Set the current state for the given `ctx` (per-session), or the global state if `ctx` is None.
        """
        if new_state not in self._states:
            raise ValueError(f"Unknown state: {new_state}")
        sid = self._resolve_session_id(ctx)
        with self._lock:
            if sid is None:
                self._current_global = new_state
            else:
                self._current_by_session_id[sid] = new_state

    def get_state(self, name: str) -> Optional["State"]:
        """Return a state object by name (None if unknown)."""
        return self._states.get(name)

    # ----------------------------
    # Terminality (symbol-driven)
    # ----------------------------

    def is_terminal(self, symbol: "InputSymbol", ctx: Optional[FastMCPContext] = None) -> bool:
        """
        Return True if the passed `symbol` equals one of the current state's `terminals`.
        """
        sname = self.current_state(ctx)
        state = self._states[sname]
        return symbol in state.terminals

    # ----------------------------
    # Stepping as async scope
    # ----------------------------

    def step(
        self,
        *,
        success_symbol: "InputSymbol",
        error_symbol: "InputSymbol",
        ctx: Optional[FastMCPContext] = None,
    ) -> AsyncTransitionScope:
        """
        Create an async step scope bound to this machine.

        Usage:
            async with machine.step(success_symbol=..., error_symbol=..., ctx=...):
                ... run user code ...
            On normal exit → SUCCESS step; on exception → ERROR step.
        """
        return AsyncTransitionScope(
            self,
            success_symbol=success_symbol,
            error_symbol=error_symbol,
            ctx=ctx,
        )

    # ----------------------------
    # Introspection
    # ----------------------------

    def available_symbols(self, kind: str, ctx: Optional[FastMCPContext] = None) -> Set[str]:
        """
        Return the set of *names* available from the current state (for `ctx` or global) for the given kind.

        Args:
            kind: one of {"tool", "resource", "prompt"}.

        Returns:
            Set of names (e.g., tool names) allowed in the current state.
        """
        names: Set[str] = set()
        sname = self.current_state(ctx)
        state = self._states[sname]
        for edge in state.deltas:
            sym = edge.input_symbol
            if sym.type == kind:
                names.add(sym.name)
        return names

    # ----------------------------
    # helpers
    # ----------------------------

    def _resolve_session_id(self, ctx: Optional[FastMCPContext]) -> Optional[str]:
        """
        Extract a session id from `ctx`. Returns None if `ctx` is None or extraction fails.
        """
        if ctx is None:
            return None
        try:
            return extract_session_id(ctx)
        except Exception:
            # Fail silently to global mode; noisy logs would spam for callers without sessioning.
            return None