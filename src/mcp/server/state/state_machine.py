from dataclasses import dataclass, field
from typing import Optional, TypedDict, Callable, TypeVar
from collections import defaultdict
from enum import Enum

import asyncio, inspect

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.fastmcp.tools import ToolManager  # Der native ToolManager

logger = get_logger(__name__)

# ----------- Helper Types -----------

Callback = Callable[[], None]

F = TypeVar("F", bound=Callable[["StateAPI"], None])

class AvailableInputs(TypedDict):
    tools: set[str]
    resources: set[str]
    prompts: set[str]

# ----------- Public Enums & Constants -----------

DEFAULT_QUALIFIER = "default" # Bildet alle ResultTypes ab

class ToolResultType(str, Enum):
    DEFAULT = DEFAULT_QUALIFIER
    SUCCESS = "success"
    ERROR = "error"

class PromptResultType(str, Enum):
    DEFAULT = DEFAULT_QUALIFIER
    SUCCESS = "success"
    ERROR = "error"

class ResourceResultType(str, Enum):
    DEFAULT = DEFAULT_QUALIFIER
    SUCCESS = "success"
    ERROR = "error"

# ----------- Internal Structures -----------

@dataclass(frozen=True) # (frozen=true) Kann nicht verändert werden
class InputSymbol:
    type: str
    name: str
    qualifier: str

    def __str__(self) -> str:
        return f"{self.type}:{self.name}:{self.qualifier}"

    @classmethod
    def for_tool(cls, name: str, result: ToolResultType) -> "InputSymbol":
        return cls("tool", name, result.value)

    @classmethod
    def for_prompt(cls, name: str, result: PromptResultType) -> "InputSymbol":
        return cls("prompt", name, result.value)

    @classmethod
    def for_resource(cls, name: str, result: ResourceResultType) -> "InputSymbol":
        return cls("resource", name, result.value)

@dataclass(frozen=True)
class Transition:
    to_state: str
    input_symbols: list[InputSymbol] = field(default_factory=list[InputSymbol])
    callback: Optional[Callback] = None # Optionale Callback Logik bei Übergang

@dataclass(frozen=True)
class State:
    name: str
    is_initial: bool = False
    is_terminal: bool = False
    transitions: list[Transition] = field(default_factory=list[Transition])

# ----------- Final Runtime State Machine -----------

class StateMachine:
    def __init__(self, initial_state: str, states: dict[str, State]):
        self._states = states
        self._initial = initial_state
        self._current = initial_state

    @property
    def current_state(self) -> str:
        return self._current
    
    def get_available_inputs(self) -> AvailableInputs:
        inputs: dict[str, set[str]] = defaultdict(set)

        for transition in self._states[self.current_state].transitions:
            for symbol in transition.input_symbols:
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
            """Findet eine passende Transition, führt Callback aus
            und setzt den neuen Zustand.  Rückgabe True = erledigt."""
            for tr in state.transitions:
                if symbol in tr.input_symbols:
                    self._current = tr.to_state
                    if tr.callback:
                        coro = tr.callback()
                        if inspect.isawaitable(coro):   # async? → fire & forget
                            asyncio.create_task(coro)
                    return True
            return False

    def transition(self, input_symbol: InputSymbol) -> None:
        state = self._states.get(self._current)
        if state is None:                       # State validieren
            raise RuntimeError(f"State '{self._current}' not defined")

        # zuerst reguläres Symbol versuchen, dann Fallback
        if self._apply(state, input_symbol):
            return

        fallback = InputSymbol(
            type=input_symbol.type,
            name=input_symbol.name,
            qualifier=DEFAULT_QUALIFIER,
        )
        self._apply(state, fallback)  # lässt Ausnahme o. Ä. außen vor: keine Treffer → no‑op

# ----------- Internal Builder -----------

class _InternalStateMachineBuilder:
    def __init__(self, tool_manager: ToolManager):
        self._states: dict[str, State] = {}
        self._initial: Optional[str] = None
        self._tool_manager = tool_manager

    def add_state(self, name: str, is_initial: bool=False, is_terminal: bool=False):
        if name not in self._states:
            self._states[name] = State(name=name, is_initial=is_initial, is_terminal=is_terminal)
            if is_initial:
                self._initial = name

    def add_transition(self, from_state: str, to_state: str, symbols: list[InputSymbol], callback: Optional[Callback] = None):
        state = self._states[from_state]
        state.transitions.append(Transition(to_state=to_state, input_symbols=symbols, callback=callback))

    def build(self) -> StateMachine:
        self._validate()
        initial = self._initial or next(iter(self._states))
        machine = StateMachine(initial_state=initial, states=self._states)
        return machine

    def _validate(self):
        # TODO: Strukturvalidierung
        # - Jeder Zustand muss erreichbar sein (optional)
        # - Es darf nur einen initialen Zustand geben
        # - Es gibt mind. einen erreichbaren Terminal-Zustand
        # - Terminal-Zustände dürfen keine Transitionen haben (optional)

        # TODO: Tool-, Prompt-, Resource-Referenzen gegen Manager prüfen
        # self._tool_manager.get_tool(name) # z. B.
        pass

# ----------- Public API DSL -----------

class StateAPI:
    def __init__(self, builder: _InternalStateMachineBuilder, state_name: str):
        self._builder = builder
        self._name = state_name

    def transition(self, to_state: str) -> "TransitionAPI": # Vorwärtsrefrenz -> "StringLiteral":
        self._builder.add_state(to_state)
        return TransitionAPI(self._builder, self._name, to_state)

    def done(self) -> "StateMachineDefinition":
        # Wir geben dieselbe Builder‑Instanz zurück, nur wieder “verpackt”
        return StateMachineDefinition.from_builder(self._builder)

class TransitionAPI:
    def __init__(self, builder: _InternalStateMachineBuilder, from_state: str, to_state: str):
        self._builder = builder
        self._from = from_state
        self._to = to_state

    def on_tool(self, name: str, result: ToolResultType = ToolResultType.DEFAULT, callback: Optional[Callback] = None) -> StateAPI: 
        symbol = InputSymbol.for_tool(name, result)
        self._builder.add_transition(self._from, self._to, [symbol], callback)
        return StateAPI(self._builder, self._from)

    def on_prompt(self, name: str, result: PromptResultType = PromptResultType.DEFAULT, callback: Optional[Callback] = None) -> StateAPI:
        symbol = InputSymbol.for_prompt(name, result)
        self._builder.add_transition(self._from, self._to, [symbol], callback)
        return StateAPI(self._builder, self._from)

    def on_resource(self, name: str, result: ResourceResultType = ResourceResultType.DEFAULT, callback: Optional[Callback] = None) -> StateAPI:
        symbol = InputSymbol.for_resource(name, result)
        self._builder.add_transition(self._from, self._to, [symbol], callback)
        return StateAPI(self._builder, self._from)

# ----------- State Machine Definition Fassade -----------

class StateMachineDefinition:
    def __init__(self, tool_manager: ToolManager):
        self._builder = _InternalStateMachineBuilder(tool_manager)

    @classmethod
    def from_builder(cls, builder: _InternalStateMachineBuilder) -> "StateMachineDefinition":
        obj = cls.__new__(cls)        # keinen neuen Builder anlegen!
        obj._builder = builder
        return obj

    def define_state(self, name: str, is_initial: bool=False, is_terminal: bool =False) -> StateAPI:
        # Gibt nichts zurück
        self._builder.add_state(name, is_initial, is_terminal)
        return StateAPI(self._builder, name)

    def state(
        self,
        name: str,
        is_initial: bool = False,
        is_terminal: bool = False,
    ) -> Callable[[F], F]:
        """Decorator für deklarative Zustandsdefinition."""
        def decorator(func: F) -> F:
            state_api: StateAPI = self.define_state(name, is_initial, is_terminal)
            func(state_api)
            return func
        return decorator    

    def _to_internal_builder(self) -> _InternalStateMachineBuilder:
        return self._builder


