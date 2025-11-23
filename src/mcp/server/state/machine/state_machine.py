from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Type

import hashlib
import threading

from contextvars import ContextVar, Token
from types import TracebackType

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.async_transition_scope import AsyncTransitionScope
from mcp.server.state.types import (
    Callback,
    FastMCPContext,
    PromptResultType,
    ResourceResultType,
    ToolResultType,
)

logger = get_logger(__name__)

# ----------------------------------------------
# Σ (input alphabet)
# ----------------------------------------------

@dataclass(frozen=True)
class InputSymbol:
    """
    Input alphabet letter: (type, ident, result) with a stable derived id.

    Formal role (Σ):
      - Symbols are triples (type, ident, result) and distinguish
        tools/prompts/resources and their outcomes (SUCCESS/ERROR).
      - `id` is a deterministic hash over (type, ident, result), used everywhere
        else in the runtime (edges, terminal sets) to avoid carrying full objects.
    """
    type: str
    ident: str
    result: str
    # Derived, stable identifier for reference from edges/states.
    id: str = field(init=False, compare=True)

    def __post_init__(self) -> None:
        oid = self.make_id(self.type, self.ident, self.result)
        object.__setattr__(self, "id", oid)

    @staticmethod
    def make_id(type_: str, ident: str, result: str) -> str:
        """
        Build a stable symbol id from (type, ident, result).

        The id is a namespaced SHA-1 over 'type\\x1fident\\x1fresult' to be:
          - deterministic across runs
          - compact and comparable as a string key
        """
        payload = f"{type_}\x1f{ident}\x1f{result}".encode("utf-8")
        return hashlib.sha1(payload).hexdigest()

    @classmethod
    def for_tool(cls, ident: str, result: ToolResultType) -> "InputSymbol":
        """Create a tool symbol with a type-safe result qualifier."""
        return cls("tool", ident, result.value)

    @classmethod
    def for_prompt(cls, ident: str, result: PromptResultType) -> "InputSymbol":
        """Create a prompt symbol with a type-safe result qualifier."""
        return cls("prompt", ident, result.value)

    @classmethod
    def for_resource(cls, ident: str, result: ResourceResultType) -> "InputSymbol":
        """Create a resource symbol with a type-safe result qualifier."""
        return cls("resource", ident, result.value)

# ----------------------------------------------
# δ edges
# ----------------------------------------------

@dataclass(frozen=True)
class Edge:
    """
    Directed δ-edge: from `from_state` on an exact symbol-id, move to `to_state`,
    then optionally run `effect`.

    Formal role (δ):
      - Encodes one δ entry: δ(q, a) = q' where q = `from_state` and a = `symbol_id`.
      - The edge is globally stored on the automaton (not on states).

    Note on equality/hashing:
      - Edges are immutable dataclasses; equality and hashing rely solely on
        (from_state, to_state, symbol_id). We deliberately *do not* support a
        list of symbol-ids per edge to preserve structural equality and hashing.
    """
    from_state: str
    to_state: str
    symbol_id: str
    effect: Callback | None = field(default=None, compare=False, repr=False)



# ----------------------------------------------
# Q (states)
# ----------------------------------------------

@dataclass(frozen=True)
class State:
    """
    Named state (element of Q).

    Terminal rule (symbol-driven):
      - A state is considered terminal for a given symbol-id if that id is in
        `terminals` configured on the state.
    """
    name: str
    terminals: list[str] = field(default_factory=list[str], compare=False, repr=False)

# ----------------------------------------------
# DFA runtime
# ----------------------------------------------

class StateMachine:
    """
    Core runtime of the state machine and main API surface.

    Summary:
      - Deterministic DFA over input triples (type, ident, result).
      - Symbols are referenced at runtime via their stable ids.
      - `step(success_symbol, error_symbol, ctx)` returns an `AsyncTransitionScope`
        that acts as the step function.
      - Session-aware via an **ambient** session id (ContextVar). The async transition scope
        binds this ambient session from `ctx` for the duration of the step; if no session is
        bound, the global state is used.

    Formal aggregation:
      - Q (states) via `_states`
      - Σ (alphabet) via `_symbols_by_id` (id → symbol)
      - δ via `_edges`
      - q0 via `initial_state`
      - F is derived at runtime via `is_terminal(symbol_id)` and each state's `terminals`.
    """

    def __init__(
        self,
        initial_state: str,
        states: dict[str, "State"],
        symbols: list["InputSymbol"],
        edges: list["Edge"],
    ) -> None:
        """Bind q0 and the immutable automaton graph (Q, Σ, δ)."""
        if initial_state not in states:
            raise ValueError(f"Unknown initial state: {initial_state}")
        self._states_by_name: dict[str, "State"] = states
        self._initial_state: str = initial_state

        # Σ: store symbols and an id → symbol index for fast lookup/introspection
        self._symbols_by_id: dict[str, "InputSymbol"] = {s.id: s for s in symbols}

        # δ: globally collected edges
        self._edges: list["Edge"] = list(edges)

        # Global (fallback) current state
        self._current_global: str = initial_state

        # Per-session state map (keyed by ambient session id)
        self._current_by_session_id: dict[str, str] = {}

        # Coarse-grained lock to protect the session map and current state updates
        self._lock = threading.RLock()

    def current_state(self) -> str:
        """
        Return the current state name for the current **ambient** session,
        or the global state if no session is bound.
        """
        sid = _AMBIENT_SESSION_ID.get()
        if sid is None:
            with self._lock:
                return self._current_global
        with self._lock:
            # Initialize lazily to q0 if unseen
            return self._current_by_session_id.setdefault(sid, self._initial_state)

    def reset(self) -> None:
        """
        Reset the runtime state to q0 for the current **ambient** session,
        or the global state if no session is bound.
        """
        sid = _AMBIENT_SESSION_ID.get()
        with self._lock:
            if sid is None:
                self._current_global = self._initial_state
            else:
                self._current_by_session_id[sid] = self._initial_state

    def set_current_state(self, new_state: str) -> None:
        """
        Set the current state for the current **ambient** session,
        or the global state if no session is bound.
        """
        if new_state not in self._states_by_name:
            raise ValueError(f"Unknown state: {new_state}")
        sid = _AMBIENT_SESSION_ID.get()
        with self._lock:
            if sid is None:
                self._current_global = new_state
            else:
                self._current_by_session_id[sid] = new_state

    def get_edge(self, symbol_id: str) -> Optional["Edge"]:
        """
        Return the (unique) δ-edge applicable from the *current* state on `symbol_id`.

        Lookup strategy:
          - Read current state (ambient session aware).
          - Scan global δ and select the edge with matching (from_state, symbol_id).
          - Return None if not found.
        """
        sname = self.current_state()
        # The graph is typically small; linear scan is simple and robust.
        # If this becomes hot, replace by an index: (from_state, symbol_id) → Edge.
        for e in self._edges:
            if e.from_state == sname and e.symbol_id == symbol_id:
                return e
        return None
    
    def is_terminal(self, symbol_id: str) -> bool:
        """
        Return True if the passed `symbol_id` equals one of the current state's `terminals`.
        """
        sname = self.current_state()
        state = self._states_by_name[sname]
        return symbol_id in state.terminals

    def step(
        self,
        *,
        success_symbol: "InputSymbol",
        error_symbol: "InputSymbol",
        ctx: Optional[FastMCPContext] = None,
    ) -> AsyncTransitionScope:
        """
        Create an async step scope bound to this machine.

        Contract:
          - Callers pass the full input symbols (not only ids). Managers for tools/prompts/resources
            construct them via the factory helpers (e.g. `InputSymbol.for_tool(...)`).
          - The scope converts the symbols to their stable ids (`symbol.id`) and uses those ids
            for δ lookup and terminal checks.
          - Session scoping is **ambient**; this scope will bind a session id from `ctx` (if resolvable)
            for the duration of the step. If no session is present, the global state is used.
          - `ctx` is forwarded to edge effects.
        """
        return AsyncTransitionScope(
            self,
            success_symbol=success_symbol,
            error_symbol=error_symbol,
            ctx=ctx,
        )

    def available_symbols(self, kind: str) -> set[str]:
        """
        Return the set of *idents* available from the current state for the given kind.
        """
        idents: set[str] = set()
        sname = self.current_state()
        for e in self._edges:
            if e.from_state != sname:
                continue
            sym = self._symbols_by_id.get(e.symbol_id)
            if sym and sym.type == kind:
                idents.add(sym.ident)
        return idents


# ----------------------------------------------
# Ambient session binding 
# ----------------------------------------------

_AMBIENT_SESSION_ID: ContextVar[Optional[str]] = ContextVar(
    f"{__name__}.session_id", default=None
)
class SessionScope:
    """
    Bind/unbind an ambient session id using ContextVar.

    Usage:
        with SessionScope("sess-123"):
            ... all StateMachine calls read "sess-123" implicitly ...
    """
    def __init__(self, session_id: Optional[str]):
        self._session_id = session_id
        self._token: Optional[Token[Optional[str]]] = None  # concrete Token type

    def __enter__(self) -> "SessionScope":
        self._token = _AMBIENT_SESSION_ID.set(self._session_id)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if self._token is not None:
            _AMBIENT_SESSION_ID.reset(self._token)

    async def __aenter__(self) -> "SessionScope":
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.__exit__(exc_type, exc, tb)
