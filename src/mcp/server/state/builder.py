"""
Finite-state machine builder (public DSL facade over a private builder).

Purpose
-------
Provide a small DSL to declare states and transitions, then build and validate
a deterministic state machine at server startup. The public API exposes:

- StateMachineDefinition (facade)
- StateAPI (fluent state scope)
- TransitionAPI (fluent transition scope; generic over the result type)

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
from typing import Callable, Optional, TypeVar, Generic, Literal

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
from mcp.server.state.transaction.manager import TransactionManager, TxKey
from mcp.server.state.transaction.types import TransactionPayloadProvider


logger = get_logger(f"{__name__}.StateMachineBuilder")

### Helper Types

F = TypeVar("F", bound=Callable[["StateAPI"], None])  # Decorator receives a StateAPI
RT = TypeVar("RT", ToolResultType, PromptResultType, ResourceResultType)  # Result-type generic

### Internal Builder

class _InternalStateMachineBuilder:
    """Private, build-only implementation.

    Collects states and transitions during DSL usage and produces either a
    global (process-wide) or session-scoped machine. Validation is invoked
    from build methods, never by users directly. This class must not be
    accessed from user code.
    """

    def __init__(
            self, tool_manager: ToolManager | None,
            resource_manager: ResourceManager | None, 
            prompt_manager: PromptManager | None,
            tx_manager: TransactionManager | None
            ):
        self._states: dict[str, State] = {}
        self._initial: Optional[str] = None
        self._tool_manager = tool_manager
        self._resource_manager = resource_manager
        self._prompt_manager = prompt_manager
        self._tx_manager = tx_manager

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
        effect: Callback = None,
    ) -> None:
        """Add a transition; ensure target state exists; warn and ignore on duplicates or ambiguities.

        Behavior:
        - Ensures the *target* state exists as a terminal placeholder (no flag updates for existing states).
        - Duplicate (exact same Transition object) → warn and ignore.
        - Ambiguous (same input symbol mapped to a different target) → warn and ignore.
        """
        # Ensure source state exists (builder contracts expect states to be declared up front)
        if from_state not in self._states:
            raise KeyError(f"State '{from_state}' not defined")

        # Ensure target state exists as terminal placeholder (no update for existing)
        if to_state not in self._states:
            # Create target with terminal=True by default (placeholder)
            self.add_or_update_state(to_state, is_initial=False, is_terminal=True, update=False)
            logger.debug("Created placeholder terminal state '%s' for transition target.", to_state)

        state = self._states[from_state]
        new_tr = Transition(to_state=to_state, input_symbol=symbol, effect=effect)

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

    def add_transaction(
        self,
        key: TxKey,
        provider: TransactionPayloadProvider,
    ) -> None:
        """Register a payload provider for the given TxKey.

        - The source state must exist → otherwise raise KeyError.
        - Multiple registrations are allowed (providers are appended).
        """
        state = key[0]
        if state not in self._states:
            raise KeyError(f"State '{state}' not defined")

        if self._tx_manager is not None:
            self._tx_manager.register(key=key, provider=provider)
            logger.debug("Registered transaction provider for key=%s", key)

    def build(self, *, context_resolver: ContextResolver = None) -> StateMachine:
        """Build a global machine (single current state for the process)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        return StateMachine(
            initial_state=initial,
            states=self._states,
            context_resolver=context_resolver
        )

    def build_session_scoped(self, *, context_resolver: ContextResolver = None) -> SessionScopedStateMachine:
        """Build a session-scoped machine (state tracked per session id, with global fallback)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        return SessionScopedStateMachine(
            initial_state=initial,
            states=self._states,
            context_resolver=context_resolver
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

class BaseTransitionAPI(Generic[RT]):
    """
    Fluent scope for transitions of a concrete (kind, name) binding within the current state.

    Outcome-first API
    -----------------
      - on_success(to_state, effect=None, transaction=None) -> Self
      - on_error(to_state, effect=None, transaction=None)   -> Self
      - build_edge() -> StateAPI  (return to state scope)

    Transactions
    ------------
      - A `transaction` is *prepared before* entering the transition scope or executing the op.
      - If PREPARE fails: hard stop. No op execution. No transition emission.
      - After execution, the transition scope emits an outcome (SUCCESS or ERROR).
      - The matching outcome’s transaction is **COMMIT**ted; the opposite outcome is **ABORT**ed.
      - Transactions are registered per **(state, kind, name, outcome)**.

    Effects
    -------
      - `effect` runs *after* the state update when this edge is taken.
      - Effects are non-semantic (logging/metrics/etc.); failures are warned and ignored.

    Subclasses pin the SUCCESS/ERROR enums and the InputSymbol factory for their result type.
    """

    # subclass contract
    _SUCCESS_ENUM: RT                               # e.g. ToolResultType.SUCCESS
    _ERROR_ENUM: RT                                 # e.g. ToolResultType.ERROR
    _factory: Callable[[str, RT], "InputSymbol"]    # e.g. InputSymbol.for_tool
    _kind: Literal["tool", "prompt", "resource"]

    def __init__(self, builder: "_InternalStateMachineBuilder", from_state: str, name: str):
        self._builder = builder
        self._from = from_state
        self._name = name

    def on_success(
        self,
        to_state: str,
        effect: Optional[Callback] = None,
        transaction: Optional[TransactionPayloadProvider] = None,
    ) -> "BaseTransitionAPI[RT]":
        """Attach the SUCCESS edge; optionally register a SUCCESS-qualified transaction. Returns Self for fluent chaining."""
        symbol = self._factory(self._name, self._SUCCESS_ENUM)
        self._builder.add_transition(self._from, to_state, symbol, effect)
        if transaction is not None:
            key: "TxKey" = (self._from, self._kind, self._name, "success")
            self._builder.add_transaction(key, transaction)
        return self

    def on_error(
        self,
        to_state: str,
        effect: Optional[Callback] = None,
        transaction: Optional[TransactionPayloadProvider] = None,
    ) -> "BaseTransitionAPI[RT]":
        """Attach the ERROR edge; optionally register an ERROR-qualified transaction. Returns Self for fluent chaining."""
        symbol = self._factory(self._name, self._ERROR_ENUM)
        self._builder.add_transition(self._from, to_state, symbol, effect)
        if transaction is not None:
            key: "TxKey" = (self._from, self._kind, self._name, "error")
            self._builder.add_transaction(key, transaction)
        return self

    def build_edge(self) -> "StateAPI":
        """Return to the state scope to continue chaining within the same state."""
        return StateAPI(self._builder, self._from)


class TransitionToolAPI(BaseTransitionAPI["ToolResultType"]):
    """Tool-typed transition scope. Use `on_success`, `on_error`, then `build_tool()` or `build_edge()` to return."""
    _SUCCESS_ENUM = ToolResultType.SUCCESS  
    _ERROR_ENUM   = ToolResultType.ERROR    # 
    _factory      = staticmethod(InputSymbol.for_tool)
    _kind         = "tool"

    def build_tool(self) -> "StateAPI":
        """Return to the state scope to continue attaching bindings for this state."""
        return self.build_edge()


class TransitionPromptAPI(BaseTransitionAPI["PromptResultType"]):
    """Prompt-typed transition scope. Use `on_success`, `on_error`, then `build_prompt()` or `build_edge()` to return."""
    _SUCCESS_ENUM = PromptResultType.SUCCESS
    _ERROR_ENUM   = PromptResultType.ERROR 
    _factory      = staticmethod(InputSymbol.for_prompt)
    _kind         = "prompt"

    def build_prompt(self) -> "StateAPI":
        """Return to the state scope to continue attaching bindings for this state."""
        return self.build_edge()


class TransitionResourceAPI(BaseTransitionAPI["ResourceResultType"]):
    """Resource-typed transition scope. Use `on_success`, `on_error`, then `build_resource()` or `build_edge()` to return."""
    _SUCCESS_ENUM = ResourceResultType.SUCCESS
    _ERROR_ENUM   = ResourceResultType.ERROR
    _factory      = staticmethod(InputSymbol.for_resource)
    _kind         = "resource"

    def build_resource(self) -> "StateAPI":
        """Return to the state scope to continue attaching bindings for this state."""
        return self.build_edge()


class StateAPI:
    """Fluent scope for a single state (input-first style).

    Entry points (return kind-specific Transition APIs):
      - on_tool(name)     → TransitionToolAPI
      - on_prompt(name)   → TransitionPromptAPI
      - on_resource(name) → TransitionResourceAPI

    To exit the state scope, call `buildState()` to return the DSL facade.
    """

    def __init__(self, builder: _InternalStateMachineBuilder, state_name: str):
        self._builder = builder
        self._name = state_name

    def on_tool(self, name: str) -> TransitionToolAPI:
        """Attach a tool by name and return a tool-typed Transition API."""
        return TransitionToolAPI(builder=self._builder, from_state=self._name, name=name)

    def on_prompt(self, name: str) -> TransitionPromptAPI:
        """Attach a prompt by name and return a prompt-typed Transition API."""
        return TransitionPromptAPI(builder=self._builder, from_state=self._name, name=name)

    def on_resource(self, name: str) -> TransitionResourceAPI:
        """Attach a resource by name and return a resource-typed Transition API."""
        return TransitionResourceAPI(builder=self._builder, from_state=self._name, name=name)

    def build_state(self) -> "StateMachineDefinition":
        """Return the facade to continue the fluent chain (same builder instance)."""
        return StateMachineDefinition.from_builder(self._builder)


### State Machine Definition (public facade over the internal builder)

class StateMachineDefinition:
    """Public DSL facade for declaring states and transitions.

    Users never call build methods; the server builds and validates at startup.

    **Decorator style**::

        @app.statebuilder.state("start", is_initial=True)
        def _(s: StateAPI):
            # Chain multiple bindings: tool -> transition, then another tool.
            s.on_tool("login") \
             .transition("home", ToolResultType.SUCCESS) \
             .end() \
             .on_tool("alt_login") \
             .transition("alt_home", ToolResultType.SUCCESS)

    **Fluent style**::

        app.statebuilder \
            .define_state("start", is_initial=True) \
            .on_prompt("confirm") \
                .transition("end", PromptResultType.SUCCESS) \
                .end() \
            .on_tool("help") \
                .transition("faq", ToolResultType.SUCCESS)
    """

    def __init__(
            self, 
            tool_manager: ToolManager | None, 
            resource_manager: ResourceManager | None, 
            prompt_manager: PromptManager | None,
            tx_manager: TransactionManager | None
        ):
        self._builder = _InternalStateMachineBuilder(tool_manager, resource_manager, prompt_manager, tx_manager)

    @classmethod
    def from_builder(cls, builder: _InternalStateMachineBuilder) -> "StateMachineDefinition":
        """Wrap an existing internal builder (no copy)."""
        obj = cls.__new__(cls)
        obj._builder = builder
        return obj

    def define_state(self, name: str, is_initial: bool = False, is_terminal: bool = False) -> StateAPI:
        """Declare (or update) a state and return a StateAPI to continue in fluent style.

        If the state already exists, this **replaces the configuration** (last call wins).
        Updating **replaces the State object** and **clears existing transitions**, which must be reattached.
        """
        self._builder.add_or_update_state(name, is_initial=is_initial, is_terminal=is_terminal, update=True)
        return StateAPI(self._builder, name)

    def state(
        self,
        name: str,
        is_initial: bool = False,
        is_terminal: bool = False,
    ) -> Callable[[F], F]:
        """Decorator for declarative state definition (same semantics as `define_state`)."""
        def decorator(func: F) -> F:
            state_api: StateAPI = self.define_state(name, is_initial, is_terminal)
            func(state_api)
            return func
        return decorator

    def _to_internal_builder(self) -> _InternalStateMachineBuilder:
        """Internal plumbing only (server builds/validates after all registrations)."""
        return self._builder
