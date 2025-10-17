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
from typing import Callable, Optional, TypeVar, Generic

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

class StateAPI:
    """Fluent scope for a single state (input-first style).

    Entry points:
    - on_tool(name)     -> TransitionAPI[ToolResultType]
    - on_prompt(name)   -> TransitionAPI[PromptResultType]
    - on_resource(name) -> TransitionAPI[ResourceResultType]

    Each `on_*` immediately installs a DEFAULT self-transition for the given (type, name).
    Additional, result-specific transitions can be attached via `TransitionAPI.transition(...)`.

    To exit the state scope, call `done()` to return the facade.
    """

    def __init__(self, builder: _InternalStateMachineBuilder, state_name: str):
        self._builder = builder
        self._name = state_name

    def on_tool(self, name: str) -> "TransitionAPI[ToolResultType]":
        """Attach a tool by name and return a tool-typed TransitionAPI."""
        return TransitionAPI[ToolResultType](
            builder=self._builder,
            from_state=self._name,
            name=name,
            kind="tool",
            factory=InputSymbol.for_tool,
        )

    def on_prompt(self, name: str) -> "TransitionAPI[PromptResultType]":
        """Attach a prompt by name and return a prompt-typed TransitionAPI."""
        return TransitionAPI[PromptResultType](
            builder=self._builder,
            from_state=self._name,
            name=name,
            kind="prompt",
            factory=InputSymbol.for_prompt,
        )

    def on_resource(self, name: str) -> "TransitionAPI[ResourceResultType]":
        """Attach a resource by name and return a resource-typed TransitionAPI."""
        return TransitionAPI[ResourceResultType](
            from_state=self._name,
            name=name,
            kind="resource",
            builder=self._builder,
            factory=InputSymbol.for_resource,
        )

    def done(self) -> "StateMachineDefinition":
        """Return the facade to continue the fluent chain (same builder instance)."""
        return StateMachineDefinition.from_builder(self._builder)


class TransitionAPI(Generic[RT]):
    """Fluent scope for transitions of a concrete (type, name) binding within the current state.

    This class is generic over the result type `RT`, which is fixed by the entry point:
    - `on_tool(...)`     → RT = ToolResultType
    - `on_prompt(...)`   → RT = PromptResultType
    - `on_resource(...)` → RT = ResourceResultType

    API surface:
    - transition(to_state, result, effect=None)  → attach an exact-match edge
    - transaction(prepare, payload=None)         → register a transaction for this state and tool/prompt/resource
    - end()                                      → return to the StateAPI (state scope)
    """

    def __init__(
        self,
        from_state: str,
        name: str,
        kind: str,
        builder: _InternalStateMachineBuilder,
        factory: Callable[[str, RT], InputSymbol],
    ):
        self._builder = builder
        self._from = from_state
        self._name = name
        self._kind = kind           # tool / prompt / resource (TxKind)
        self._factory = factory     # InputSymbol factory for the specific result type

    def transition(
        self,
        to_state: str,
        result: RT,
        effect: Callback = None,
    ) -> "TransitionAPI[RT]":
        """Attach a transition for (type, name, result) from the current state to `to_state`.

        **effect**:
            Optional side-effect invoked *after* the state update when this edge is taken.
            It is not part of the state machine’s semantics: the machine does not observe
            its return value and does not rely on it for determinism. Keep business logic
            out of effects—use them only for things like logging, metrics, or event-sourcing.
        """
        # Build a typed input symbol with the provided result enum and attach the edge.
        symbol = self._factory(self._name, result)
        self._builder.add_transition(self._from, to_state, symbol, effect)
        return self

    def transaction(
        self,
        provider: TransactionPayloadProvider,
    ) -> "TransitionAPI[RT]":
        """Register a transaction for this state and tool/prompt/resource.

        What it is:
            A client-side request executed under a transaction boundary so state-dependent
            changes don’t “stick” if the tool/prompt/resource fails. This lets the runtime
            keep client and server in sync and preserves the state machine’s determinism.

        How it runs:
            - PREPARE happens *before* the tool/prompt/resource is executed.
            The `provider` can be a static payload or a callable; callables may enrich the
            payload using request context/lifespan data.
            - On success, the transaction is COMMITed.
            - On failure/exception, it is ABORTed (no commit).

        Important:
            - Don’t assume data written by the same tool/prompt/resource is available to the
            `provider`—prepare runs first. If you need data in the payload, add a preceding
            step that writes it to context.
            - You can think of this as making the operation deterministic over the pair
            (operation, transaction). Multiple providers may be registered; all are processed
            in order.
            - Correct behavior depends on client capabilities and proper client handlers.
        """
        key: TxKey = (self._from, self._kind, self._name)
        self._builder.add_transaction(key, provider)
        return self
    
    def end(self) -> "StateAPI":
        """Return to the state scope to continue chaining within the same state."""
        return StateAPI(self._builder, self._from)


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
