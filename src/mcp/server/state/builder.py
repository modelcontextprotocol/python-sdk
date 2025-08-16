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
from typing import Callable, Optional, TypeVar

from mcp.server.fastmcp.prompts import PromptManager
from mcp.server.fastmcp.resources import ResourceManager
from mcp.server.fastmcp.tools import ToolManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.state_machine import (
    InputSymbol,
    State,
    StateMachine,
    Transition,
)
from mcp.server.state.machine.state_machine_session_scoped import (
    SessionScopedStateMachine,
)
from mcp.server.state.types import (
    Callback,
    ContextResolver,
    PromptResultType,
    ResourceResultType,
    ToolResultType,
)
from mcp.server.state.validator import StateMachineValidator, ValidationIssue


logger = get_logger(f"{__name__}.StateMachineBuilder")

### Helper Types 

F = TypeVar("F", bound=Callable[["StateAPI"], None])  # Decorator receives a StateAPI

### Internal Builder 

class _InternalStateMachineBuilder:
    """Private, build-only implementation.
    
    Collects states and transitions during DSL usage and produces either a
    global (process-wide) or session-scoped machine. Validation is invoked
    from build methods, never by users directly. This class must not be
    accessed from user code.
    """

    def __init__(self, tool_manager: ToolManager | None, resource_manager: ResourceManager | None, prompt_manager: PromptManager | None):
        self._states: dict[str, State] = {}
        self._initial: Optional[str] = None
        self._tool_manager = tool_manager
        self._resource_manager = resource_manager
        self._prompt_manager = prompt_manager

    def add_or_update_state(
        self,
        name: str,
        is_initial: bool = False,
        is_terminal: bool = False,
        *,
        update: bool = False,
    ) -> None:
        """Add a state or (optionally) update its configuration.

        Behavior:
        - Not exists: create the state (ignores `update`).
        - Exists & update=False: ignore (no changes). Logged at DEBUG.
        - Exists & update=True: replace the configuration (transitions are reset).

        Initial-state rule:
        - If `is_initial=True` and another initial is already set, raise ValueError.
        """
        exists = name in self._states

        if exists and not update:
            logger.debug("State '%s' already exists; update=False. Configuration will be ignored.", name)
            return

        # Validate initial flag before writing
        if is_initial and self._initial is not None and self._initial != name:
            raise ValueError(
                f"Initial state already set to '{self._initial}'; cannot set '{name}' as initial."
            )

        if exists and update:
            logger.debug("State '%s' exists; configuration will be updated.", name)

        # Note: updating replaces the State object and clears transitions by design
        self._states[name] = State(name=name, is_initial=is_initial, is_terminal=is_terminal)

        if is_initial:
            self._initial = name

    def add_transition(
        self,
        from_state: str,
        to_state: str,
        symbol: InputSymbol,
        callback: Callback = None,
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

    def build(self, *, context_resolver: ContextResolver = None) -> StateMachine:
        """Build a global machine (single current state for the process)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        return StateMachine(
            initial_state=initial,
            states=self._states,
            context_resolver=context_resolver,
        )
    
    def build_session_scoped(self, *, context_resolver: ContextResolver = None) -> SessionScopedStateMachine:
        """Build a session-scoped machine (state tracked per session id, with global fallback)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        return SessionScopedStateMachine(
            initial_state=initial,
            states=self._states,
            context_resolver=context_resolver,
        )
        
    def _validate(self) -> None:
        """Run structural and reference checks """

        issues: list[ValidationIssue] = StateMachineValidator(
            states=self._states,
            initial_state=self._initial,
            tool_manager=self._tool_manager,         # ToolManager
            prompt_manager=self._prompt_manager,     # PromptManager
            resource_manager=self._resource_manager, # ResourceManager
        ).validate()

        # Separate issues by severity
        errors = [i.message for i in issues if i.level == "error"]
        warnings = [i.message for i in issues if i.level == "warning"]

        # Log warnings
        for w in warnings:
            logger.warning("State machine validation warning: %s", w)

        # Fail if errors exist
        if errors:
            raise ValueError("Invalid state machine:\n- " + "\n- ".join(errors))

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
        """Ensure ``to_state`` exists (create if missing) and return a TransitionAPI to attach inputs.

        Behavior:
        - Creates the target state as **terminal by default** (placeholder).
        - **Never updates** an existing state's config (uses update=False).
        - To change flags later, **re-declare** it via `define_state(...)`.

        Calling `transition(to_state)` multiple times will not alter an already-declared state's flags.
        """
        self._builder.add_or_update_state(to_state, is_initial=False, is_terminal=True, update=False)
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
        callback: Callback = None,
    ) -> StateAPI:
        """Trigger on a tool result (DEFAULT, SUCCESS, or ERROR). Optional callback runs on fire."""
        symbol = InputSymbol.for_tool(name, result)
        self._builder.add_transition(self._from, self._to, symbol, callback)
        return StateAPI(self._builder, self._from)

    def on_prompt(
        self,
        name: str,
        result: PromptResultType = PromptResultType.DEFAULT,
        callback: Callback = None,
    ) -> StateAPI:
        """Trigger on a prompt result (DEFAULT, SUCCESS, or ERROR). Optional callback runs on fire."""
        symbol = InputSymbol.for_prompt(name, result)
        self._builder.add_transition(self._from, self._to, symbol, callback)
        return StateAPI(self._builder, self._from)

    def on_resource(
        self,
        name: str,
        result: ResourceResultType = ResourceResultType.DEFAULT,
        callback: Callback = None,
    ) -> StateAPI:
        """Trigger on a resource result (DEFAULT, SUCCESS, or ERROR). Optional callback runs on fire."""
        symbol = InputSymbol.for_resource(name, result)
        self._builder.add_transition(self._from, self._to, symbol, callback)
        return StateAPI(self._builder, self._from)
    

### State Machine Definition (public facade over the internal builder)

class StateMachineDefinition:
    """Public DSL facade for declaring states and transitions.

    Users never call build methods; the server builds and validates at startup.

    **Decorator style**::

        @app.statebuilder.state("start", is_initial=True)
        def _(s):
            s.transition("next").on_tool("my_tool")

    **Fluent style**::

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
        """Declare (or update) a state and return a StateAPI to continue in fluent style.

        If the state was already declared (via this method or the decorator), this **replaces the configuration**
        (last call wins). **Note:** updating **replaces the State object** and **clears existing transitions**,
        which must be reattached.
        """
        self._builder.add_or_update_state(name, is_initial=is_initial, is_terminal=is_terminal, update=True)
        return StateAPI(self._builder, name)
    
    def state(
        self,
        name: str,
        is_initial: bool = False,
        is_terminal: bool = False,
    ) -> Callable[[F], F]:
        """Decorator for declarative state definition.

        The decorated function receives a StateAPI to attach transitions.
        If the state already exists, this **updates** its configuration (last call wins).
        **Note:** updating **replaces the State object** and **clears existing transitions**,
        which must be reattached.
        """
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
