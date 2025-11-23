from __future__ import annotations

from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional, Dict, Set, List, Tuple

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

    Architecture (updated):
      - Q (states): Dict[str, State] with `State.terminals: list[str]` of symbol-ids.
      - Σ (input symbols): provided as `symbols_by_id: Dict[id, InputSymbol]`.
      - δ (edges): global `List[Edge]` with (from_state, to_state, symbol_id).

    Expected manager APIs:
      - tool_manager.list_tools() -> list[Tool]
      - prompt_manager.list_prompts() -> list[Prompt]
      - resource_manager.list_resources() -> list[Resource]

    Validation checks performed:

    Structural checks (no mutation):
      - An explicit initial state is defined and present.
      - All edges reference known symbol-ids (present in Σ).
      - All referenced tools/prompts/resources exist in their managers.
      - Reachability (BFS) is computed using ONLY edges whose artifacts are available.
      - At least one **reachable terminal edge** exists from the initial region.

    Post-checks (cleanup/pruning):
      - Unreachable states from the initial state are reported as warnings and removed.
      - Edges referencing removed states are pruned (single warning with counts).
      - States whose **only available incoming edges** are terminal will have their outgoing
        edges pruned as unreachable (warning).

    Notes:
      - Terminality is symbol-id based: `symbol_id in target_state.terminals`.
      - Reachability ignores edges whose artifacts are not available.
      - The validator mutates the provided `states`/`edges` for cleanup (immutability of
        State instances is preserved; we replace collections wholesale).
    """

    def __init__(
        self,
        *,
        states: Dict[str, State],
        edges: List[Edge],
        symbols_by_id: Dict[str, InputSymbol],
        initial_state: Optional[str],
        tool_manager: ToolManager | None,
        prompt_manager: PromptManager | None,
        resource_manager: ResourceManager | None,
    ) -> None:
        self.states: Dict[str, State] = states
        self.edges: List[Edge] = edges
        self.symbols_by_id: Dict[str, InputSymbol] = symbols_by_id
        self.initial_state: Optional[str] = initial_state
        self.tool_manager: ToolManager | None = tool_manager
        self.prompt_manager: PromptManager | None = prompt_manager
        self.resource_manager: ResourceManager | None = resource_manager
        self.issues: List[ValidationIssue] = []

        # cached across phases
        self._available: Optional[Dict[str, Set[str]]] = None
        self._reachable: Set[str] = set()
        self._has_reachable_terminal: bool = False

    # ----------------------------
    # main entry
    # ----------------------------
    def validate(self) -> List[ValidationIssue]:
        """Run structural checks, then post-check cleanup, and return issues."""
        self._structural_checks()
        if any(i.level == "error" for i in self.issues):
            return self.issues

        self._post_checks()
        return self.issues

    # ----------------------------
    # structural checks (no mutation)
    # ----------------------------
    def _structural_checks(self) -> None:
        """Aggregate all structural validations without mutating states/edges."""
        # Initial must be defined and present
        if not self.initial_state:
            self.issues.append(ValidationIssue("error", "No initial state defined."))
            return
        if self.initial_state not in self.states:
            self.issues.append(
                ValidationIssue("error", f"Initial state '{self.initial_state}' not found.")
            )
            return

        # Edge → Symbol existence
        unknown_symbol_ids = sorted({e.symbol_id for e in self.edges if e.symbol_id not in self.symbols_by_id})
        for sid in unknown_symbol_ids:
            self.issues.append(ValidationIssue("error", f"Edge references unknown symbol-id '{sid}'."))

        # Collect availability and reference errors/warnings
        self._available = self._collect_available_and_check_refs()

        # Reachability & terminal presence under availability constraints
        self._reachable, self._has_reachable_terminal = self._compute_reachable_and_terminal_flag(self._available)
        if not self._has_reachable_terminal:
            self.issues.append(ValidationIssue("error", "No reachable terminal state from initial."))

    # ----------------------------
    # post checks (cleanup/pruning)
    # ----------------------------
    def _post_checks(self) -> None:
        """Perform cleanup: prune unreachable and terminal-only-incoming cases."""
        if not self.states:
            return
        available = self._available or {"tools": set(), "prompts": set(), "resources": set()}

        # 1) Remove unreachable states and edges that reference them
        self._warn_and_prune_unreachable_states(self._reachable)

        # 2) Prune outgoing edges for states with only terminal incoming (w.r.t. availability)
        self._prune_terminal_only_incoming(available)

    # ----------------------------
    # availability + references
    # ----------------------------
    def _collect_available_and_check_refs(self) -> Dict[str, Set[str]]:
        """
        Build sets of available artifact identifiers and record missing references as issues.

        Returns:
          {
            "tools": {tool_ident, ...},
            "prompts": {prompt_ident, ...},
            "resources": {resource_ident, ...},
          }
        """
        tool_refs: Set[str] = set()
        prompt_refs: Set[str] = set()
        resource_refs: Set[str] = set()

        # Gather referenced artifacts from edges via Σ
        for e in self.edges:
            sym = self.symbols_by_id.get(e.symbol_id)
            if sym is None:
                # Already reported as structural error above
                continue
            if sym.type == "tool":
                tool_refs.add(sym.ident)
            elif sym.type == "prompt":
                prompt_refs.add(sym.ident)
            elif sym.type == "resource":
                resource_refs.add(sym.ident)

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

        resource_idents: Set[str] = set()
        try:
            if self.resource_manager is None:
                raise ValueError("No resource manager provided.")
            resources: List[Resource] = self.resource_manager.list_resources()
            # Annahme: sym.ident entspricht der Manager-Identifikation (z. B. r.name oder str(r.uri))
            # Bewusst konservativ: verwenden str(r.uri) wie bisher.
            resource_idents = {str(r.uri) for r in resources}
            for missing in sorted(resource_refs - resource_idents):
                self.issues.append(ValidationIssue("error", f"Referenced resource '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Resource check skipped: {e}"))

        return {
            "tools": tool_names,
            "prompts": prompt_names,
            "resources": resource_idents,
        }

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

        # Pre-index edges by source for efficient BFS
        by_src: Dict[str, List[Edge]] = defaultdict(list)
        for e in self.edges:
            by_src[e.from_state].append(e)

        while q:
            sname = q.popleft()
            for e in by_src.get(sname, []):
                sym = self.symbols_by_id.get(e.symbol_id)
                if sym is None:
                    # Unknown symbol-id is a structural error; ignore in traversal
                    continue
                if not self._is_symbol_available(sym, available):
                    continue

                dst = e.to_state
                dst_state = self.states.get(dst)
                if dst_state and e.symbol_id in dst_state.terminals:
                    found_terminal_edge = True

                if dst in self.states and dst not in seen:
                    seen.add(dst)
                    q.append(dst)

        return seen, found_terminal_edge

    # ----------------------------------------------
    # prune "terminal-only incoming"
    # ----------------------------------------------
    def _prune_terminal_only_incoming(self, available: Dict[str, Set[str]]) -> None:
        """
        For any state S that has outgoing edges but **all available incoming edges** are terminal
        w.r.t. S.terminals (and S is not the initial state), its outgoing edges are unreachable.
        We remove all edges with from_state == S and emit a warning.

        Implementation note:
        - We update `self.edges` **in place** (slice assignment) to preserve list identity
            for callers holding a reference to the same list object.
        """
        if not self.states or not self.edges:
            return

        initial = self.initial_state
        if initial is None:
            return  # already handled

        # Build incoming map over available edges: target -> list[symbol_id]
        incoming: Dict[str, List[str]] = defaultdict(list)
        for e in self.edges:
            sym = self.symbols_by_id.get(e.symbol_id)
            if sym is None or not self._is_symbol_available(sym, available):
                continue
            incoming[e.to_state].append(e.symbol_id)

        # Determine states to prune (outgoing)
        to_prune: List[str] = []
        has_outgoing: Dict[str, bool] = defaultdict(bool)
        for e in self.edges:
            has_outgoing[e.from_state] = True

        for name, st in self.states.items():
            if name == initial:
                continue
            if not has_outgoing.get(name, False):
                continue
            in_syms = incoming.get(name, [])
            if not in_syms:
                # No available incoming → reachability pruning handles it.
                continue
            if all(sid in st.terminals for sid in in_syms):
                to_prune.append(name)

        if not to_prune:
            return

        # Remove all edges from these states (in place to preserve aliasing)
        to_prune_set = set(to_prune)
        before = len(self.edges)
        filtered = [e for e in self.edges if e.from_state not in to_prune_set]
        removed = before - len(filtered)
        self.edges[:] = filtered  # <-- in-place update (no rebinding)

        for name in to_prune:
            self.issues.append(
                ValidationIssue(
                    "warning",
                    f"Outgoing edges from state '{name}' pruned: only terminal incoming edges present."
                )
            )
        if removed > 0:
            logger.debug("Pruned %d edges due to terminal-only incoming.", removed)

    # ----------------------------
    # post: unreachable cleanup
    # ----------------------------
    def _warn_and_prune_unreachable_states(self, reachable: Set[str]) -> None:
        """
        Emit warnings for states not reachable from the initial state and remove them.
        Afterwards, remove edges that reference removed states.
        """
        if not self.states:
            return

        to_remove = [name for name in self.states.keys() if name not in reachable]
        if not to_remove:
            return

        for name in to_remove:
            self.issues.append(
                ValidationIssue("warning", f"State '{name}' is unreachable from initial and was removed.")
            )
            del self.states[name]

        removed_set = set(to_remove)

        # Filter global edges: drop any edge touching removed states
        before = len(self.edges)
        self.edges = [e for e in self.edges if e.from_state not in removed_set and e.to_state not in removed_set]
        pruned = before - len(self.edges)
        if pruned > 0:
            self.issues.append(
                ValidationIssue("warning", f"Pruned {pruned} edges referencing removed states.")
            )

    # ----------------------------
    # helpers (kept minimal)
    # ----------------------------
    @staticmethod
    def _is_symbol_available(sym: InputSymbol, available: Dict[str, Set[str]]) -> bool:
        """Check artifact availability for a symbol."""
        if sym.type == "tool":
            return sym.ident in available["tools"]
        if sym.type == "prompt":
            return sym.ident in available["prompts"]
        if sym.type == "resource":
            return sym.ident in available["resources"]
        return False  # Unknown kinds are treated as unavailable
