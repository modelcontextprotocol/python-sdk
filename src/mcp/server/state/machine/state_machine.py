"""
Deterministic state machine.

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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.async_transition_scope import AsyncTransitionScope
from mcp.server.state.types import (
    Callback,
    ContextResolver,
    PromptResultType,
    ResourceResultType,
    ToolResultType,
)

logger = get_logger(__name__)

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
    """Directed edge: on exact input symbol, move to ``to_state`` and then run optional effect."""

    to_state: str
    input_symbol: InputSymbol
    effect: Callback = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class State:
    """Named state of the machine. May be initial or terminal (never both)."""

    name: str
    is_initial: bool = field(default=False, compare=False)
    is_terminal: bool = field(default=False, compare=False)
    transitions: list[Transition] = field(default_factory=list[Transition], compare=False, repr=False)  

### Final Runtime State Machine

class StateMachine:
    """Deterministic state machine over input symbol triples.

    Provides an async context manager to drive transitions based on success or error outcomes.
    The context manager is exposed via `transition_scope(...)`.
    """

    def __init__(
        self,
        initial_state: str,
        states: dict[str, State],
        *,
        context_resolver: ContextResolver = None,
    ):
        """Bind an initial state and the immutable state graph."""
        self._states = states
        self._initial = initial_state
        self._current = initial_state
        self._resolve_context = context_resolver

    ### State Access

    @property
    def initial_state(self) -> str:
        """Expose initial state name."""
        return self._initial

    @property
    def current_state(self) -> str:
        """Return the current state name."""
        return self._current
    
    @property
    def context_resolver(self) -> ContextResolver:
        """Expose the resolver callable (may be None)."""
        return self._resolve_context

    def set_current_state(self, new_state: str) -> None:
        """Internal setter for current state (used by the transition scope)."""
        self._current = new_state

    def get_state(self, name: str) -> Optional[State]:
        """Return a state object by name (None if unknown)."""
        return self._states.get(name)

    def is_terminal(self, state_name: str) -> bool:
        """Return True if the given state is marked terminal/final (unknown → False)."""
        s = self._states.get(state_name)
        return s.is_terminal if s else False

    ### Transition Scope

    def transition_scope(
        self,
        *,
        success_symbol: InputSymbol,
        error_symbol: InputSymbol,
        log_exc: Callable[..., None] = logger.exception,
        exc_mapper: Callable[[BaseException], BaseException] = lambda e: ValueError(str(e)),
    ) -> AsyncTransitionScope:
        """Create an async transition scope bound to this machine."""
        return AsyncTransitionScope(
            self,
            success_symbol=success_symbol,
            error_symbol=error_symbol,
            log_exc=log_exc,
            exc_mapper=exc_mapper,
        )
    
    ### Introspection

    def get_available_inputs(self) -> dict[str, set[str]]:
        """List available tool/resource/prompt names from outgoing transitions of the current state."""
        inputs: dict[str, set[str]] = defaultdict(set)
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

