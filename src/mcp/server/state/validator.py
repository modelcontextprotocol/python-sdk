from __future__ import annotations

from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional, Dict, Set, List, Tuple, Callable

from mcp.server.fastmcp.prompts import PromptManager
from mcp.server.fastmcp.prompts.base import Prompt
from mcp.server.fastmcp.resources import ResourceManager
from mcp.server.fastmcp.resources.base import Resource
from mcp.server.fastmcp.tools import ToolManager
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.state_machine import InputSymbol, State, Edge

logger = get_logger(__name__)


@dataclass(frozen=True)
class ValidationIssue:
    level: str  # "error" | "warning"
    message: str


class StateMachineValidator:
    """
    Validates the structure and references of a State Machine.

    Expected manager APIs:
      - tool_manager.list_tools() -> list[Tool]
      - prompt_manager.list_prompts() -> list[Prompt]
      - resource_manager.list_resources() -> list[Resource]

    Validation checks performed:
      - An explicit initial state is defined and present (hard error if missing/not found).
      - All referenced tools/prompts/resources exist in their managers (errors on missing).
      - Reachability (BFS) is computed using ONLY edges whose artifacts are available.
      - At least one **reachable terminal edge** exists from the initial region (error otherwise).
      - Unreachable states from the initial state are reported as warnings (and removed as cleanup).
      - States whose **only** available incoming edges are terminal will have their outgoing edges
        pruned as unreachable; a warning is emitted.

    Notes:
      - Reachability uses BFS and filters edges by available artifacts.
      - The notion of "terminal" is symbol-based per target state (state.terminals: list[InputSymbol]).
        Terminal states may still define outgoing edges; semantics are enforced at runtime.
      - States and edges are treated as immutable; any pruning/rewrite replaces whole State instances.
    """

    def __init__(
        self,
        *,
        states: Dict[str, State],
        initial_state: Optional[str],
        tool_manager: ToolManager | None,
        prompt_manager: PromptManager | None,
        resource_manager: ResourceManager | None,
    ) -> None:
        self.states: Dict[str, State] = states
        self.initial_state: Optional[str] = initial_state
        self.tool_manager: ToolManager | None = tool_manager
        self.prompt_manager: PromptManager | None = prompt_manager
        self.resource_manager: ResourceManager | None = resource_manager
        self.issues: List[ValidationIssue] = []

    # ----------------------------
    # main entry
    # ----------------------------
    def validate(self) -> List[ValidationIssue]:
        """Run all structural and reference checks, perform cleanup where applicable, and return issues."""
        # Hard check: initial must be defined and present
        self._check_initial_defined_and_exists()
        if any(i.level == "error" for i in self.issues):
            return self.issues

        available = self._collect_available_and_check_refs()
        self._prune_terminal_only_incoming(available)
        reachable, has_reachable_terminal = self._compute_reachable_and_terminal_flag(available)
        self._check_at_least_one_reachable_terminal(has_reachable_terminal)
        self._warn_and_prune_unreachable_states(reachable)
        return self.issues

    # ----------------------------
    # availability + references
    # ----------------------------
    def _collect_available_and_check_refs(self) -> Dict[str, Set[str]]:
        """
        Build sets of available artifact identifiers and record missing references as issues.

        Returns:
          {
            "tools": {tool_name, ...},
            "prompts": {prompt_name, ...},
            "resources": {resource_uri_str, ...},
          }
        """
        tool_refs: Set[str] = set()
        prompt_refs: Set[str] = set()
        resource_refs: Set[str] = set()

        for s in self.states.values():
            for e in s.deltas:
                sym: InputSymbol = e.input_symbol
                if sym.type == "tool":
                    tool_refs.add(sym.name)
                elif sym.type == "prompt":
                    prompt_refs.add(sym.name)
                elif sym.type == "resource":
                    resource_refs.add(sym.name)

        tool_names: Set[str] = set()
        try:
            if self.tool_manager is None:
                raise ValueError("No tool manager provided.")
            tools: List[Tool] = self.tool_manager.list_tools()
            tool_names = {t.name for t in tools}
            for missing in sorted(tool_refs - tool_names):
                self.issues.append(ValidationIssue("error", f"Referenced tool '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Tool check skipped: {e}"))

        prompt_names: Set[str] = set()
        try:
            if self.prompt_manager is None:
                raise ValueError("No prompt manager provided.")
            prompts: List[Prompt] = self.prompt_manager.list_prompts()
            prompt_names = {p.name for p in prompts}
            for missing in sorted(prompt_refs - prompt_names):
                self.issues.append(ValidationIssue("error", f"Referenced prompt '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Prompt check skipped: {e}"))

        resource_uris: Set[str] = set()
        try:
            if self.resource_manager is None:
                raise ValueError("No resource manager provided.")
            resources: List[Resource] = self.resource_manager.list_resources()
            resource_uris = {str(r.uri) for r in resources}
            for missing in sorted(resource_refs - resource_uris):
                self.issues.append(ValidationIssue("error", f"Referenced resource '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Resource check skipped: {e}"))

        return {
            "tools": tool_names,
            "prompts": prompt_names,
            "resources": resource_uris,
        }

    # ----------------------------------------------
    # prune "terminal-only incoming" (immutability-safe)
    # ----------------------------------------------
    def _prune_terminal_only_incoming(self, available: Dict[str, Set[str]]) -> None:
        """
        For any state S that has outgoing edges but **all available incoming edges** are terminal
        w.r.t. S.terminals (and S is not the initial state), its outgoing edges are unreachable.
        We replace S with a copy that has no deltas and emit a warning.
        """
        if not self.states:
            return

        initial = self.initial_state
        if initial is None:
            return  # already reported as error by the initial check

        # Build available-based incoming map: target -> list[(source, symbol)]
        incoming: Dict[str, List[Tuple[str, InputSymbol]]] = defaultdict(list)
        for src_name, src in self.states.items():
            for e in src.deltas:
                if not self._is_symbol_available(e.input_symbol, available):
                    continue
                incoming[e.to_state].append((src_name, e.input_symbol))

        for name, st in list(self.states.items()):
            if name == initial:
                continue  # initial state can be entered at startup, keep its outgoings
            if not st.deltas:
                continue  # nothing to prune
            in_list = incoming.get(name, [])
            if not in_list:
                # No available incoming → reachability step will handle it.
                continue

            # Are ALL available incoming symbols terminal for this state?
            all_terminal = all(sym in st.terminals for _, sym in in_list)
            if all_terminal:
                count = len(st.deltas)
                pruned = self._pruned_copy(st, keep=lambda _e: False)
                self._replace_state(
                    name,
                    pruned,
                    reason=f"Unreachable edges pruned: only terminal incoming edges present ({count} removed)."
                )

    # ----------------------------
    # reachability (filtered)
    # ----------------------------
    def _compute_reachable_and_terminal_flag(
        self, available: Dict[str, Set[str]]
    ) -> Tuple[Set[str], bool]:
        """
        Compute reachable states using BFS, traversing only edges whose artifacts are available.
        Also tracks whether at least one **terminal edge** is reachable from the initial region.
        """
        start = self.initial_state
        if start is None:
            return set(), False

        q: deque[str] = deque([start])
        seen: Set[str] = {start}
        found_terminal_edge = False

        while q:
            sname = q.popleft()
            s = self.states.get(sname)
            if not s:
                continue

            for e in s.deltas:
                sym = e.input_symbol
                if not self._is_symbol_available(sym, available):
                    continue

                dst = e.to_state
                dst_state = self.states.get(dst)
                if dst_state and sym in dst_state.terminals:
                    found_terminal_edge = True

                if dst in self.states and dst not in seen:
                    seen.add(dst)
                    q.append(dst)

        return seen, found_terminal_edge

    # ----------------------------
    # post checks & cleanup (immutability-safe)
    # ----------------------------
    def _check_at_least_one_reachable_terminal(self, has_reachable_terminal: bool) -> None:
        """At least one terminal state must be reachable from the initial region."""
        if not has_reachable_terminal:
            self.issues.append(ValidationIssue("error", "No reachable terminal state from initial."))

    def _warn_and_prune_unreachable_states(self, reachable: Set[str]) -> None:
        """
        Emit warnings for states not reachable from the initial state and remove them.
        Afterwards, replace remaining states with copies where edges to removed states are filtered out.
        """
        if not self.states:
            return

        # Remove unreachable states (with warnings)
        to_remove = [name for name in self.states.keys() if name not in reachable]
        if to_remove:
            for name in to_remove:
                self.issues.append(
                    ValidationIssue("warning", f"State '{name}' is unreachable from initial and was removed.")
                )
                del self.states[name]

            removed_set = set(to_remove)

            # For remaining states, remove edges targeting removed states by replacing the State
            for name, st in list(self.states.items()):
                before = len(st.deltas)
                if before == 0:
                    continue
                pruned = self._pruned_copy(st, keep=lambda e: e.to_state not in removed_set)
                after = len(pruned.deltas)
                if after < before:
                    self._replace_state(
                        name,
                        pruned,
                        reason=f"Pruned {before - after} edges targeting removed states."
                    )

    # ----------------------------
    # helpers
    # ----------------------------
    def _check_initial_defined_and_exists(self) -> None:
        """Ensure an initial state is explicitly defined and present."""
        if not self.initial_state:
            self.issues.append(ValidationIssue("error", "No initial state defined."))
            return
        if self.initial_state not in self.states:
            self.issues.append(
                ValidationIssue("error", f"Initial state '{self.initial_state}' not found.")
            )

    @staticmethod
    def _is_symbol_available(sym: InputSymbol, available: Dict[str, Set[str]]) -> bool:
        """Check artifact availability for a symbol."""
        if sym.type == "tool":
            return sym.name in available["tools"]
        if sym.type == "prompt":
            return sym.name in available["prompts"]
        if sym.type == "resource":
            return sym.name in available["resources"]
        return False  # Unknown kinds are treated as unavailable

    @staticmethod
    def _pruned_copy(state: State, *, keep: Callable[[Edge], bool]) -> State:
        """
        Create a new State instance with deltas filtered by `keep`.
        Preserves name and terminals; never mutates the original (immutability-safe).
        """
        new_deltas: List[Edge] = [e for e in state.deltas if keep(e)]
        # Defensive copies to keep outer code from mutating original lists
        return State(name=state.name, terminals=list(state.terminals), deltas=new_deltas)

    def _replace_state(self, name: str, new_state: State, *, reason: str) -> None:
        """Replace a state entry with a new instance and emit a warning describing the reason."""
        self.states[name] = new_state
        self.issues.append(ValidationIssue("warning", f"State '{name}' redefined: {reason}"))
