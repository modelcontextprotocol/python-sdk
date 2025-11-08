from __future__ import annotations

from typing import Callable, Optional, TypeVar, Generic, Literal, Dict, List

from mcp.server.fastmcp.prompts import PromptManager
from mcp.server.fastmcp.resources import ResourceManager
from mcp.server.fastmcp.tools import ToolManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.state_machine import (
    InputSymbol,
    State,
    StateMachine,
    Edge,  # formerly DeltaEdge
)

from mcp.server.state.types import (
    Callback,
    PromptResultType,
    ResourceResultType,
    ToolResultType,
)
from mcp.server.state.validator import StateMachineValidator, ValidationIssue
from mcp.server.state.transaction.manager import TransactionManager, TxKey
from mcp.server.state.transaction.types import TransactionPayloadProvider


logger = get_logger(f"{__name__}.StateMachineBuilder")

# ----------------------------
# Helper Types
# ----------------------------

F  = TypeVar("F", bound=Callable[["StateAPI"], None])  # Decorator receives a StateAPI
RT = TypeVar("RT", ToolResultType, PromptResultType, ResourceResultType)  # Result-type generic

# ----------------------------
# Internal Builder
# ----------------------------

class _InternalStateMachineBuilder:
    """Private, build-only implementation.

    Collects states and edges during DSL usage and produces either a
    global (process-wide) or session-scoped machine. Validation is invoked
    from build methods, never by users directly. This class must not be
    accessed from user code.
    """

    def __init__(
        self,
        tool_manager: ToolManager | None,
        resource_manager: ResourceManager | None,
        prompt_manager: PromptManager | None,
        tx_manager: TransactionManager | None,
    ):
        """Capture external managers (for validation) and initialize buffers."""
        self._states: Dict[str, State] = {}
        self._initial: Optional[str] = None
        self._tool_manager = tool_manager
        self._resource_manager = resource_manager
        self._prompt_manager = prompt_manager
        self._tx_manager = tx_manager

    def add_state(self, name: str, *, is_initial: bool = False) -> None:
        """Declare a state if missing; optionally mark as initial (first-wins; later attempts warn & are ignored)."""
        exists = name in self._states
        if not exists:
            # Create with empty edge list and empty terminal-symbol list.
            self._states[name] = State(name=name, deltas=[], terminals=[])
        else:
            logger.debug("State '%s' already exists; keeping configuration.", name)

        if is_initial:
            if self._initial is None or self._initial == name:
                self._initial = name
            else:
                logger.warning(
                    "Initial state already set to '%s'; ignoring attempt to set '%s' as initial.",
                    self._initial, name
                )

    def add_terminal(self, state_name: str, symbol: InputSymbol) -> None:
        """Append a terminal symbol to a state's terminal set (duplicates are ignored)."""
        st = self._states.get(state_name)
        if st is None:
            raise KeyError(f"State '{state_name}' not defined")
        if symbol not in st.terminals:
            st.terminals.append(symbol)
        else:
            logger.debug("Terminal symbol %r already present on state '%s'; ignored.", symbol, state_name)

    def add_edge(
        self,
        from_state: str,
        to_state: str,
        symbol: InputSymbol,
        effect: Callback | None = None,
    ) -> None:
        """Add an edge δ(q, a) = q'; ensure target exists; warn & ignore on duplicates/ambiguities.

        Behavior:
        - Ensures the *target* state exists (no flags are modified for existing states).
        - Duplicate (same symbol & same target) → warn and ignore.
        - Ambiguous (same symbol mapped to a different target from the same source) → warn and ignore.
        """
        if from_state not in self._states:
            raise KeyError(f"State '{from_state}' not defined")

        # Ensure target state exists (placeholder if needed).
        if to_state not in self._states:
            self.add_state(to_state, is_initial=False)
            logger.debug("Created placeholder state '%s' for edge target.", to_state)

        src = self._states[from_state]
        new_edge = Edge(to_state=to_state, input_symbol=symbol, effect=effect)

        # duplicate?
        if any(e.input_symbol == symbol and e.to_state == to_state for e in src.deltas):
            logger.warning("Edge %r already exists; new definition ignored.", new_edge)
            return

        # ambiguous?
        if any(e.input_symbol == symbol and e.to_state != to_state for e in src.deltas):
            logger.warning(
                "Ambiguous edge on %s from '%s': existing target differs; new definition ignored.",
                symbol, from_state
            )
            return

        src.deltas.append(new_edge)

    def add_transaction(
        self,
        key: TxKey,
        provider: TransactionPayloadProvider,
    ) -> None:
        """Register a payload provider for the given TxKey (multiple registrations allowed)."""
        state_name = key[0]
        if state_name not in self._states:
            raise KeyError(f"State '{state_name}' not defined")
        if self._tx_manager is not None:
            self._tx_manager.register(key=key, provider=provider)
            logger.debug("Registered transaction provider for key=%s", key)

    def build(self) -> StateMachine:
        """Build a global machine (single current state for the process)."""
        self._validate()
        initial = self._initial or next(iter(self._states))
        return StateMachine(initial_state=initial, states=self._states)
    
    # ----------------------------
    # Validation
    # ----------------------------

    def _validate(self) -> None:
        """Run structural and reference checks (errors abort; warnings are logged)."""
        issues: List[ValidationIssue] = StateMachineValidator(
            states=self._states,
            initial_state=self._initial,
            tool_manager=self._tool_manager,
            prompt_manager=self._prompt_manager,
            resource_manager=self._resource_manager,
        ).validate()

        for i in issues:
            if i.level == "warning":
                logger.warning("State machine validation warning: %s", i.message)

        errors = [i.message for i in issues if i.level == "error"]
        if errors:
            raise ValueError("Invalid state machine:\n- " + "\n- ".join(errors))

# ----------------------------
# Public API DSL
# ----------------------------

class BaseTransitionAPI(Generic[RT]):
    """
    Fluent scope for transitions (internally *edges*) of a concrete (kind, name) binding within the current state.

    Outcome-first API:
      - on_success(to_state, *, terminal=False, effect=None, transaction=None) -> Self
      - on_error(to_state,   *, terminal=False, effect=None, transaction=None) -> Self
      - build_edge() -> StateAPI  (return to state scope)

    Transactions:
      - A `transaction` is *prepared before* entering the transition scope or executing the op.
      - If PREPARE fails: hard stop. No op execution. No transition emission.
      - After execution, the transition scope emits an outcome (SUCCESS or ERROR).
      - The matching outcome's transaction is **COMMIT**ted; the opposite outcome is **ABORT**ed.
      - Transactions are registered per **(state, kind, name, outcome)**.

    Effects:
      - `effect` runs *after* the state update when this edge is taken.
      - Effects are non-semantic (logging/metrics/etc.); failures are warned and ignored.

    Subclasses pin the SUCCESS/ERROR enums and the InputSymbol factory for their result type.
    """

    # subclass contract
    _SUCCESS_ENUM: RT                               # e.g. ToolResultType.SUCCESS
    _ERROR_ENUM: RT                                 # e.g. ToolResultType.ERROR
    _factory: Callable[[str, RT], InputSymbol]      # e.g. InputSymbol.for_tool
    _kind: Literal["tool", "prompt", "resource"]

    def __init__(self, builder: _InternalStateMachineBuilder, from_state: str, name: str):
        """Bind the builder, the source state name, and the bound (kind-specific) binding name."""
        self._builder = builder
        self._from = from_state
        self._name = name

    def on_success(
        self,
        to_state: str,
        *,
        terminal: bool = False,
        effect: Optional[Callback] = None,
        transaction: Optional[TransactionPayloadProvider] = None,
    ) -> BaseTransitionAPI[RT]:
        """Attach the SUCCESS transition (edge); optionally mark target terminal & register a transaction."""
        symbol = self._factory(self._name, self._SUCCESS_ENUM)
        self._builder.add_edge(self._from, to_state, symbol, effect)
        if terminal:
            self._builder.add_terminal(to_state, symbol)
        if transaction is not None:
            key: TxKey = (self._from, self._kind, self._name, "success")
            self._builder.add_transaction(key, transaction)
        return self

    def on_error(
        self,
        to_state: str,
        *,
        terminal: bool = False,
        effect: Optional[Callback] = None,
        transaction: Optional[TransactionPayloadProvider] = None,
    ) -> BaseTransitionAPI[RT]:
        """Attach the ERROR transition (edge); optionally mark target terminal & register a transaction."""
        symbol = self._factory(self._name, self._ERROR_ENUM)
        self._builder.add_edge(self._from, to_state, symbol, effect)
        if terminal:
            self._builder.add_terminal(to_state, symbol)
        if transaction is not None:
            key: TxKey = (self._from, self._kind, self._name, "error")
            self._builder.add_transaction(key, transaction)
        return self

    def build_edge(self) -> "StateAPI":
        """Return to the state scope to continue chaining within the same state."""
        return StateAPI(self._builder, self._from)


class TransitionToolAPI(BaseTransitionAPI["ToolResultType"]):
    """Tool-typed transition scope. Use `on_success`, `on_error`, then `build_tool()` or `build_edge()` to return."""
    _SUCCESS_ENUM = ToolResultType.SUCCESS
    _ERROR_ENUM   = ToolResultType.ERROR
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

    To exit the state scope, call `build_state()` to return the DSL facade.
    """

    def __init__(self, builder: _InternalStateMachineBuilder, state_name: str):
        """Bind the internal builder and the current state name for fluent chaining."""
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


class StateMachineDefinition:
    """Public DSL facade for declaring states and edges.

    Users never call build methods; the server builds and validates at startup.

    **Decorator style**::

        @app.statebuilder.state("start", is_initial=True)
        def _(s: StateAPI):
            s.on_tool("login") 
             .on_success("home", terminal=True)
             .build_edge()
             .on_tool("alt_login")
             .on_error("start")
             .build_edge()

    **Fluent style**::

        app.statebuilder
            .define_state("start", is_initial=True)
            .on_prompt("confirm")
                .on_success("end", terminal=True)
                .build_edge()
            .on_tool("help")
                .on_success("faq")
                .build_edge()
    """

    def __init__(
        self,
        tool_manager: ToolManager | None,
        resource_manager: ResourceManager | None,
        prompt_manager: PromptManager | None,
        tx_manager: TransactionManager | None,
    ):
        """Create a new facade over a fresh internal builder."""
        self._builder = _InternalStateMachineBuilder(tool_manager, resource_manager, prompt_manager, tx_manager)

    @classmethod
    def from_builder(cls, builder: _InternalStateMachineBuilder) -> "StateMachineDefinition":
        """Wrap an existing internal builder (no copy)."""
        obj = cls.__new__(cls)
        obj._builder = builder
        return obj

    def define_state(self, name: str, is_initial: bool = False) -> StateAPI:
        """Declare a state (no update semantics) and return a StateAPI to continue in fluent style."""
        self._builder.add_state(name, is_initial=is_initial)
        return StateAPI(self._builder, name)

    def state(self, name: str, is_initial: bool = False) -> Callable[[F], F]:
        """Decorator for declarative state definition (same semantics as `define_state`)."""
        def decorator(func: F) -> F:
            state_api: StateAPI = self.define_state(name, is_initial)
            func(state_api)
            return func
        return decorator

    def _to_internal_builder(self) -> _InternalStateMachineBuilder:
        """Internal plumbing only (server builds/validates after all registrations)."""
        return self._builder
