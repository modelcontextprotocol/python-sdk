"""
Finite-state machine builder (public DSL facade over a private builder).

Purpose
-------
Provide a small DSL to declare states and transitions, then build and validate
a deterministic state machine at server startup. The public API exposes:

- StateMachineDefinition (facade)
- StateAPI (fluent state scope)
- TransitionAPI (fluent transition scope)

Chaining model
--------------
The fluent chain alternates:

    StateMachineDefinition → StateAPI → TransitionAPI → StateAPI → ... → done() → StateMachineDefinition

An input symbol is a triple ``(type, name, result)`` where:
- type ∈ {"tool", "prompt", "resource"}
- name is the identifier
- result ∈ {DEFAULT, SUCCESS, ERROR}

At startup the server transfers the accumulated declarations to the private
builder, chooses global or session-scoped machine, then builds and validates.
"""

from typing import Optional, Callable, TypeVar

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.fastmcp.tools import ToolManager
from mcp.server.fastmcp.resources import ResourceManager
from mcp.server.fastmcp.prompts import PromptManager

from mcp.server.state.types import ResourceResultType, ToolResultType, PromptResultType
from mcp.server.state.machine import State, Transition, InputSymbol, StateMachine, SessionScopedStateMachine

logger = get_logger(f"{__name__}.StateMachineBuilder")

### Helper Types 

Callback = Callable[[], None]  # Small alias to keep signatures readable for tooling and type checkers
F = TypeVar("F", bound=Callable[["StateAPI"], None])  # Decorator receives a StateAPI

### Internal Builder 

class _InternalStateMachineBuilder:
    """Private, build-only implementation.
    
    Collects states and transitions during DSL usage and produces either a
    global (process-wide) or session-scoped machine. Validation is invoked
    from build methods, never by users directly. This class must not be
    accessed from user code.
    """

    def __init__(self, tool_manager: ToolManager, resource_manager: ResourceManager, prompt_manager: PromptManager):
        self._states: dict[str, State] = {} # TODO: change this to a list (compare will work based on dataclass)
        self._initial: Optional[str] = None
        self._tool_manager = tool_manager
        self._resource_manager = resource_manager
        self._prompt_manager = prompt_manager

    def add_or_update_state(
            self, name: str, 
            is_initial: bool=False, 
            is_terminal: bool=False
        ) -> None:
        """Add a state or update its configuration.
        
        Note: transitions will be removed when updating the configuration.
        """
        if name in self._states:
            logger.debug("State '%s' already exists; configuration will be updated.", name)

        if is_initial:
            if self._initial is None or self._initial == name:
                self._initial = name
            else:
                msg = (
                    f"Initial state already set to '{self._initial}'; "
                    f"cannot set '{name}' as initial."
                )
                raise ValueError(msg)

        self._states[name] = State(name=name, is_initial=is_initial, is_terminal=is_terminal)

    def add_transition(
        self,
        from_state: str,
        to_state: str,
        symbol: InputSymbol,
        callback: Optional[Callback] = None,
    ) -> None:
        """Add a transition; warn and ignore on duplicates or ambiguities."""
        state = self._states[from_state]
        new_tr = Transition(to_state=to_state, input_symbol=symbol, callback=callback)

        # duplicate?
        if new_tr in state.transitions:
            logger.warning("Transition '%s' already exists; new definition ignored.", new_tr)
            return

        # ambiguous? same symbol already mapped to a different target
        if any(tr.input_symbol == symbol and tr.to_state != to_state for tr in state.transitions):
            logger.warning(
                "Ambiguous transition on %s from '%s': existing target differs; new definition ignored.",
                symbol, from_state,
            )
            return

        state.transitions.append(new_tr)

    def build(self) -> StateMachine:
        """Build a global machine (single current state for the process)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        machine = StateMachine(initial_state=initial, states=self._states)
        return machine
    
    def build_session_scoped(self, *, session_resolver: Callable[[], Optional[str]]) -> "SessionScopedStateMachine":
        """Build a session-scoped machine (state tracked per session id, with global fallback)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        return SessionScopedStateMachine(
            initial_state=initial,
            states=self._states,
            session_resolver=session_resolver,
        )

    def _validate(self):
        """Run structural and reference checks (TODO: move to a dedicated Validator class).

        Planned validations:
        - Exactly one initial state exists.
        - At least one reachable terminal state exists.
        - Terminal states have no outgoing transitions (optional rule).
        - All referenced tools/prompts/resources exist in their managers.
        - (Optional) Every state is reachable from the initial state.
        """
        # Example manager lookups (to be implemented):
        # self._tool_manager.get_tool(name)
        # self._prompt_manager.get_prompt(name)
        # self._resource_manager.get_resource(name)
        pass


### Public API DSL

class StateAPI:
    """Fluent scope for a single state.

    ``transition(to_state)`` returns a TransitionAPI to attach one or more input symbols.
    ``done()`` returns the facade to continue with additional states.
    """

    def __init__(self, builder: _InternalStateMachineBuilder, state_name: str):
        self._builder = builder
        self._name = state_name

    def transition(self, to_state: str) -> "TransitionAPI":
        """Ensure that ``to_state`` exists (create if missing) and return a TransitionAPI to attach inputs.

        By default the created state is terminal; re-declare the state (e.g., via define_state) to change its flags.
        """
        self._builder.add_or_update_state(to_state, is_initial=False, is_terminal=True)  
        return TransitionAPI(self._builder, self._name, to_state)

    def done(self) -> "StateMachineDefinition":
        """Return the facade to continue the fluent chain (same builder instance)."""
        return StateMachineDefinition.from_builder(self._builder)


class TransitionAPI:
    """Fluent scope for a transition from ``from_state`` → ``to_state``.

    Each ``on_*`` attaches an input symbol and returns the StateAPI for the source
    state so you can continue chaining.
    """

    def __init__(self, builder: _InternalStateMachineBuilder, from_state: str, to_state: str):
        self._builder = builder
        self._from = from_state
        self._to = to_state

    def on_tool(
        self,
        name: str,
        result: ToolResultType = ToolResultType.DEFAULT,
        callback: Optional[Callback] = None,
    ) -> StateAPI:
        """Trigger on a tool result (DEFAULT, SUCCESS, or ERROR). Optional callback runs on fire."""
        symbol = InputSymbol.for_tool(name, result)
        self._builder.add_transition(self._from, self._to, symbol, callback)
        return StateAPI(self._builder, self._from)

    def on_prompt(
        self,
        name: str,
        result: PromptResultType = PromptResultType.DEFAULT,
        callback: Optional[Callback] = None,
    ) -> StateAPI:
        """Trigger on a prompt result (DEFAULT, SUCCESS, or ERROR). Optional callback runs on fire."""
        symbol = InputSymbol.for_prompt(name, result)
        self._builder.add_transition(self._from, self._to, symbol, callback)
        return StateAPI(self._builder, self._from)

    def on_resource(
        self,
        name: str,
        result: ResourceResultType = ResourceResultType.DEFAULT,
        callback: Optional[Callback] = None,
    ) -> StateAPI:
        """Trigger on a resource result (DEFAULT, SUCCESS, or ERROR). Optional callback runs on fire."""
        symbol = InputSymbol.for_resource(name, result)
        self._builder.add_transition(self._from, self._to, symbol, callback)
        return StateAPI(self._builder, self._from)
    

### State Machine Definition (public facade over the internal builder)

class StateMachineDefinition:
    """Public DSL facade for declaring states and transitions.

    Users never call build methods; the server builds and validates at startup.

    Decorator style::

        @app.statebuilder.state("start", is_initial=True)
        def _(s):
            s.transition("next").on_tool("my_tool")

    Fluent style::

        app.statebuilder
            .define_state("start", is_initial=True)
            .transition("next").on_tool("my_tool")
            .done()
    """

    def __init__(self, tool_manager: ToolManager, resource_manager: ResourceManager, prompt_manager: PromptManager):
        self._builder = _InternalStateMachineBuilder(tool_manager, resource_manager, prompt_manager)

    @classmethod
    def from_builder(cls, builder: _InternalStateMachineBuilder) -> "StateMachineDefinition":
        """Wrap an existing internal builder (no copy)."""
        obj = cls.__new__(cls)
        obj._builder = builder
        return obj

    def define_state(self, name: str, is_initial: bool = False, is_terminal: bool = False) -> StateAPI:
        """Declare a state and return a StateAPI to continue in fluent style."""
        self._builder.add_or_update_state(name, is_initial, is_terminal)
        return StateAPI(self._builder, name)

    def state(
        self,
        name: str,
        is_initial: bool = False,
        is_terminal: bool = False,
    ) -> Callable[[F], F]:
        """Decorator for declarative state definition. The decorated function receives a StateAPI."""
        def decorator(func: F) -> F:
            state_api: StateAPI = self.define_state(name, is_initial, is_terminal)
            func(state_api)
            return func
        return decorator

    def _to_internal_builder(self) -> _InternalStateMachineBuilder:
        """Internal plumbing only.

        The server uses this at startup to build and validate *after* all registrations,
        so user code is order-independent.
        """
        return self._builder
