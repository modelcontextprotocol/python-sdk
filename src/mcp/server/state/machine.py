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
from typing import Optional, Callable
from collections import defaultdict

from mcp.server.fastmcp.utilities.logging import get_logger

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

# TODO: implement auto transition to initial if final state is reached

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

    def transition(self, input_symbol: InputSymbol) -> None:
        """Apply exact-match transition; if none, retry with DEFAULT qualifier as a fallback (no-op if still unmatched)."""
        # READ via property (do it always like this to keep session compability)
        state = self._states.get(self.current_state)
        if state is None:
            raise RuntimeError(f"State '{self.current_state}' not defined")

        if self._apply(state, input_symbol):
            return

        fallback = InputSymbol(
            type=input_symbol.type,
            name=input_symbol.name,
            qualifier=DEFAULT_QUALIFIER,
        )
        self._apply(state, fallback)  # no-op if no match


### Final Runtime State Machine (Session scoped)

class SessionScopedStateMachine(StateMachine):
    """Same API as StateMachine; scopes current state per session via a resolver."""

    def __init__(
        self,
        initial_state: str,
        states: dict[str, State],
        *,
        session_resolver: Callable[[], Optional[str]],
    ):
        """Inject a resolver that yields the active session id; state is tracked per session."""
        super().__init__(initial_state, states)
        self._resolve_sid = session_resolver
        self._current_by_session: dict[str, str] = {}

    def ensure_session(self, session_id: str) -> None:
        """Initialize session-local state with the initial state if unseen."""
        self._current_by_session.setdefault(session_id, self._initial)

    @property
    def current_state(self) -> str:
        """Return the session-local state if a session id is resolved; otherwise fall back to the global state."""
        sid = self._resolve_sid()
        if not sid:
            return super().current_state
        return self._current_by_session.get(sid, self._initial)

    def _set_current_state(self, new_state: str) -> None:
        """Set the session-local state if a session id is resolved; otherwise set the global state."""
        sid = self._resolve_sid()
        if not sid:
            return super()._set_current_state(new_state)
        self._current_by_session[sid] = new_state
