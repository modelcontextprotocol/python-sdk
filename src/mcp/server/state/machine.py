"""
Session-scoped deterministic state machine.

Formal model
------------
We use the classical definition S = (Q, Σ, δ, q0, F).

- Q: set of states
- Σ: input alphabet of symbols I ⊆ T x N x R, where
      T ∈ {"tool", "prompt", "resource"},
      N is the identifier space for names,
      R is a result type (DEFAULT, SUCCESS, ERROR)
- δ: transition function δ: Q x I → Q (captured as explicit Transition edges)
- q0: initial state
- F: set of terminal states

Input symbols
-------------
Each input symbol is a triple ``(type, name, result)`` and acts as a letter of the
alphabet. In practice, available symbols per state derive from the tools, resources,
and prompts that are enabled in that state.

Callbacks
---------
A transition may define an optional callback executed after the state update.
It can be synchronous or awaitable; awaitables are scheduled fire-and-forget.
"""

import asyncio, inspect

from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from collections import defaultdict

from mcp.server.fastmcp.utilities.logging import get_logger

from mcp.server.state.helper.extract_session_id import extract_session_id
from mcp.server.state.types import ResourceResultType, ToolResultType, PromptResultType, DEFAULT_QUALIFIER

logger = get_logger(__name__)

Callback = Callable[[], None]

### Internal Structures 

@dataclass(frozen=True)  # (frozen=True) cannot be changed
class InputSymbol:
    """Input letter of the alphabet: (type, name, result)."""

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


@dataclass(frozen=True)
class Transition:
    """Directed edge: on exact input symbol, move to ``to_state`` and then run optional callback."""

    to_state: str
    input_symbol: InputSymbol
    callback: Optional[Callback] = field(default=None, compare=False, repr=False)  # ignored for equality and repr


@dataclass(frozen=True)
class State:
    """Named state of the machine. May be initial or terminal (never both)."""

    name: str
    is_initial: bool = False
    is_terminal: bool = False
    transitions: list[Transition] = field(default_factory=list[Transition], compare=False, repr=False)  


### Final Runtime State Machine

class StateMachine:
    """Deterministic state machine over InputSymbol triples."""

    def __init__(self, initial_state: str, states: dict[str, State]):
        """Bind an initial state and the immutable state graph."""
        self._states = states
        self._initial = initial_state
        self._current = initial_state

    @property
    def current_state(self) -> str:
        """Return the current state name."""
        return self._current

    # allow subclasses to change how "current" is written
    def _set_current_state(self, new_state: str) -> None:
        """Set the current state (override to customize persistence or scoping)."""
        self._current = new_state

    def get_available_inputs(self) -> dict[str, set[str]]:
        """List available tool/resource/prompt names from outgoing transitions of the current state."""
        inputs: dict[str, set[str]] = defaultdict(set)
        # READ via property (already OK)
        state = self._states[self.current_state]
        for tr in state.transitions:
            symbol = tr.input_symbol
            if symbol.type == "tool":
                inputs["tools"].add(symbol.name)
            elif symbol.type == "resource":
                inputs["resources"].add(symbol.name)
            elif symbol.type == "prompt":
                inputs["prompts"].add(symbol.name)
        return {
            "tools": inputs.get("tools", set()),
            "resources": inputs.get("resources", set()),
            "prompts": inputs.get("prompts", set()),
        }

    def transition(self, input_symbol: InputSymbol) -> None:
        """Apply exact-match transition; if none, retry with DEFAULT qualifier as a fallback (no-op if still unmatched)."""
        # READ via property (do it always like this to keep session compability)
        state = self._states.get(self.current_state)
        if state is None:
            raise RuntimeError(f"State '{self.current_state}' not defined")

        if self._apply(state, input_symbol):
            # after apply: check if terminal; if so, reset to initial
            if self._is_terminal_state(self.current_state):
                self._reset_to_initial()
            return

        fallback = InputSymbol(
            type=input_symbol.type,
            name=input_symbol.name,
            qualifier=DEFAULT_QUALIFIER,
        )
        self._apply(state, fallback)  # no-op if no match
        # after apply (fallback): check if terminal; if so, reset to initial
        if self._is_terminal_state(self.current_state):
            self._reset_to_initial()

    def _apply(self, state: State, symbol: InputSymbol) -> bool:
        """Try to apply a transition for ``symbol``; update state and run callback if found."""
        for tr in state.transitions:
            if symbol == tr.input_symbol:
                # WRITE via setter
                self._set_current_state(tr.to_state)
                if tr.callback:
                    coro = tr.callback()
                    # TODO: Maybe change this later with some kind of handler?
                    if inspect.isawaitable(coro):  # async? fire & forget
                        asyncio.create_task(coro)
                return True
        return False
    
    def _is_terminal_state(self, state_name: str) -> bool:
        """Return True if the given state is marked terminal/final."""
        s = self._states.get(state_name)
        return bool(s and (getattr(s, "is_terminal", False) or getattr(s, "terminal", False)))

    def _reset_to_initial(self) -> None:
        """Reset to initial state."""
        self._set_current_state(self._initial)


### Final Runtime State Machine (Session scoped)

class SessionScopedStateMachine(StateMachine):
    """Same API as StateMachine; scopes current state per session via a resolver."""

    def __init__(
        self,
        initial_state: str,
        states: dict[str, State],
        *,
        context_resolver: Callable[[], Optional[Any]],
    ):
        """Inject a resolver that yields the current request Context; state is tracked per session id."""
        super().__init__(initial_state, states)
        self._resolve_context = context_resolver
        self._current_by_session_id: dict[str, str] = {}

    def ensure_session_id(self, session_id: str) -> None:
        """Initialize state for the given session_id if unseen."""
        self._current_by_session_id.setdefault(session_id, self._initial)
        logger.info("Registered inital state for session %s", session_id)

    def cleanup_session_id(self, session_id: str) -> None:
        """Remove state tracking for the given session_id."""
        self._current_by_session_id.pop(session_id, None)

    def _resolve_sid(self) -> Optional[str]:
        """Resolve session id from the current request context (global fallback when unavailable)."""
        ctx = self._resolve_context()
        if ctx is None:
            return None
        return extract_session_id(ctx)

    @property
    def current_state(self) -> str:
        """Return the state for the resolved session id; otherwise fall back to the global state."""
        sid = self._resolve_sid()
        if not sid:
            return super().current_state
        self.ensure_session_id(sid)
        return self._current_by_session_id.get(sid, self._initial)

    def _set_current_state(self, new_state: str) -> None:
        """Set the state for the resolved session id; otherwise set the global state."""
        sid = self._resolve_sid()
        if not sid:
            return super()._set_current_state(new_state)
        self.ensure_session_id(sid)
        self._current_by_session_id[sid] = new_state