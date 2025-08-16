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

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.callback import apply_callback_with_context
from mcp.server.state.types import (
    Callback,
    ContextResolver,
    DEFAULT_QUALIFIER,
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
    """Directed edge: on exact input symbol, move to ``to_state`` and then run optional callback."""

    to_state: str
    input_symbol: InputSymbol
    callback: Callback = field(default=None, compare=False, repr=False)  # ignored for equality and repr


@dataclass(frozen=True)
class State:
    """Named state of the machine. May be initial or terminal (never both)."""

    name: str
    is_initial: bool = field(default=False, compare=False)
    is_terminal: bool = field(default=False, compare=False)
    transitions: list[Transition] = field(default_factory=list[Transition], compare=False, repr=False)  

### Final Runtime State Machine

class StateMachine:
    """Deterministic state machine over InputSymbol triples."""

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

    @property
    def current_state(self) -> str: # Always READ via property
        """
        Returns the current state name. 

        **Note**: This can be overidden allows subclasses to change how "current" is retrieved.
        """
        return self._current

    def _set_current_state(self, new_state: str) -> None: # Always WRTIE via setter
        """Set the current state.
        
        **Note**: This can be overidden allows subclasses to change how "current" is written.
        """
        self._current = new_state

    def _is_terminal_state(self, state_name: str) -> bool:
        """Return True if the given state is marked terminal/final."""
        s = self._states.get(state_name)
        return s.is_terminal if s else False
    
    def _apply(self, state: State, symbol: InputSymbol) -> bool:
        """Try to apply a transition for `symbol`; update state and run callback if found."""
        for tr in state.transitions:
            if symbol == tr.input_symbol:
                self._set_current_state(tr.to_state)  
                apply_callback_with_context(tr.callback, self._resolve_context) 
                return True
        return False

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

    def transition(self, input_symbol: InputSymbol) -> None:
        """Apply exact-match transition; if none, retry with DEFAULT qualifier as a fallback (no-op if still unmatched)."""
        state = self._states.get(self.current_state)

        if state is None:
            raise RuntimeError(f"State '{self.current_state}' not defined")

        if self._apply(state, input_symbol):
            if self._is_terminal_state(self.current_state):
                self._set_current_state(self._initial)
            return

        fallback = InputSymbol(
            type=input_symbol.type,
            name=input_symbol.name,
            qualifier=DEFAULT_QUALIFIER,
        )

        self._apply(state, fallback)  # no-op if no match

        if self._is_terminal_state(self.current_state):
            self._set_current_state(self._initial)

